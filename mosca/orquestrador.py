"""O laço principal: jogo -> olho -> cérebro -> teclas e mosca 3D, mais gravação,
torneio, treino automático e registro das partidas."""

import collections
import re
import sys
import time
from datetime import datetime

import numpy as np
from PyQt6 import QtCore, QtGui

from comparar import melhoria_percentual
from registro import registrar_partida, marcar_torneio
from .aprendizado import Gravador, Imitacao, Torneio
from .config import ACOES, ARQUIVO_DESAFIANTE, PASTA, PASTA_GRAVACOES_MOSCA, QUADRO_MS, ROTULO_TECLA
from .estimulos import DetectorLoop, DetectorParada, DetectorPresa, ExploradorSalas, LeitorHUD, LeitorMapa
from .interface import Painel


class Orquestrador(QtCore.QObject):
    """Um passo por quadro: jogo -> cérebro -> (mosca 3D, ações no jogo)."""

    CICLO_S = 600  # a cada ~10 min de jogo da mosca, treina uma nova desafiante

    def __init__(self, jogo, cerebro, mosca, manual=False):
        """`manual`: versão escolhida à mão (--treino N): sem torneio nem ciclo."""
        super().__init__()
        self.jogo, self.cerebro, self.mosca = jogo, cerebro, mosca
        self.painel = Painel(cerebro, mosca)
        self.torneio = None
        if hasattr(jogo, "controlando") and not manual:
            self.torneio = Torneio()
        self.modelos = {"campea": cerebro.modelo, "desafiante": None}
        if self.torneio is not None and self.torneio.em_disputa:
            self.modelos["desafiante"] = Imitacao.carregar(ARQUIVO_DESAFIANTE)
        self.papel = "campea"
        self.gravador_mosca = None  # as partidas da mosca, para ela aprender com elas

        cartao_mosca = self.painel.cartao_mosca
        cartao_mosca.bt_evolucao.clicked.connect(lambda: QtCore.QProcess.startDetached(
            sys.executable, [str(PASTA / "evolucao.py")], str(PASTA)))
        self.gravador = None
        self.hud = LeitorHUD() if hasattr(jogo, "controlando") else None
        self.parada = DetectorParada()
        self.presa = DetectorPresa()
        self.loop = DetectorLoop()
        self.explorador = ExploradorSalas() if self.hud is not None else None
        self.leitor_mapa = LeitorMapa() if self.hud is not None else None
        self._desde_mapa = 0.0  # segundos de jogo da mosca desde a última olhada no mapa
        self._foto_mapa_em = None
        self._ultimo_dano = 0.0
        self._ultimas_telas = collections.deque(maxlen=10)  # ~0,3 s, para o diagnóstico
        self._sorteio = np.random.default_rng()
        self._recompensas = collections.deque()  # (instante, valor) dos últimos 10 s
        self._ultimo_evento = (None, 0.0)
        self._recompensa_quadro = 0.0
        self.partida = None  # o que a mosca fez desde que ligou "Controlar jogo"
        self._envios = []  # threads de registro de partidas
        self.treino = None  # QProcess do treinar.py, quando rodando
        self._treinar_de_novo = False
        self._info_treino, self._info_ate = None, 0.0
        if self.hud is None:
            cartao_mosca.m_recompensa.hide()  # o jogo demo não tem HUD
        if hasattr(jogo, "controlando"):
            cartao_mosca.bt_controlar.toggled.connect(self.alternar_controle)
            cartao_mosca.bt_gravar.toggled.connect(self.alternar_gravacao)
        else:  # o jogo demo já é controlado sempre e não dá para jogar nele
            cartao_mosca.bt_controlar.hide()
            cartao_mosca.bt_gravar.hide()

        geo = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        largura, altura = min(geo.width() - 40, 1400), min(geo.height() - 80, 780)
        self.painel.setGeometry(geo.x() + (geo.width() - largura) // 2, geo.y() + 40, largura, altura)
        self.painel.show()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(QUADRO_MS)

    def alternar_controle(self, ligado):
        self.jogo.controlando = ligado
        if ligado:
            self.jogo.janelas_proprias.add(int(self.painel.winId()))
            self.jogo.focar()
            if self.torneio is not None:
                self._usar(self.torneio.quem_joga())
                self.gravador_mosca = Gravador(PASTA_GRAVACOES_MOSCA)
            self._comecar_partida()
        else:
            self.jogo.soltar_tudo()
            self._terminar_partida()
            self._parar_gravacao_mosca()
            if self.torneio is not None and self.torneio.em_disputa:
                self.torneio.fechar_rodada(self.papel)

    # --- torneio: campeã x desafiante, e o ciclo de aprender jogando ---

    NOMES_PAPEIS = {"campea": "campeã", "desafiante": "desafiante"}

    def _usar(self, papel):
        """Põe a campeã ou a desafiante no cérebro da mosca."""
        self.papel = papel
        modelo = self.modelos[papel]
        if modelo is not None:
            modelo.papel = self.NOMES_PAPEIS[papel] if self.torneio and self.torneio.em_disputa else None
        self.cerebro.modelo = modelo
        self.painel.cartao_cerebro.atualizar_selecao()

    def _nome(self, papel):
        modelo = self.modelos[papel]
        numero = f" #{modelo.treino_id}" if modelo is not None and modelo.treino_id else ""
        return self.NOMES_PAPEIS[papel] + numero

    def _avisar(self, texto, segundos=15):
        self._info_treino, self._info_ate = texto, time.monotonic() + segundos

    def _parar_gravacao_mosca(self):
        if self.gravador_mosca is not None:
            self.gravador_mosca.parar()
            self.gravador_mosca = None

    def _torneio_quadro(self):
        """Depois de cada quadro em que a mosca jogou de fato."""
        t = self.torneio
        trocar = t.contar(self.papel, QUADRO_MS / 1000, self._recompensa_quadro)
        resultado = t.veredito()
        if resultado:
            self._encerrar_torneio(resultado)
        elif trocar:
            self._terminar_partida()  # cada rodada vira uma partida com o seu treino
            self._usar(t.quem_joga())
            self._comecar_partida()
            self._avisar(f"Vez da {self._nome(self.papel)}", 4)
        if not t.em_disputa and self.treino is None and t.ciclo_cumprido(self.CICLO_S):
            self._ciclo()

    def _encerrar_torneio(self, resultado):
        t = self.torneio
        desafiante, campea = self.modelos["desafiante"], self.modelos["campea"]
        placar = {
            "resultado": resultado,
            "contra_treino": campea.treino_id if campea else None,
            "por_minuto": round(t.por_minuto("desafiante"), 2),
            "por_minuto_campea": round(t.por_minuto("campea"), 2),
            "minutos": round(t.estado["placar"]["desafiante"]["segundos"] / 60, 1),
            "minutos_campea": round(t.estado["placar"]["campea"]["segundos"] / 60, 1),
            "incerteza": round(min(t.incerteza(), 99.0), 2),
            "melhoria_pct": None,
            "rodadas": {p: [round(r, 2) for r in t.estado["rodadas"][p]] for p in t.PAPEIS},
        }
        pct = melhoria_percentual(placar["por_minuto_campea"], placar["por_minuto"])
        placar["melhoria_pct"] = None if pct is None else round(pct, 1)
        melhoria = f" = {pct:+.0f}% de recompensa/min" if pct is not None else ""
        nome_d, nome_c = self._nome("desafiante"), self._nome("campea")
        self._terminar_partida()
        t.encerrar(resultado)
        self._envios.append(marcar_torneio(desafiante.treino_id if desafiante else None, placar))
        if resultado == "venceu":
            self.modelos["campea"] = desafiante
            texto = (f"🏆 A {nome_d} venceu ({placar['por_minuto']:+.1f}/min contra "
                     f"{placar['por_minuto_campea']:+.1f}/min{melhoria}) e virou a campeã")
        elif resultado == "interrompida":
            texto = f"Disputa da {nome_d} interrompida: uma desafiante nova, com a sua gravação, vai treinar"
        else:
            texto = (f"A {nome_d} perdeu ({placar['por_minuto']:+.1f}/min contra "
                     f"{placar['por_minuto_campea']:+.1f}/min{melhoria}): a {nome_c} continua")
        self.modelos["desafiante"] = None
        self._usar("campea")
        self._comecar_partida()
        self._avisar(texto, 30)

    def _ciclo(self):
        """A mosca jogou o bastante desde o último treino: treina uma desafiante
        com tudo, inclusive as partidas dela (salvas antes de treinar)."""
        self._parar_gravacao_mosca()
        if self.jogo.controlando:
            self.gravador_mosca = Gravador(PASTA_GRAVACOES_MOSCA)
        self.torneio.zerar_ciclo()
        self.treinar()

    def _texto_torneio(self):
        t = self.torneio
        if t is None or self.partida is None:
            return None
        if not t.em_disputa:
            falta = max(0, self.CICLO_S - t.estado["mosca_desde_treino"]) / 60
            return f"🏆 {self._nome('campea')} jogando · próximo treino em ~{falta:.0f} min de jogo"
        partes = []
        for papel in ("desafiante", "campea"):
            minutos = t.estado["placar"][papel]["segundos"] / 60
            partes.append(f"{self._nome(papel)} {t.por_minuto(papel):+.1f}/min ({minutos:.1f} min)")
        incerteza = t.incerteza()
        margem = f" · incerteza ±{2 * incerteza:.1f}" if incerteza != float("inf") else ""
        return f"⚔ {self._nome(self.papel)} jogando · " + " × ".join(partes) + margem

    # --- partidas: cada vez que a mosca joga sozinha vira uma linha no Supabase ---

    MINIMO_PARTIDA_S = 5

    def _comecar_partida(self):
        self.partida = {
            "inicio": time.time(),
            "quadros": 0,
            "eventos": collections.Counter(),
            "recompensa": 0.0,
            "teclas": np.zeros(len(ACOES)),
        }

    def _contar_partida(self, eventos):
        """Conta um quadro só se a mosca estava de fato no controle do jogo."""
        p = self.partida
        if p is None or self.jogo.aviso or not self.jogo.em_foco():
            return
        p["quadros"] += 1
        p["eventos"].update(eventos)
        p["recompensa"] += self._recompensa_quadro
        teclas = np.array([a in self.jogo.apertadas for a in ACOES])
        p["teclas"] += teclas
        if self.gravador_mosca is not None:
            self.gravador_mosca.adicionar(
                self.cerebro.reduzida, teclas, self._recompensa_quadro, self.hud.vida,
                "sala_nova" in self._eventos_quadro, "presa" in self._eventos_quadro,
                "loop" in self._eventos_quadro,
            )
        self._habito_do_mapa()
        if self.torneio is not None:
            self._torneio_quadro()

    # --- olhar o mapa: de tempos em tempos, num momento calmo, segura Tab ---

    OLHAR_MAPA_S = 45  # de jogo da mosca entre uma olhada e outra
    CALMA_S = 5  # sem tomar dano há tanto tempo
    PASTA_MAPAS = PASTA / "mapas"
    GUARDAR_MAPAS = 100

    def _habito_do_mapa(self):
        self._desde_mapa += QUADRO_MS / 1000
        agora = time.monotonic()
        if self._desde_mapa >= self.OLHAR_MAPA_S and agora - self._ultimo_dano > self.CALMA_S:
            self._desde_mapa = 0.0
            self.cerebro.pulsar_zona("Mapa")  # a zona do mapa acende e a pata aperta Tab
            self._foto_mapa_em = agora + 1.0  # o mapa leva um instante para abrir
            self._avisar("🗺 Olhando o mapa", 3)

    def _fotografar_mapa(self, imagem):
        """Guarda o mapa aberto (para calibrar a leitura da posição pela Bússola)."""
        from PIL import Image

        self._foto_mapa_em = None
        self.PASTA_MAPAS.mkdir(exist_ok=True)
        Image.fromarray(np.ascontiguousarray(imagem)).save(
            self.PASTA_MAPAS / time.strftime("mapa_%Y-%m-%d_%H%M%S.png")
        )
        for velho in sorted(self.PASTA_MAPAS.glob("mapa_*.png"))[: -self.GUARDAR_MAPAS]:
            velho.unlink()

    def _terminar_partida(self):
        p, self.partida = self.partida, None
        if p is None:
            return
        segundos = p["quadros"] * QUADRO_MS / 1000
        if segundos < self.MINIMO_PARTIDA_S:
            return  # ligou e desligou: não vale como partida
        modelo = self.cerebro.modelo
        uso = p["teclas"] / p["quadros"]
        self._envios.append(registrar_partida({
            "inicio": datetime.fromtimestamp(p["inicio"]).astimezone().isoformat(),
            "fim": datetime.now().astimezone().isoformat(),
            "segundos": round(segundos, 1),
            "quadros": p["quadros"],
            "treino_id": modelo.treino_id if modelo is not None else None,
            "cerebro": self.cerebro.origem,
            "recompensa_total": round(p["recompensa"], 2),
            "recompensa_por_minuto": round(p["recompensa"] / segundos * 60, 2),
            "danos": p["eventos"]["dano"],
            "acertos": p["eventos"]["acerto"],
            "geo": p["eventos"]["geo"],
            "curas": p["eventos"]["cura"],
            "paradas": p["eventos"]["parada"],
            "mortes": p["eventos"]["morte"],
            "salas_novas": p["eventos"]["sala_nova"],
            "presas": p["eventos"]["presa"],
            "loops": p["eventos"]["loop"],
            "lugares_mapa": p["eventos"]["mapa_novo"],
            "uso_teclas": {a: round(float(u), 4) for a, u in zip(ACOES, uso)},
        }))

    def alternar_gravacao(self, ligado):
        bt_controlar = self.painel.cartao_mosca.bt_controlar
        if ligado:
            # Quem joga é você: a mosca não pode apertar teclas ao mesmo tempo
            bt_controlar.setChecked(False)
            bt_controlar.setEnabled(False)
            self.gravador = Gravador()
            self.jogo.focar()
        else:
            self.gravador.parar()
            self.gravador = None
            bt_controlar.setEnabled(True)
            self._pedir_treino()  # aprende com tudo o que já foi gravado

    def _pedir_treino(self):
        """Fim de uma gravação sua: treina já. Uma disputa em andamento é
        interrompida (fica registrada assim no Supabase): a desafiante nova aprende
        com tudo o que a atual aprendeu e mais a gravação, e a campeã não muda."""
        if self.torneio is not None and self.torneio.em_disputa:
            self._encerrar_torneio("interrompida")
        self.treinar()

    def _arquitetura_do_treino(self):
        """Reveza as arquiteturas: depois de uma desafiante da mesma arquitetura
        da campeã, a próxima é da outra. Assim as duas seguem competindo."""
        campea = self.modelos["campea"]
        da_campea = getattr(campea, "arquitetura", "mlp") if campea is not None else "mlp"
        if self.torneio is None:
            return da_campea
        outra = "conectoma" if da_campea == "mlp" else "mlp"
        return outra if self.torneio.estado.get("ultima_arquitetura") == da_campea else da_campea

    def treinar(self):
        """Roda o treinar.py em outro processo (não trava o painel) e, no fim,
        troca o cérebro da mosca pelo modelo novo."""
        if self.treino is not None:
            self._treinar_de_novo = True  # termina este e treina de novo com tudo
            return
        processo = QtCore.QProcess(self)
        processo.setWorkingDirectory(str(PASTA))
        processo.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        processo.readyReadStandardOutput.connect(self._saida_treino)
        processo.finished.connect(self._fim_treino)
        self._log_treino = []
        self._info_treino = "🧠 Treinando a mosca…"
        self.treino = processo
        arquitetura = self._arquitetura_do_treino()
        self._info_treino = f"🧠 Treinando a mosca ({'conectoma' if arquitetura == 'conectoma' else 'rede inventada'})…"
        processo.start(sys.executable, ["-u", str(PASTA / "treinar.py"), "--arquitetura", arquitetura])

    def _saida_treino(self):
        texto = bytes(self.treino.readAllStandardOutput()).decode(errors="replace")
        self._log_treino.append(texto)
        for epoca in re.finditer(r"época\s+(\d+)/(\d+)", texto):
            self._info_treino = f"🧠 Treinando a mosca… época {epoca[1]}/{epoca[2]}"

    def _fim_treino(self, codigo, _status):
        log = "".join(self._log_treino)
        (PASTA / "treino.log").write_text(log)  # a tabela de resultado fica aqui
        self.treino = None
        if codigo == 0 and "modelo salvo" in log:
            self._nova_desafiante()
        elif "mínimo" in log:
            self._info_treino = "🧠 Pouca gravação para treinar: grave um pouco mais"
        else:
            self._info_treino = "⚠ O treino falhou (veja treino.log)"
        self._info_ate = time.monotonic() + 10
        if self._treinar_de_novo:
            self._treinar_de_novo = False
            self.treinar()

    def _nova_desafiante(self):
        if self.torneio is None:  # versão escolhida à mão: não mexe em quem joga
            self._info_treino = "🧠 Nova desafiante treinada; abra o painel sem --treino para ela disputar"
            return
        jogando = self.partida is not None
        if jogando:
            self._terminar_partida()
        promovida = self.torneio.nova_desafiante()
        if promovida:
            nova = self.modelos["campea"] = Imitacao.carregar()
            self._info_treino = f"🧠 {promovida}"
        else:
            nova = self.modelos["desafiante"] = Imitacao.carregar(ARQUIVO_DESAFIANTE)
            self._info_treino = (f"⚔ Nova {self._nome('desafiante')} treinada: ela disputa com a "
                                 f"{self._nome('campea')} quando a mosca jogar")
        self.torneio.estado["ultima_arquitetura"] = nova.arquitetura  # para revezar
        self.torneio.salvar()
        self._usar(self.torneio.quem_joga() if jogando else "campea")
        if jogando:
            self._comecar_partida()

    def _gravar(self):
        """Um quadro de gravação: só com o jogo em foco, senão gravaria teclas
        que você digita em outro programa."""
        g = self.gravador
        minutos, segundos = divmod(int(time.monotonic() - g.inicio), 60)
        texto = f"⏺ Gravando {minutos:02d}:{segundos:02d} · {g.total:,} quadros".replace(",", ".")
        if self.jogo.aviso or not self.jogo.em_foco():
            return texto + " · pausado: clique no jogo", {a: 0.0 for a in ACOES}
        teclas = self.jogo.teclas_do_usuario()
        g.adicionar(
            self.cerebro.reduzida, teclas, self._recompensa_quadro, self.hud.vida,
            "sala_nova" in self._eventos_quadro, "presa" in self._eventos_quadro,
                "loop" in self._eventos_quadro,
        )
        return texto, {a: float(t) for a, t in zip(ACOES, teclas)}

    def soltar_teclas(self):
        if hasattr(self.jogo, "soltar_tudo"):
            self.jogo.soltar_tudo()

    def encerrar(self):
        # Para o timer antes de soltar: um último tick poderia reapertar teclas
        self.timer.stop()
        if self.gravador is not None:
            self.gravador.parar()  # salva o que falta
            self.gravador = None
        self._parar_gravacao_mosca()
        if self.explorador is not None:
            self.explorador.salvar()
        if self.treino is not None:
            # O modelo só é trocado no fim do treino, então parar no meio é seguro
            self.treino.finished.disconnect()
            self.treino.kill()
            self.treino.waitForFinished(2000)
        if hasattr(self.jogo, "controlando"):
            self.jogo.controlando = False
        self.soltar_teclas()
        if self.torneio is not None and self.partida is not None and self.torneio.em_disputa:
            self.torneio.fechar_rodada(self.papel)  # salva o placar da rodada em andamento
        self._terminar_partida()
        for envio in self._envios:
            envio.join(timeout=10)  # dá tempo de a última partida chegar ao Supabase

    NOMES_EVENTOS = {
        "dano": "tomou dano", "cura": "curou", "acerto": "acertou inimigo", "geo": "pegou geo",
        "parada": "ficou parada", "morte": "morreu", "sala_nova": "sala nova!",
        "presa": "ficou presa", "mapa_novo": "lugar novo no mapa!", "loop": "andando em círculos",
    }

    # Reflexo de sair do lugar: moscas paradas demais fazem movimentos
    # espontâneos. Tira a mosca do banco (onde ela volta toda vez que morre),
    # de cantos e paredes. Só quando ela está no controle do jogo.
    REFLEXOS = ["Esquerda", "Direita", "Pular"]

    def _reflexo(self):
        acao = self._sorteio.choice(self.REFLEXOS)
        self.cerebro.pulsar_zona(acao)
        return f"reflexo: tentou {ROTULO_TECLA[acao]}"

    def _mudar_de_ideia(self):
        """Andando em círculos: escolhe um lado e se compromete com ele por ~3 s,
        com um pulo no começo (o loop é justamente ficar trocando de lado)."""
        lado = self._sorteio.choice(["Esquerda", "Direita"])
        outro = "Direita" if lado == "Esquerda" else "Esquerda"
        self.cerebro.pulso_zona_ate[outro] = 0.0
        self.cerebro.pulsar_zona(lado, 3.0)
        self.cerebro.pulsar_zona("Pular", 0.5)
        return f"reflexo: mudou de ideia ({ROTULO_TECLA[lado]} por 3 s)"

    def _escapar(self):
        """Presa forçando para um lado: meia-volta (às vezes pulando junto)."""
        outro = "Esquerda" if self.presa.lado == "Direita" else "Direita"
        self.cerebro.pulsar_zona(outro)
        if self._sorteio.random() < 0.5:
            self.cerebro.pulsar_zona("Pular")
            return f"reflexo: meia-volta ({ROTULO_TECLA[outro]}) pulando"
        return f"reflexo: meia-volta ({ROTULO_TECLA[outro]})"

    # --- diagnóstico: um print de cada evento, para conferir se a leitura está certa ---

    PASTA_DIAGNOSTICO = PASTA / "diagnostico"
    GUARDAR_POR_EVENTO = 20

    def _diagnostico(self, evento, imagem):
        """Salva "antes" (~0,3 s antes) e "agora" lado a lado com o nome do evento."""
        from PIL import Image, ImageDraw

        antes = self._ultimas_telas[0]
        largura = 480
        quadros = []
        for tela in (antes, imagem):
            img = Image.fromarray(np.ascontiguousarray(tela))
            quadros.append(img.resize((largura, round(img.height * largura / img.width))))
        altura = quadros[0].height
        folha = Image.new("RGB", (2 * largura + 10, altura + 34), (12, 13, 20))
        folha.paste(quadros[0], (0, 34))
        folha.paste(quadros[1], (largura + 10, 34))
        texto = ImageDraw.Draw(folha)
        nome = self.NOMES_EVENTOS.get(evento, evento)
        texto.text((8, 10), f"{nome}   ·   antes (~0,3 s)", fill=(200, 205, 225))
        texto.text((largura + 18, 10), f"agora   ·   {time.strftime('%H:%M:%S')}", fill=(200, 205, 225))
        pasta = self.PASTA_DIAGNOSTICO / evento
        pasta.mkdir(parents=True, exist_ok=True)
        folha.save(pasta / time.strftime(f"%Y-%m-%d_%H%M%S_{evento}.jpg"), quality=85)
        for velho in sorted(pasta.glob("*.jpg"))[: -self.GUARDAR_POR_EVENTO]:
            velho.unlink()

    def _ler_hud(self, imagem):
        """Eventos do jogo -> dopamina no cérebro + painel de recompensa."""
        self._recompensa_quadro = 0.0
        self._eventos_quadro = []
        if self.hud is None or self.jogo.aviso:
            return
        self._ultimas_telas.append(imagem)
        valor, eventos = self.hud.passo(imagem)
        if self.cerebro.reduzida is not None:
            eventos += self.explorador.passo(self.cerebro.reduzida)
            if "sala_nova" in eventos:
                self.explorador.salvar()
        if "dano" in eventos or "morte" in eventos:
            self._ultimo_dano = time.monotonic()
        eventos += self.parada.passo(
            self.cerebro.movimento_medio, self.hud.visivel, self.hud.gastando_alma
        )
        if self.cerebro.reduzida is not None:
            if self.jogo.controlando:
                apertadas = self.jogo.apertadas
            elif self.gravador is not None:  # você jogando: as suas teclas
                apertadas = {a for a, t in zip(ACOES, self.jogo.teclas_do_usuario()) if t}
            else:
                apertadas = set()
            eventos += self.presa.passo(
                self.cerebro.reduzida, "Esquerda" in apertadas, "Direita" in apertadas, self.hud.visivel
            )
        if self.cerebro.reduzida is not None:
            bom = any(LeitorHUD.RECOMPENSA[e] > 0 for e in eventos)
            eventos += self.loop.passo(self.cerebro.reduzida, bom, self.hud.visivel)
        reflexo = None
        encostada, self.presa.encostada = self.presa.encostada, False
        if "loop" in eventos and self.jogo.controlando:
            reflexo = self._mudar_de_ideia()
        elif ("presa" in eventos or encostada) and self.jogo.controlando:
            reflexo = self._escapar()  # já com 4 s encostada; a punição só vem com 6 s
        elif "parada" in eventos and self.jogo.controlando:
            reflexo = self._reflexo()
        if self._foto_mapa_em is not None and time.monotonic() >= self._foto_mapa_em:
            self._fotografar_mapa(imagem)
            eventos += self.leitor_mapa.ler(imagem)
        valor = sum(LeitorHUD.RECOMPENSA[e] for e in eventos)
        self._eventos_quadro = eventos
        for evento in set(eventos) - {"parada"}:  # parada é frequente e já foi conferida
            self._diagnostico(evento, imagem)
        agora = time.monotonic()
        if eventos:
            self._recompensa_quadro = valor
            self.cerebro.recompensa(valor)
            self._recompensas.append((agora, valor))
            texto = ", ".join(self.NOMES_EVENTOS[e] for e in eventos)
            self._ultimo_evento = (f"{texto} · {reflexo}" if reflexo else texto, agora)
        while self._recompensas and self._recompensas[0][0] < agora - 10:
            self._recompensas.popleft()
        texto, quando = self._ultimo_evento
        self.painel.cartao_mosca.atualizar_recompensa(
            sum(v for _, v in self._recompensas),
            self.hud.vida if self.hud.visivel else None,
            texto if agora - quando < 3 else None,
            self.explorador.salas,
            self.leitor_mapa.posicao,
        )

    def tick(self):
        imagem = self.jogo.quadro()
        _, acoes = self.cerebro.passo(imagem)
        self._ler_hud(imagem)  # depois do cérebro: usa o movimento que o olho viu
        self.jogo.passo(acoes)
        self._contar_partida(self._eventos_quadro)
        gravacao = None
        if self.gravador is not None:
            # Gravando, as patas da mosca repetem as teclas que você aperta
            gravacao, acoes = self._gravar()
        cartao_mosca = self.painel.cartao_mosca
        cartao_mosca.mostrar(self.mosca.passo(acoes, imagem))
        comando = np.concatenate([self.cerebro.zona[a] for a in ROTULO_TECLA])
        aviso = (
            self.mosca.erro
            or getattr(self.jogo, "aviso", None)
            or getattr(self.jogo, "aviso_controle", None)
        )
        info = self._texto_torneio()
        if self.treino is not None or time.monotonic() < self._info_ate:
            info = self._info_treino
        cartao_mosca.atualizar_metricas(
            self.cerebro.taxas[comando].mean(), acoes, aviso, gravacao, info
        )
        self.painel.cartao_cerebro.atualizar()
