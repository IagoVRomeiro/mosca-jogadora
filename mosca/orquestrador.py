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
from .correcao import Correcao
from .curriculo import Curriculo
from .especialistas import PASTA_ESPECIALISTAS, Especialistas
from .juiz import DetectoresPelaPosicao, JuizDoJogo, MemoriaDePerigos, SaidasDoSalao, eh_arena
from .config import ACOES, ARQUIVO_DESAFIANTE, PASTA, PASTA_GRAVACOES_MOSCA, QUADRO_MS, ROTULO_TECLA
from .estimulos import DetectorLoop, DetectorParada, DetectorPresa, ExploradorSalas, LeitorHUD
from .interface import Painel


class Orquestrador(QtCore.QObject):
    """Um passo por quadro: jogo -> cérebro -> (mosca 3D, ações no jogo)."""

    CICLO_S = 600  # a cada ~10 min de jogo da mosca, treina uma nova desafiante
    GRAVACAO_MINIMA_S = 60  # gravação mais curta (um atalho apertado sem querer) não treina

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
        self.correcao = Correcao()  # você assumindo quando ela erra (mosca/correcao.py)
        self.gravador_correcao = None
        self._correcao_s = 0.0  # correções desde que a mosca foi ligada

        cartao_mosca = self.painel.cartao_mosca
        cartao_mosca.bt_evolucao.clicked.connect(lambda: QtCore.QProcess.startDetached(
            sys.executable, [str(PASTA / "evolucao.py")], str(PASTA)))
        self.gravador = None
        self.hud = LeitorHUD() if hasattr(jogo, "controlando") else None
        self.parada = DetectorParada()
        self.presa = DetectorPresa()
        self.loop = DetectorLoop()
        self.explorador = ExploradorSalas() if self.hud is not None else None
        self.juiz = None  # eventos de dentro do jogo (mod/MoscaEventos); sem ele, pela tela
        if self.hud is not None:
            self.pela_posicao = DetectoresPelaPosicao()
            self.perigos = MemoriaDePerigos()
            self.saidas = SaidasDoSalao()
            self.curriculo = Curriculo()
            self.especialistas = Especialistas(carregar=Imitacao.carregar)
            try:
                self.juiz = JuizDoJogo()
            except OSError as e:  # porta ocupada (outro painel aberto?)
                print(f"⚠ juiz do jogo desligado ({e}): eventos pela tela")
        self._ultimo_dano = 0.0
        self._ultimas_telas = collections.deque(maxlen=10)  # ~0,3 s, para o diagnóstico
        self._sorteio = np.random.default_rng()
        self._escalada_em = float("-inf")  # última tentativa de escalar (reflexo de presa)
        self._pulos_escalada = []  # quando dar os próximos pulos da tentativa
        self._treino_pendente = False  # correções esperando a disputa (desafiante na frente)
        self._recompensas = collections.deque()  # (instante, valor) dos últimos 10 s
        self._ultimo_evento = (None, 0.0)
        self._especialista = None  # (arena, "atual"/"candidato") quando um especialista joga
        self._ultima_arena = None  # (arena, quem jogou) da luta em andamento, para o veredito
        self._treino_especialista = None  # arena do treino em andamento, se for de especialista
        self._fila_especialistas = []  # arenas da sua última gravação, esperando o treino delas
        self._arenas_gravadas = collections.Counter()  # quadros seus em cada arena, na gravação
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

    # Atalhos do teclado (atalho_mosca.sh manda um sinal ao painel): o mesmo
    # atalho liga e desliga. A notificação avisa, porque o painel fica atrás do jogo.
    def atalho(self, qual):
        cartao = self.painel.cartao_mosca
        botao = {"gravar": cartao.bt_gravar, "controlar": cartao.bt_controlar}[qual]
        if not botao.isVisible():
            return
        if not botao.isEnabled():
            self._notificar("Pare a gravação antes de ligar o Controlar jogo (Ctrl+Alt+G)")
            return
        botao.toggle()
        if qual == "gravar":
            self._notificar("⏺ Gravando: você joga" if botao.isChecked()
                            else "⏹ Gravação parada (com 1 min ou mais, a mosca treina com ela)")
        else:
            self._notificar("🎮 A mosca está jogando" if botao.isChecked() else "🎮 Controlar jogo desligado")

    def _parar_com_esc(self):
        """Esc no teclado (ou o pause do controle, pelo plugin): a mosca para de
        jogar, como desligar o Controlar jogo. Senão, no menu de pausa, ela
        sairia apertando as opções."""
        estado = self._estado_jogo
        apertou = bool(getattr(self.jogo, "esc_apertado", lambda: False)()
                       or (estado and "Pausar" in estado.get("acoes", ())))
        antes, self._esc_antes = getattr(self, "_esc_antes", False), apertou
        if apertou and not antes and getattr(self.jogo, "controlando", False):
            self.painel.cartao_mosca.bt_controlar.setChecked(False)  # solta as teclas dela
            self._notificar("⏸ Esc: a mosca parou de jogar (Ctrl+Alt+C liga de novo)")

    @staticmethod
    def _notificar(texto):
        QtCore.QProcess.startDetached("notify-send", ["-a", "Mosca jogadora", "-t", "3000", "Mosca jogadora", texto])

    def alternar_controle(self, ligado):
        self.jogo.controlando = ligado
        if ligado:
            self.jogo.janelas_proprias.add(int(self.painel.winId()))
            if not getattr(self.jogo, "pelo_plugin", False):  # pelo plugin ela joga sem foco
                self.jogo.focar()
            if self.torneio is not None:
                self._usar(self.torneio.quem_joga())
                self.gravador_mosca = Gravador(PASTA_GRAVACOES_MOSCA)
            self._comecar_partida()
        else:
            self.jogo.soltar_tudo()
            if self.correcao.ativa:
                self._fim_correcao(self.correcao.terminar())
            self._terminar_partida()
            self._parar_gravacao_mosca()
            if self._correcao_s >= self.GRAVACAO_MINIMA_S:
                self._avisar(f"🧑 {self._correcao_s / 60:.1f} min de correções: treinando com elas", 10)
                self._correcao_s = 0.0
                self._pedir_treino()
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
        if self._especialista is not None:
            # quem joga é o especialista da arena: a disputa das versões gerais não
            # anda, mas o tempo de jogo conta para o próximo treino geral
            t.estado["mosca_desde_treino"] += QUADRO_MS / 1000
            if not t.em_disputa and self.treino is None and t.ciclo_cumprido(self.CICLO_S):
                self._ciclo()
            return
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
        if self._treino_pendente:  # correções guardadas enquanto ela estava na frente
            self._treino_pendente = False
            self.treinar()

    def _ciclo(self):
        """A mosca jogou o bastante desde o último treino: treina uma desafiante
        com tudo, inclusive as partidas dela (salvas antes de treinar)."""
        self._parar_gravacao_mosca()
        if self.jogo.controlando:
            self.gravador_mosca = Gravador(PASTA_GRAVACOES_MOSCA)
        self.torneio.zerar_ciclo()
        self.treinar()

    def _texto_torneio(self):
        if self._especialista is not None:
            texto = self.especialistas.texto(*self._especialista)
            curriculo = getattr(self, "curriculo", None)
            return f"{texto} · {curriculo.texto()}" if curriculo is not None and curriculo.texto() else texto
        texto = self._texto_da_disputa()
        curriculo = getattr(self, "curriculo", None)
        if texto and curriculo is not None and curriculo.texto():
            return f"{texto} · {curriculo.texto()}"
        return texto

    def _texto_da_disputa(self):
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
            "do_jogo": 0,  # quadros com os eventos vindos do plugin (não da tela)
        }

    def _contar_partida(self, eventos):
        """Conta um quadro só se a mosca estava de fato no controle do jogo."""
        p = self.partida
        if p is None or self.jogo.aviso or not self.jogo.recebe_teclas():
            return
        p["quadros"] += 1
        p["do_jogo"] += self._juiz_ativo
        p["eventos"].update(eventos)
        p["recompensa"] += self._recompensa_quadro
        teclas = np.array([a in self.jogo.apertadas for a in ACOES])
        p["teclas"] += teclas
        if self.gravador_mosca is not None:
            self.gravador_mosca.adicionar(
                self.cerebro.reduzida, teclas, self._recompensa_quadro, self._vida,
                self._eventos_quadro, self._estado_jogo,
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
            "salas_novas": p["eventos"]["sala_nova"],
            "presas": p["eventos"]["presa"],
            "loops": p["eventos"]["loop"],
            "ajudas": p["eventos"]["ajuda"],
            "inimigos_mortos": p["eventos"]["inimigo_morto"],
            "cenas_novas": p["eventos"]["cena_nova"],
            "lugares_novos": p["eventos"]["lugar_novo"],
            "fonte_eventos": "jogo" if p["do_jogo"] * 2 > p["quadros"] else "tela",
            "uso_teclas": {a: round(float(u), 4) for a, u in zip(ACOES, uso)},
        }))

    def alternar_gravacao(self, ligado):
        bt_controlar = self.painel.cartao_mosca.bt_controlar
        if ligado:
            # Quem joga é você: a mosca não pode apertar teclas ao mesmo tempo
            bt_controlar.setChecked(False)
            bt_controlar.setEnabled(False)
            self.gravador = Gravador()
            self._arenas_gravadas = collections.Counter()
            self.jogo.focar()
        else:
            self.gravador.parar()
            segundos = self.gravador.total * QUADRO_MS / 1000
            self.gravador = None
            bt_controlar.setEnabled(True)
            if segundos < self.GRAVACAO_MINIMA_S:
                # fica guardada (entra nos próximos treinos), mas não vale
                # interromper uma disputa nem treinar só por ela
                self._avisar(f"Gravação de {segundos:.0f} s: curta demais para treinar agora", 10)
                return
            # os especialistas das arenas onde você lutou (num panteão, várias) vêm
            # depois do treino geral
            arenas = [a for a, n in self._arenas_gravadas.most_common() if n >= self.MINIMO_GRAVADO_ARENA]
            self._fila_especialistas += [a for a in arenas if a not in self._fila_especialistas]
            if arenas:
                nomes = ", ".join(a.removeprefix("GG_") for a in arenas)
                self._notificar(f"🎯 Depois do treino geral: especialistas de {nomes}")
            self._pedir_treino()  # aprende com tudo o que já foi gravado

    LIDERANDO_MINIMO_S = 60  # de jogo da desafiante para "estar na frente" valer

    def _desafiante_na_frente(self):
        t = self.torneio
        return (t.estado["placar"]["desafiante"]["segundos"] >= self.LIDERANDO_MINIMO_S
                and t.por_minuto("desafiante") > t.por_minuto("campea"))

    def _pedir_treino(self):
        """Fim de uma gravação sua: treina já. Uma disputa em andamento é
        interrompida (fica registrada assim no Supabase): a desafiante nova aprende
        com tudo o que a atual aprendeu e mais a gravação, e a campeã não muda.
        Exceto se a desafiante estiver na frente: aí ela tem a chance de vencer, e o
        treino espera o veredito."""
        if self.torneio is not None and self.torneio.em_disputa:
            if self._desafiante_na_frente():
                self._treino_pendente = True
                self._avisar(f"🧠 A {self._nome('desafiante')} está na frente: o treino com a sua "
                             "gravação roda quando a disputa terminar", 10)
                return
            self._encerrar_torneio("interrompida")
        self.treinar()

    # A outra arquitetura (não a da campeã) treina uma vez a cada tantas. Era uma
    # sim, uma não: o conectoma perdeu as ~13 disputas depois da #46 (14/10) e
    # metade dos treinos ia para ele
    OUTRA_ARQUITETURA_A_CADA = 3

    def _arquitetura_do_treino(self):
        """Reveza as arquiteturas: depois de OUTRA_ARQUITETURA_A_CADA - 1 desafiantes
        da arquitetura da campeã, uma da outra. Assim as duas seguem competindo."""
        campea = self.modelos["campea"]
        da_campea = getattr(campea, "arquitetura", "mlp") if campea is not None else "mlp"
        if self.torneio is None:
            return da_campea
        outra = "conectoma" if da_campea == "mlp" else "mlp"
        seguidas = self.torneio.estado.get("seguidas_da_campea", 0)
        return outra if seguidas >= self.OUTRA_ARQUITETURA_A_CADA - 1 else da_campea

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

    def treinar_especialista(self, arena):
        """Treina (em outro processo) o especialista de uma arena: vira candidato."""
        if self.treino is not None:
            return
        campea = self.modelos["campea"]
        arquitetura = getattr(campea, "arquitetura", "mlp") if campea is not None else "mlp"
        processo = QtCore.QProcess(self)
        processo.setWorkingDirectory(str(PASTA))
        processo.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        processo.readyReadStandardOutput.connect(self._saida_treino)
        processo.finished.connect(self._fim_treino)
        self._log_treino = []
        self.treino, self._treino_especialista = processo, arena
        self._info_treino = f"🎯 Treinando o especialista de {arena.removeprefix('GG_')}…"
        processo.start(sys.executable, ["-u", str(PASTA / "treinar.py"), "--arquitetura", arquitetura,
                                        "--especialista", arena])

    def _saida_treino(self):
        texto = bytes(self.treino.readAllStandardOutput()).decode(errors="replace")
        self._log_treino.append(texto)
        for epoca in re.finditer(r"época\s+(\d+)/(\d+)", texto):
            self._info_treino = f"🧠 Treinando a mosca… época {epoca[1]}/{epoca[2]}"

    def _fim_treino(self, codigo, _status):
        log = "".join(self._log_treino)
        self.treino = None
        arena, self._treino_especialista = self._treino_especialista, None
        if arena is not None:
            PASTA_ESPECIALISTAS.mkdir(exist_ok=True)
            (PASTA_ESPECIALISTAS / f"{arena}.log").write_text(log)
            nome = arena.removeprefix("GG_")
            if codigo == 0 and "especialista salvo" in log:
                texto = f"🎯 Especialista novo de {nome}: joga as próximas lutas de lá e assume se for melhor"
            elif "nada novo aprendido" in log:
                texto = f"🎯 Especialista de {nome}: nada novo; tenta de novo depois de mais lutas"
            elif "Pouca luta" in log:
                texto = f"🎯 Pouca luta em {nome} para um especialista ainda"
            else:
                texto = f"⚠ O treino do especialista de {nome} falhou (veja especialistas/{arena}.log)"
            self.especialistas.treinou(arena)
            self._avisar(texto, 15)
            if self._treinar_de_novo:
                self._treinar_de_novo = False
                self.treinar()
            self._proximo_da_fila()
            return
        (PASTA / "treino.log").write_text(log)  # a tabela de resultado fica aqui
        if codigo == 0 and "modelo salvo" in log:
            self._nova_desafiante()
        elif "nada novo aprendido" in log:  # não vale uma disputa: espera mais dados
            self._info_treino = (f"🧠 Treino sem novidade: a {self._nome('campea')} continua; "
                                 "o próximo terá mais dados")
        elif "mínimo" in log:
            self._info_treino = "🧠 Pouca gravação para treinar: grave um pouco mais"
        else:
            self._info_treino = "⚠ O treino falhou (veja treino.log)"
        self._info_ate = time.monotonic() + 10
        if self._treinar_de_novo:
            self._treinar_de_novo = False
            self.treinar()
        self._proximo_da_fila()  # especialistas da sua última gravação

    def _registrar_substituida(self):
        """Uma desafiante nova chegou com a anterior ainda sem resultado (dois
        treinos seguidos): a anterior fica no Supabase como "substituída", com o
        placar que tiver."""
        anterior = self.modelos.get("desafiante")
        if anterior is None or not anterior.treino_id:
            return
        t = self.torneio
        campea = self.modelos.get("campea")
        self._envios.append(marcar_torneio(anterior.treino_id, {
            "resultado": "substituida",
            "motivo": "um treino seguinte terminou antes do veredito (já inclui os dados dela)",
            "contra_treino": campea.treino_id if campea else None,
            "por_minuto": round(t.por_minuto("desafiante"), 2),
            "por_minuto_campea": round(t.por_minuto("campea"), 2),
            "minutos": round(t.estado["placar"]["desafiante"]["segundos"] / 60, 1),
            "minutos_campea": round(t.estado["placar"]["campea"]["segundos"] / 60, 1),
            "melhoria_pct": None,
        }))
        self.modelos["desafiante"] = None

    def _nova_desafiante(self):
        if self.torneio is None:  # versão escolhida à mão: não mexe em quem joga
            self._info_treino = "🧠 Nova desafiante treinada; abra o painel sem --treino para ela disputar"
            return
        jogando = self.partida is not None
        if jogando:
            self._terminar_partida()
        self._registrar_substituida()
        promovida = self.torneio.nova_desafiante()
        if promovida:
            nova = self.modelos["campea"] = Imitacao.carregar()
            self._info_treino = f"🧠 {promovida}"
        else:
            nova = self.modelos["desafiante"] = Imitacao.carregar(ARQUIVO_DESAFIANTE)
            self._info_treino = (f"⚔ Nova {self._nome('desafiante')} treinada: ela disputa com a "
                                 f"{self._nome('campea')} quando a mosca jogar")
        self.torneio.estado["ultima_arquitetura"] = nova.arquitetura  # para revezar
        campea = self.modelos["campea"]
        if getattr(nova, "arquitetura", "mlp") == getattr(campea, "arquitetura", "mlp") and nova is not campea:
            self.torneio.estado["seguidas_da_campea"] = self.torneio.estado.get("seguidas_da_campea", 0) + 1
        else:  # a outra arquitetura treinou (ou a nova virou campeã): recomeça a conta
            self.torneio.estado["seguidas_da_campea"] = 0
        self.torneio.salvar()
        self._usar(self.torneio.quem_joga() if jogando else "campea")
        if jogando:
            self._comecar_partida()

    # --- correção ao vivo (mosca/correcao.py) ---

    @property
    def _mosca_joga(self):
        return getattr(self.jogo, "controlando", False) and not self.correcao.ativa

    def _suas_teclas(self):
        """As ações que VOCÊ está acionando agora (na ordem de ACOES). Com o
        plugin, como o jogo as lê: teclado ou controle, dá no mesmo (a mosca
        aprende "Pular", não "botão A"). Sem ele, só o teclado. As da mosca
        ficam de fora."""
        estado = self._estado_jogo
        if estado is not None and "acoes" in estado:
            suas = set(estado["acoes"])
        else:
            suas = {a for a, t in zip(ACOES, self.jogo.teclas_do_usuario()) if t}
        if self.jogo.controlando:
            suas -= self.jogo.da_mosca()
        return np.array([a in suas for a in ACOES])

    def _vigiar_correcao(self):
        """Com a mosca ligada, uma tecla do jogo que ela não apertou é sua: você
        assume. Devolve as suas teclas enquanto você joga, ou None."""
        if self.hud is None:  # jogo demo
            return None
        agora = time.monotonic()
        teclas = np.zeros(len(ACOES), bool)
        no_jogo = self.jogo.controlando and not self.jogo.aviso and self.jogo.recebe_teclas()
        if no_jogo:
            teclas = self._suas_teclas()
        voce = bool(teclas.any())
        if not self.correcao.ativa:
            self.correcao.eventos(self._eventos_quadro, agora)
        mudanca = self.correcao.passo(voce, agora) if self.jogo.controlando else None
        if mudanca == "assumiu":
            self.jogo.soltar_tudo()
            self.gravador_correcao = Gravador(sufixo="_correcao")
            self._notificar("🧑 Você assumiu: solte o teclado e a mosca volta em 2 s")
        elif mudanca is not None:
            self._fim_correcao(mudanca)
        if not self.correcao.ativa:
            return None
        if no_jogo:
            self.gravador_correcao.adicionar(
                self.cerebro.reduzida, teclas, self._recompensa_quadro, self._vida,
                self._eventos_quadro, self._estado_jogo,
            )
        return {a: float(t) for a, t in zip(ACOES, teclas)}

    def _fim_correcao(self, tipo):
        g, self.gravador_correcao = self.gravador_correcao, None
        if tipo == "sem_querer":
            if g is not None:
                g.descartar()
            return
        if g is not None:
            g.parar()
        self._correcao_s += self.correcao.segundos
        if self.partida is not None:
            self.partida["eventos"]["ajuda"] += 1
        if self.correcao.em_apuros:
            # o que ela fazia antes de você entrar estava errado: estímulo ruim
            # no último quadro dela (o desconto do treino espalha para trás)
            punicao = Correcao.PUNICAO
            if self.gravador_mosca is not None:
                self.gravador_mosca.ajustar_ultima(punicao)
            if self.partida is not None:
                self.partida["recompensa"] += punicao
            if self.torneio is not None and self.torneio.em_disputa:
                self.torneio.contar(self.papel, 0.0, punicao)  # precisar de ajuda conta no placar
            self.cerebro.recompensa(punicao)
        if self.jogo.controlando:
            self._notificar("🪰 A mosca voltou a jogar")

    def _gravar(self):
        """Um quadro de gravação: só com o jogo em foco, senão gravaria teclas
        que você digita em outro programa."""
        g = self.gravador
        minutos, segundos = divmod(int(time.monotonic() - g.inicio), 60)
        texto = f"⏺ Gravando {minutos:02d}:{segundos:02d} · {g.total:,} quadros".replace(",", ".")
        if self.jogo.aviso or not self.jogo.em_foco():
            return texto + " · pausado: clique no jogo", {a: 0.0 for a in ACOES}
        teclas = self._suas_teclas()
        g.adicionar(
            self.cerebro.reduzida, teclas, self._recompensa_quadro, self._vida,
            self._eventos_quadro, self._estado_jogo,
        )
        estado = self._estado_jogo
        if estado is not None and eh_arena(estado["cena"]):
            self._arenas_gravadas[estado["cena"]] += 1
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
        if self.gravador_correcao is not None:
            self.gravador_correcao.parar()
            self.gravador_correcao = None
        self._parar_gravacao_mosca()
        if self.explorador is not None:
            self.explorador.salvar()
        if self.juiz is not None:
            self.juiz.fechar()
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
        "presa": "ficou presa", "loop": "andando em círculos",
        "inimigo_morto": "matou inimigo!", "cena_nova": "sala nova!", "lugar_novo": "lugar novo",
        "banco_novo": "banco novo!", "cura_critica": "curou na hora certa", "perigo": "caiu em espinhos/ácido",
        "vai_e_volta": "indo e voltando pela mesma passagem", "chefe_derrotado": "🏆 venceu o chefe!",
        "dano_chefe": "feriu o chefe", "sombra_recuperada": "recuperou a sombra!",
        "inimigo_repetido": "matou inimigo de novo",
        "parede": "forçando a parede", "sem_novidade": "nada de novo há 1 min",
        "magia": "soltou magia", "magia_sem_alvo": "magia no vazio",
        "magia_com_vida_baixa": "magia em vez de curar",
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

    ESCALAR_S = 2.0  # tempo segurando para o lado da parede na tentativa
    PULOS_ESCALADA_S = (0.0, 0.7, 1.4)  # pular de novo agarrada = subir (Garra de Louva-a-deus)
    DE_NOVO_ESCALAR_S = 8.0  # presa de novo antes disto: a tentativa não deu certo

    def _seguir_em_frente(self):
        """Indo e voltando pela mesma passagem: segue na direção em que entrou
        na sala (para longe da porta) por 3 s, em vez de voltar por ela."""
        vx = self.juiz.vx_ao_entrar if self.juiz is not None else 0.0
        lado = ("Direita" if vx > 0 else "Esquerda") if abs(vx) > 0.5 else self._sorteio.choice(["Esquerda", "Direita"])
        outro = "Esquerda" if lado == "Direita" else "Direita"
        self.cerebro.pulso_zona_ate[outro] = 0.0
        self.cerebro.pulsar_zona(lado, 3.0)
        return f"reflexo: seguiu em frente ({ROTULO_TECLA[lado]} por 3 s)"

    def _escapar(self):
        """Presa forçando contra uma parede: primeiro tenta escalar (pular e
        segurar para o lado dela, pulando de novo agarrada); se continuar presa
        logo depois, meia-volta (às vezes pulando junto)."""
        agora = time.monotonic()
        lado = self._lado_presa or "Direita"
        if agora - self._escalada_em > self.DE_NOVO_ESCALAR_S:
            self._escalada_em = agora
            self.cerebro.pulsar_zona(lado, self.ESCALAR_S)
            self._pulos_escalada = [agora + t for t in self.PULOS_ESCALADA_S]
            return f"reflexo: tentou escalar ({ROTULO_TECLA[lado]} + pulos)"
        outro = "Esquerda" if lado == "Direita" else "Direita"
        self.cerebro.pulsar_zona(outro)
        if self._sorteio.random() < 0.5:
            self.cerebro.pulsar_zona("Pular")
            return f"reflexo: meia-volta ({ROTULO_TECLA[outro]}) pulando"
        return f"reflexo: meia-volta ({ROTULO_TECLA[outro]})"

    # Por enquanto ela não sai da sala das estátuas: as lutas são lá (juiz.SaidasDoSalao)
    PRENDER_NO_SALAO = True

    def _longe_dos_espinhos(self, acoes):
        """Na beira de onde ela já caiu em espinhos ou ácido, não anda nem esquiva
        para lá (juiz.MemoriaDePerigos); nem para as saídas da sala das estátuas."""
        if not (self._mosca_joga and self._juiz_ativo):
            return acoes
        apertando = {a for a, v in acoes.items() if v > 0.5}
        vetadas = self.perigos.vetar(self.juiz.estado)
        if vetadas & apertando:
            self._ultimo_evento = ("reflexo: parou na beira dos espinhos", time.monotonic())
        saida = self.saidas.vetar(self.juiz.estado) if self.PRENDER_NO_SALAO else set()
        if saida & apertando:
            self._ultimo_evento = ("reflexo: não sai da sala das estátuas", time.monotonic())
        vetadas |= saida
        return {a: (0.0 if a in vetadas else v) for a, v in acoes.items()}

    def _pular_na_escalada(self):
        """Os pulos da tentativa de escalar: curtos e separados (soltar e apertar
        de novo é o que faz subir agarrada na parede)."""
        agora = time.monotonic()
        while self._pulos_escalada and agora >= self._pulos_escalada[0]:
            self._pulos_escalada.pop(0)
            if self._mosca_joga:
                self.cerebro.pulsar_zona("Pular", 0.4)

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

    @property
    def _juiz_ativo(self):
        return self.juiz is not None and self.juiz.ativo

    @property
    def _estado_jogo(self):
        return self.juiz.estado if self._juiz_ativo else None

    @property
    def _vida(self):
        return self.juiz.vida if self._juiz_ativo else self.hud.vida

    def _seguir_curriculo(self):
        """Lutas do Salão dos Deuses que terminaram vão para o currículo (só as dela),
        e a estátua da próxima luta vai para o plugin."""
        if self.juiz is None:
            return
        estado = self._estado_jogo
        ordem = list(estado.get("estatuas") or []) if estado else []
        for estatua, sala, venceu in self.juiz.pegar_lutas():
            if self._mosca_joga:
                # o currículo é das estátuas; os especialistas, de toda luta (panteão também)
                avisos = self.curriculo.registrar(estatua, venceu, ordem, sala=sala) if estatua else []
                avisos += self.curriculo.panteoes_novos_prontos(self.juiz.panteoes)
                arena, quem = self._ultima_arena or (sala, "geral")
                if sala and arena != sala:  # a luta que terminou não é a que ela vinha jogando
                    arena, quem = sala, "geral"
                if arena:  # quem jogou: especialista, candidato ou a geral
                    avisos += self.especialistas.registrar_luta(arena, quem, venceu)
                for aviso in avisos:
                    self._notificar(aviso)
                    self._info_treino, self._info_ate = aviso, time.monotonic() + 15
            self._ultima_arena = None
        self.jogo.estatua_alvo = self.curriculo.proxima() if self._juiz_ativo else ""
        if self._fila_especialistas:
            self._proximo_da_fila()
        elif self.treino is None and self._mosca_joga:
            arena = self.especialistas.precisa_treinar()
            if arena:
                self.treinar_especialista(arena)

    MINIMO_GRAVADO_ARENA = 1800  # quadros (1 min) seus numa arena para treinar o especialista dela

    def _proximo_da_fila(self):
        """Especialistas das arenas da sua gravação, um de cada vez, sem atrapalhar
        o treino geral (que vai primeiro)."""
        if self.treino is None and self._fila_especialistas:
            self.treinar_especialista(self._fila_especialistas.pop(0))

    def _escolher_cerebro(self):
        """Numa arena com especialista, joga ele (o candidato, enquanto é avaliado);
        fora dela, a campeã ou a desafiante geral. Trocar de cérebro fecha a partida,
        para cada uma ficar com o treino que jogou."""
        if getattr(self, "especialistas", None) is None:
            return
        estado = self._estado_jogo
        cena = estado["cena"] if estado else ""
        modelo, quem = self.especialistas.modelo(cena) if eh_arena(cena) else (None, None)
        if eh_arena(cena) and self._mosca_joga:
            self._ultima_arena = (cena, quem or "geral")
        self._especialista = (cena, quem) if modelo is not None else None
        desejado = modelo if modelo is not None else self.modelos[self.papel]
        if desejado is None or self.cerebro.modelo is desejado:
            return
        if modelo is not None:
            modelo.papel = f"especialista de {cena.removeprefix('GG_')}"
        jogando = self.partida is not None
        if jogando:
            self._terminar_partida()
        self.cerebro.modelo = desejado
        self.painel.cartao_cerebro.atualizar_selecao()
        if jogando:
            self._comecar_partida()

    PLUGIN_SURDO_S = 1.0  # sem o plugin contar teclas lidas por isto: volta ao XTest

    def _teclas_pelo_plugin(self):
        """Plugin novo: as teclas da mosca vão por dentro do jogo, com ou sem foco.
        Só enquanto ele confirma que está lendo (a contagem "entrada" sobe); se ela
        parar, as teclas voltam ao XTest (que precisa do jogo em foco)."""
        estado, agora = self._estado_jogo, time.monotonic()
        lidos = estado.get("entrada") if estado else None
        if isinstance(lidos, bool) or not isinstance(lidos, int):  # plugin antigo ou fora
            self.jogo.pelo_plugin = False
            return
        if lidos != getattr(self, "_teclas_lidas", None):
            self._teclas_lidas, self._teclas_lidas_em = lidos, agora
        self.jogo.pelo_plugin = agora - self._teclas_lidas_em < self.PLUGIN_SURDO_S

    def _ler_hud(self, imagem):
        """Eventos do jogo -> dopamina no cérebro + painel de recompensa."""
        self._recompensa_quadro = 0.0
        self._eventos_quadro = []
        if self.hud is None or self.jogo.aviso:
            return
        self._ultimas_telas.append(imagem)
        # A tela é lida sempre (os detectores usam HUD visível e alma gastando);
        # com o plugin mandando, os eventos de vida, geo, golpes e salas vêm dele
        valor, eventos = self.hud.passo(imagem)
        do_jogo = self.juiz.passo() if self.juiz is not None else []
        self._teclas_pelo_plugin()
        self._seguir_curriculo()
        if self._juiz_ativo:
            eventos = do_jogo
        elif self.cerebro.reduzida is not None:
            eventos += self.explorador.passo(self.cerebro.reduzida)
            if "sala_nova" in eventos:
                self.explorador.salvar()
        if "dano" in eventos or "morte" in eventos:
            self._ultimo_dano = time.monotonic()
        if self._mosca_joga:
            apertadas = self.jogo.apertadas
        elif self.gravador is not None or self.correcao.ativa:  # você jogando: as suas teclas
            apertadas = {a for a, t in zip(ACOES, self._suas_teclas()) if t}
        else:
            apertadas = set()
        esquerda, direita = "Esquerda" in apertadas, "Direita" in apertadas
        bom = any(LeitorHUD.RECOMPENSA[e] > 0 for e in eventos)
        if self._juiz_ativo:
            # posição real do Cavaleiro: parada, presa, loop e lugar novo exatos
            detector = self.pela_posicao
            eventos += detector.passo(self.juiz.estado, esquerda, direita, bom, eventos)
            self.perigos.passo(self.juiz.estado, eventos)
            if self.PRENDER_NO_SALAO and self._mosca_joga:
                self.saidas.passo(self.juiz.estado)
        else:  # pela tela (movimento da câmera)
            detector = self.presa
            eventos += self.parada.passo(
                self.cerebro.movimento_medio, self.hud.visivel, self.hud.gastando_alma
            )
            if self.cerebro.reduzida is not None:
                eventos += self.presa.passo(self.cerebro.reduzida, esquerda, direita, self.hud.visivel)
                eventos += self.loop.passo(self.cerebro.reduzida, bom, self.hud.visivel)
        reflexo = None
        self._pular_na_escalada()
        encostada, detector.encostada = detector.encostada, False
        self._lado_presa = detector.lado
        if encostada:
            eventos.append("parede")
        if "vai_e_volta" in eventos and self._mosca_joga:
            reflexo = self._seguir_em_frente()
        elif "loop" in eventos and self._mosca_joga:
            reflexo = self._mudar_de_ideia()
        elif ("presa" in eventos or encostada) and self._mosca_joga:
            reflexo = self._escapar()  # já com 4 s encostada; a punição só vem com 6 s
        elif "parada" in eventos and self._mosca_joga:
            reflexo = self._reflexo()
        valor = sum(LeitorHUD.RECOMPENSA[e] for e in eventos)
        self._eventos_quadro = eventos
        for evento in set(eventos) - {"parada", "lugar_novo"}:  # frequentes: sem foto
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
            self._vida if self._juiz_ativo or self.hud.visivel else None,
            texto if agora - quando < 3 else None,
            len(self.juiz.cenas) if self._juiz_ativo else self.explorador.salas,
        )

    def tick(self):
        self._escolher_cerebro()
        imagem = self.jogo.quadro()
        _, acoes = self.cerebro.passo(imagem)
        self._ler_hud(imagem)  # depois do cérebro: usa o movimento que o olho viu
        self._parar_com_esc()
        acoes = self._longe_dos_espinhos(acoes)
        gravacao = None
        suas = self._vigiar_correcao()
        if suas is None:
            self.jogo.passo(acoes)
            self._contar_partida(self._eventos_quadro)
        else:  # você está corrigindo: a mosca não aperta nada e as patas repetem você
            acoes = suas
            gravacao = "🧑 Você está jogando (correção) · a mosca volta 2 s depois que você soltar"
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
