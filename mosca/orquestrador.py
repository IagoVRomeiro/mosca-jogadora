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
from .estimulos import DetectorParada, LeitorHUD
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
        cartao_mosca.bt_pausar.clicked.connect(lambda: self.alternar_pausa())
        cartao_mosca.bt_reiniciar.clicked.connect(lambda: self.reiniciar())
        self.gravador = None
        self.hud = LeitorHUD() if hasattr(jogo, "controlando") else None
        self.parada = DetectorParada()
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
                self.cerebro.reduzida, teclas, self._recompensa_quadro, self.hud.vida
            )
        if self.torneio is not None:
            self._torneio_quadro()

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
            self.treinar()  # aprende com tudo o que já foi gravado

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
        processo.start(sys.executable, ["-u", str(PASTA / "treinar.py")])

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
            self.modelos["campea"] = Imitacao.carregar()
            self._info_treino = f"🧠 {promovida}"
        else:
            self.modelos["desafiante"] = Imitacao.carregar(ARQUIVO_DESAFIANTE)
            self._info_treino = (f"⚔ Nova {self._nome('desafiante')} treinada: ela disputa com a "
                                 f"{self._nome('campea')} quando a mosca jogar")
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
        g.adicionar(self.cerebro.reduzida, teclas, self._recompensa_quadro, self.hud.vida)
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

    def alternar_pausa(self):
        self.mosca.pausado = not self.mosca.pausado
        bt = self.painel.cartao_mosca.bt_pausar
        if self.mosca.pausado:
            self.soltar_teclas()
            self.timer.stop()
            bt.setText("▶  Continuar")
        else:
            self.timer.start(QUADRO_MS)
            bt.setText("❚❚  Pausar")
        self.painel.cartao_mosca.atualizar_metricas(0, {})

    def reiniciar(self):
        if self.hud is not None:
            self.hud.reiniciar()
        self.parada.reiniciar()
        self.cerebro.reiniciar()
        self.jogo.reiniciar()
        self.mosca.pedido_reinicio = True
        self.painel.cartao_cerebro.atualizar_selecao()

    NOMES_EVENTOS = {
        "dano": "tomou dano", "cura": "curou", "acerto": "acertou inimigo", "geo": "pegou geo",
        "parada": "ficou parada", "morte": "morreu",
    }

    # Reflexo de sair do lugar: moscas paradas demais fazem movimentos
    # espontâneos. Tira a mosca do banco (onde ela volta toda vez que morre),
    # de cantos e paredes. Só quando ela está no controle do jogo.
    REFLEXOS = ["Esquerda", "Direita", "Pular"]

    def _reflexo(self):
        acao = self._sorteio.choice(self.REFLEXOS)
        self.cerebro.pulsar_zona(acao)
        return f"reflexo: tentou {ROTULO_TECLA[acao]}"

    def _ler_hud(self, imagem):
        """Eventos do jogo -> dopamina no cérebro + painel de recompensa."""
        self._recompensa_quadro = 0.0
        self._eventos_quadro = []
        if self.hud is None or self.jogo.aviso:
            return
        valor, eventos = self.hud.passo(imagem)
        eventos += self.parada.passo(
            self.cerebro.movimento_medio, self.hud.visivel, self.hud.gastando_alma
        )
        reflexo = None
        if "parada" in eventos and self.jogo.controlando:
            reflexo = self._reflexo()
        valor = sum(LeitorHUD.RECOMPENSA[e] for e in eventos)
        self._eventos_quadro = eventos
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
