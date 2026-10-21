"""Interface: paleta, cartões do cérebro e da mosca e a janela do painel."""

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from .config import ACOES_JOGO, ROTULO_TECLA
from .corpo3d import MoscaNoPC


# Paleta (igual para o Qt e para os gráficos)
COR_FUNDO = "#0b0d14"


COR_CARTAO = "#12151f"


COR_BORDA = "#232838"


COR_TEXTO = "#e7e9f2"


COR_TEXTO_FRACO = "#7d8399"


COR_DESTAQUE = "#7c5cff"


COR_REPOUSO = (150, 175, 210, 120)


COR_ESTIMULADO = (150, 110, 255, 220)


COR_DISPARO = (255, 196, 70, 235)


COR_RECOMPENSA = (74, 222, 128, 240)


COR_PUNICAO = (248, 113, 113, 240)


ESTILO = f"""
* {{ color: {COR_TEXTO}; font-size: 13px; }}
QWidget#raiz {{ background: {COR_FUNDO}; }}
QFrame#cartao {{ background: {COR_CARTAO}; border: 1px solid {COR_BORDA}; border-radius: 14px; }}
QLabel {{ background: transparent; }}
QLabel#numero {{ color: {COR_TEXTO_FRACO}; font-size: 13px; }}
QLabel#titulo {{ font-size: 16px; font-weight: 600; }}
QLabel#fraco, QLabel#secao {{ color: {COR_TEXTO_FRACO}; font-size: 12px; }}
QLabel#status {{ color: #4ade80; font-size: 12px; }}
QLabel#valor {{ font-size: 20px; font-weight: 600; }}
QFrame#metrica {{ background: #181c28; border: 1px solid {COR_BORDA}; border-radius: 10px; }}
QPushButton {{
    background: #1a1e2b; border: 1px solid {COR_BORDA}; border-radius: 8px;
    padding: 6px 12px;
}}
QPushButton:hover {{ background: #232838; }}
QPushButton:pressed {{ background: #2c3245; }}
QPushButton:checked, QPushButton#primario {{
    background: {COR_DESTAQUE}; border-color: {COR_DESTAQUE}; color: white;
}}
QPushButton#gravar:checked {{ background: #dc2626; border-color: #dc2626; }}
QPushButton#aba {{ border: none; background: transparent; color: {COR_TEXTO_FRACO}; padding: 4px 8px; }}
QPushButton#aba:checked {{ color: {COR_TEXTO}; border-bottom: 2px solid {COR_DESTAQUE}; border-radius: 0; }}
QSlider::groove:horizontal {{ height: 4px; background: {COR_BORDA}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {COR_DESTAQUE}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; margin: -5px 0; border-radius: 7px; }}
QProgressBar {{ background: {COR_BORDA}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {COR_DESTAQUE}; border-radius: 3px; }}
"""


def array_to_pixmap(arr):
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w, _ = arr.shape
    img = QtGui.QImage(arr.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()
    return QtGui.QPixmap.fromImage(img)


def rotulo(texto, nome=None):
    lbl = QtWidgets.QLabel(texto)
    if nome:
        lbl.setObjectName(nome)
    return lbl


def cabecalho(numero, titulo, subtitulo=None):
    caixa = QtWidgets.QVBoxLayout()
    caixa.setSpacing(2)
    linha = QtWidgets.QHBoxLayout()
    linha.addWidget(rotulo(numero, "numero"))
    linha.addSpacing(6)
    linha.addWidget(rotulo(titulo, "titulo"))
    linha.addStretch()
    caixa.addLayout(linha)
    sub = None
    if subtitulo is not None:
        sub = rotulo(subtitulo, "fraco")
        caixa.addWidget(sub)
    return caixa, linha, sub


class VistaCerebro(pg.ViewBox):
    """ViewBox que transforma cliques/arrastos em pinceladas."""

    pincelada = QtCore.pyqtSignal(float, float)
    fim_pincelada = QtCore.pyqtSignal()
    cursor = QtCore.pyqtSignal(object)  # (x, y) ou None

    def __init__(self):
        super().__init__(lockAspect=True, enableMenu=False)
        self.setMouseEnabled(False, False)

    def _ponto(self, ev):
        p = self.mapSceneToView(ev.scenePos())
        return p.x(), p.y()

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        ev.accept()
        self.pincelada.emit(*self._ponto(ev))
        self.cursor.emit(self._ponto(ev))
        if ev.isFinish():
            self.fim_pincelada.emit()

    def mouseClickEvent(self, ev):
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            ev.accept()
            self.pincelada.emit(*self._ponto(ev))
            self.fim_pincelada.emit()

    def hoverEvent(self, ev):
        self.cursor.emit(None if ev.isExit() else self._ponto(ev))


class CartaoCerebro(QtWidgets.QFrame):
    def __init__(self, cerebro):
        super().__init__()
        self.setObjectName("cartao")
        self.cerebro = cerebro
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)

        caixa, _, self.subtitulo = cabecalho("01", "Pintar o cérebro", "")
        layout.addLayout(caixa)

        # Nuvem de neurônios
        self.vista = VistaCerebro()
        grafico = pg.PlotWidget(viewBox=self.vista, background=COR_CARTAO)
        grafico.hideAxis("left")
        grafico.hideAxis("bottom")
        grafico.hideButtons()
        grafico.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.vista.setRange(xRange=(-1.5, 1.5), yRange=(-0.8, 0.8), padding=0.02)
        pos = cerebro.posicoes
        # Silhueta com todos os ~139 mil neurônios: a amostra que acende, sozinha,
        # ficava espalhada e não mostrava a forma do cérebro
        fundo = getattr(getattr(cerebro, "real", None), "fundo", None)
        if fundo is not None:
            densidade, (fx, fy, fw, fh) = fundo
            cor = np.array(COR_REPOUSO[:3], np.float32)
            lut = np.zeros((256, 4), np.uint8)
            nivel = np.linspace(0, 1, 256)
            lut[:, :3] = (cor * (0.35 + 0.45 * nivel[:, None])).astype(np.uint8)
            lut[:, 3] = (np.clip(nivel * 1.6, 0, 1) ** 1.2 * 150).astype(np.uint8)
            silhueta = pg.ImageItem(densidade, levels=(0, 1), lut=lut)
            silhueta.setRect(QtCore.QRectF(fx, fy, fw, fh))
            self.vista.addItem(silhueta)
        self.base = pg.ScatterPlotItem(pos=pos, size=1.8, pen=None, brush=pg.mkBrush(*COR_REPOUSO))
        self.camada_estimulo = pg.ScatterPlotItem(size=3.2, pen=None, brush=pg.mkBrush(*COR_ESTIMULADO))
        self.brilho = pg.ScatterPlotItem(size=9, pen=None, brush=pg.mkBrush(255, 196, 70, 40))
        self.camada_disparo = pg.ScatterPlotItem(size=3.5, pen=None, brush=pg.mkBrush(*COR_DISPARO))
        self.camada_pam = pg.ScatterPlotItem(size=4.5, pen=None, brush=pg.mkBrush(*COR_RECOMPENSA))
        self.camada_ppl1 = pg.ScatterPlotItem(size=4.5, pen=None, brush=pg.mkBrush(*COR_PUNICAO))
        caneta_zona = pg.mkPen(255, 255, 255, 220, width=1.2)
        self.camada_zona = pg.ScatterPlotItem(size=7, pen=caneta_zona, brush=pg.mkBrush(255, 255, 255, 60))
        self.rotulo_zona = pg.TextItem("", color=(235, 238, 250), anchor=(0.5, 0.5))
        self.rotulo_zona.setPos(0, 0.72)  # no alto: os neurônios da zona ficam espalhados
        self.rotulo_zona.hide()
        for item in (
            self.base, self.camada_estimulo, self.brilho, self.camada_disparo,
            self.camada_pam, self.camada_ppl1, self.camada_zona, self.rotulo_zona,
        ):
            self.vista.addItem(item)
        # Rótulos da dopamina. As zonas das ações não têm rótulo fixo: na conectoma
        # ficam todas no centro (neurônios descendentes) e as letras se amontoavam.
        # Passar o mouse num botão de ação mostra a zona dela (camada_zona).
        self.rotulos = {}
        for nome, texto in [("PAM", "+"), ("PPL1", "−")]:
            txt = pg.TextItem(texto, color=(200, 205, 225, 170), anchor=(0.5, 0.5))
            self.vista.addItem(txt)
            self.rotulos[nome] = txt
        self._versao_zonas = None
        self.posicionar_rotulos()
        for texto, x in (("E", -1.42), ("D", 1.42)):
            txt = pg.TextItem(texto, color=COR_TEXTO_FRACO, anchor=(0.5, 0.5))
            txt.setPos(x, -0.72)
            self.vista.addItem(txt)
        self.circulo = QtWidgets.QGraphicsEllipseItem()
        caneta = pg.mkPen(255, 255, 255, 140, width=1)
        caneta.setCosmetic(True)
        self.circulo.setPen(caneta)
        self.circulo.hide()
        self.vista.addItem(self.circulo)
        layout.addWidget(grafico, stretch=1)

        # Legenda
        legenda = QtWidgets.QHBoxLayout()
        legenda.addStretch()
        for texto, cor in (
            ("Em repouso", COR_REPOUSO), ("Estimulado", COR_ESTIMULADO), ("Disparando", COR_DISPARO),
            ("Recompensa", COR_RECOMPENSA), ("Punição", COR_PUNICAO),
        ):
            ponto = rotulo("●")
            ponto.setStyleSheet(f"color: rgb{cor[:3]}; font-size: 11px;")
            legenda.addWidget(ponto)
            legenda.addWidget(rotulo(texto, "fraco"))
            legenda.addSpacing(10)
        legenda.addStretch()
        layout.addLayout(legenda)

        # Ferramentas do pincel
        ferramentas = QtWidgets.QHBoxLayout()
        self.bt_pintar = QtWidgets.QPushButton("✎  Pintar")
        self.bt_apagar = QtWidgets.QPushButton("⌫  Apagar")
        grupo = QtWidgets.QButtonGroup(self)
        for bt in (self.bt_pintar, self.bt_apagar):
            bt.setCheckable(True)
            grupo.addButton(bt)
            ferramentas.addWidget(bt)
        self.bt_pintar.setChecked(True)
        ferramentas.addSpacing(12)
        ferramentas.addWidget(rotulo("Pincel", "fraco"))
        self.tamanho = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.tamanho.setRange(8, 80)
        self.tamanho.setValue(40)
        ferramentas.addWidget(self.tamanho, stretch=1)
        self.lbl_tamanho = rotulo("40 px", "fraco")
        self.lbl_tamanho.setMinimumWidth(40)
        self.tamanho.valueChanged.connect(lambda v: self.lbl_tamanho.setText(f"{v} px"))
        ferramentas.addWidget(self.lbl_tamanho)
        bt_limpar = QtWidgets.QPushButton("Limpar")
        bt_limpar.clicked.connect(lambda: self.limpar())
        ferramentas.addWidget(bt_limpar)
        bt_pulsar = QtWidgets.QPushButton("⚡ Pulsar de novo")
        bt_pulsar.setObjectName("primario")
        bt_pulsar.clicked.connect(lambda: cerebro.pulsar_selecao())
        ferramentas.addWidget(bt_pulsar)
        layout.addLayout(ferramentas)

        # Ações prontas: pulsam a zona de comando correspondente
        layout.addSpacing(6)
        layout.addWidget(rotulo("AÇÕES", "secao"))
        acoes = QtWidgets.QGridLayout()
        acoes.setSpacing(6)
        self._botao_acao = {}
        for i, (nome, acao) in enumerate(ACOES_JOGO.items()):
            bt = QtWidgets.QPushButton(f"{acao.rotulo}  {acao.curto}")
            bt.setToolTip(f"{nome} (tecla {acao.rotulo}): o mouse aqui mostra a zona no cérebro")
            bt.clicked.connect(lambda _, n=nome: cerebro.pulsar_zona(n))
            bt.installEventFilter(self)
            self._botao_acao[bt] = nome
            acoes.addWidget(bt, i // 6, i % 6)
        layout.addLayout(acoes)

        self.vista.pincelada.connect(self.pintar)
        self.vista.fim_pincelada.connect(self.fim_pincelada)
        self.vista.cursor.connect(self.mover_circulo)
        self.atualizar_selecao()

    def eventFilter(self, objeto, evento):
        """Mouse sobre um botão de ação: destaca os neurônios da zona dela."""
        nome = self._botao_acao.get(objeto)
        if nome is not None:
            if evento.type() == QtCore.QEvent.Type.Enter:
                self.mostrar_zona(nome)
            elif evento.type() == QtCore.QEvent.Type.Leave:
                self.mostrar_zona(None)
        return super().eventFilter(objeto, evento)

    def mostrar_zona(self, nome):
        indices = self.cerebro.zona.get(nome, []) if nome else []
        if not len(indices):
            self.camada_zona.setData(pos=np.zeros((0, 2)))
            self.rotulo_zona.hide()
            return
        self.camada_zona.setData(pos=self.cerebro.posicoes[indices])
        self.rotulo_zona.setText(f"○ zona de {nome} (tecla {ROTULO_TECLA[nome]}): {len(indices)} neurônios")
        self.rotulo_zona.show()

    def _raio(self):
        return self.tamanho.value() / 2 * self.vista.viewPixelSize()[0]

    def pintar(self, x, y):
        self.cerebro.pintar(x, y, self._raio(), apagar=self.bt_apagar.isChecked())
        self.atualizar_selecao()

    def fim_pincelada(self):
        if self.bt_pintar.isChecked():
            self.cerebro.pulsar_selecao()

    def limpar(self):
        self.cerebro.selecao[:] = False
        self.atualizar_selecao()

    def mover_circulo(self, ponto):
        if ponto is None:
            self.circulo.hide()
            return
        r = self._raio()
        self.circulo.setRect(ponto[0] - r, ponto[1] - r, 2 * r, 2 * r)
        self.circulo.show()

    def atualizar_selecao(self):
        n = int(self.cerebro.selecao.sum())
        texto = f"{n:,} neurônios selecionados".replace(",", ".")
        self.subtitulo.setText(f"{texto} · cérebro: {self.cerebro.origem}")

    def posicionar_rotulos(self):
        c = self.cerebro
        for nome, txt in self.rotulos.items():
            indices = c.dopamina[nome] if nome in c.dopamina else c.zona.get(nome, [])
            txt.setPos(*c.centro(indices))
            txt.setVisible(len(indices) > 0)
        self._versao_zonas = c.versao_zonas

    def atualizar(self):
        if self.cerebro.versao_zonas != self._versao_zonas:
            self.posicionar_rotulos()
        pos = self.cerebro.posicoes
        # Selecionados aparecem roxos; durante o pulso, tudo que está sendo estimulado
        self.camada_estimulo.setData(pos=pos[self.cerebro.selecao | self.cerebro.estimulados()])
        disparos = self.cerebro.disparos
        disparando = pos[disparos]
        self.camada_disparo.setData(pos=disparando)
        self.brilho.setData(pos=disparando)
        # Verde/vermelho só durante um estímulo de verdade (evento do jogo): fora
        # disso os PAM/PPL1 também disparam (espontâneo, atividade da rede) e
        # pareceria recompensa com o Cavaleiro parado
        for camada, nome in ((self.camada_pam, "PAM"), (self.camada_ppl1, "PPL1")):
            if self.cerebro.t < self.cerebro.dopamina_ate[nome]:
                camada.setData(pos=pos[np.intersect1d(disparos, self.cerebro.dopamina[nome])])
            else:
                camada.setData(pos=np.zeros((0, 2)))


class CartaoMetrica(QtWidgets.QFrame):
    def __init__(self, titulo, unidade, maximo):
        super().__init__()
        self.setObjectName("metrica")
        self.unidade, self.maximo = unidade, maximo
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        self.titulo = rotulo(titulo, "fraco")
        layout.addWidget(self.titulo)
        self.valor = rotulo("0", "valor")
        layout.addWidget(self.valor)
        self.barra = QtWidgets.QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        layout.addWidget(self.barra)

    def definir_texto(self, texto, fracao):
        self.valor.setText(texto)
        self.barra.setValue(int(1000 * np.clip(fracao, 0, 1)))

    def definir(self, valor):
        self.valor.setText(f"{valor:.0f} {self.unidade}")
        self.barra.setValue(int(1000 * np.clip(abs(valor) / self.maximo, 0, 1)))


class CartaoMosca(QtWidgets.QFrame):
    def __init__(self, mosca):
        super().__init__()
        self.setObjectName("cartao")
        self.mosca = mosca
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)

        caixa, linha, _ = cabecalho("02", "Veja a resposta")
        self.bt_evolucao = QtWidgets.QPushButton("📈  Evolução")
        self.bt_evolucao.setToolTip("Abre o painel com a melhora da mosca versão a versão")
        self.bt_gravar = QtWidgets.QPushButton("⏺  Gravar")
        self.bt_gravar.setCheckable(True)
        self.bt_gravar.setObjectName("gravar")
        self.bt_gravar.setToolTip(
            "Você joga e o programa grava a tela e as suas teclas,\n"
            "para depois treinar a mosca com o treinar.py\n\nAtalho: Ctrl+Alt+G (o mesmo para parar)"
        )
        self.bt_controlar = QtWidgets.QPushButton("🎮  Controlar jogo")
        self.bt_controlar.setCheckable(True)
        self.bt_controlar.setToolTip(
            "A mosca aperta as teclas no jogo (" + ", ".join(ROTULO_TECLA.values()) + ")"
            "\n\nAtalho: Ctrl+Alt+C (o mesmo para parar)"
        )
        linha.addWidget(self.bt_evolucao)
        linha.addWidget(self.bt_gravar)
        linha.addWidget(self.bt_controlar)
        layout.addLayout(caixa)

        linha2 = QtWidgets.QHBoxLayout()
        self.status = rotulo("● Olhando a tela", "status")
        linha2.addWidget(self.status)
        linha2.addStretch()
        grupo = QtWidgets.QButtonGroup(self)
        for nome in MoscaNoPC.CAMERAS:
            aba = QtWidgets.QPushButton(nome)
            aba.setObjectName("aba")
            aba.setCheckable(True)
            aba.setChecked(nome == mosca.camera)
            aba.clicked.connect(lambda _, n=nome: setattr(self.mosca, "camera", n))
            grupo.addButton(aba)
            linha2.addWidget(aba)
        layout.addLayout(linha2)

        self.view = QtWidgets.QLabel()
        self.view.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.view.setMinimumSize(320, 240)
        self.view.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Ignored
        )
        layout.addWidget(self.view, stretch=1)
        rodape = QtWidgets.QHBoxLayout()
        rodape.addWidget(rotulo("NeuroMechFly · FlyGym · cada pata cuida de até 2 teclas", "fraco"))
        rodape.addStretch()
        # Os atalhos funcionam com o jogo em foco (atalho_mosca.sh, no GNOME)
        atalhos = rotulo("⌨  Ctrl+Alt+G gravar  ·  Ctrl+Alt+C mosca joga  ·  Ctrl+Alt+M abrir tudo")
        atalhos.setStyleSheet(f"color: {COR_TEXTO}; font-size: 12px;")
        atalhos.setToolTip("O mesmo atalho liga e desliga. Funcionam com o jogo em foco.")
        rodape.addWidget(atalhos)
        layout.addLayout(rodape)

        metricas = QtWidgets.QHBoxLayout()
        self.m_impulso = CartaoMetrica("Impulso motor", "Hz", 40)
        self.m_batidas = CartaoMetrica("Batidas nas teclas", "/s", 15)
        self.m_teclas = CartaoMetrica("Teclas", "", 1)
        self.m_recompensa = CartaoMetrica("Recompensa (10 s)", "", 3)
        for m in (self.m_impulso, self.m_batidas, self.m_teclas, self.m_recompensa):
            metricas.addWidget(m)
        layout.addLayout(metricas)

    def mostrar(self, quadro):
        self.view.setPixmap(
            array_to_pixmap(quadro).scaled(
                self.view.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )

    def atualizar_recompensa(self, soma, vida, ultimo, salas=None):
        """`soma` dos últimos 10 s, vida, último evento (ou None) e quantas salas
        a mosca conhece."""
        cor = "#4ade80" if soma > 0 else "#f87171" if soma < 0 else COR_TEXTO
        self.m_recompensa.valor.setStyleSheet(f"color: {cor};")
        self.m_recompensa.definir_texto(f"{soma:+.1f}", abs(soma) / 3)
        partes = [f"♥ {vida}" if vida is not None else "HUD não visível"]
        if salas is not None:
            partes.append(f"🗺 {salas} salas")
        if ultimo:
            partes.append(ultimo)
        self.m_recompensa.titulo.setText(" · ".join(partes))

    def atualizar_metricas(self, impulso, acoes, aviso=None, gravacao=None, info=None):
        teclas = [ROTULO_TECLA[a] for a in ROTULO_TECLA if acoes.get(a, 0) > 0.5]
        self.status.setStyleSheet(
            "color: #fbbf24;" if aviso
            else "color: #f87171;" if gravacao
            else "color: #a78bfa;" if info
            else ""
        )
        if aviso:  # avisos da captura do jogo e erros da simulação 3D
            texto = "⚠ " + aviso
        elif gravacao:
            texto = gravacao
        elif info:  # treino automático
            texto = info
        elif teclas:
            texto = "● Apertando " + " ".join(teclas)
        else:
            texto = "● Olhando a tela"
        self.status.setText(texto)
        self.m_impulso.definir(impulso)
        self.m_batidas.definir(self.mosca.batidas_por_s)
        self.m_teclas.definir_texto(" ".join(teclas) or "—", len(teclas) / len(ROTULO_TECLA))


class Painel(QtWidgets.QWidget):
    """Janela principal: cérebro à esquerda, mosca à direita."""

    def __init__(self, cerebro, mosca):
        super().__init__()
        self.setObjectName("raiz")
        self.setWindowTitle("Mosca jogadora")
        self.cartao_cerebro = CartaoCerebro(cerebro)
        self.cartao_mosca = CartaoMosca(mosca)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)
        layout.addWidget(self.cartao_cerebro, stretch=1)
        layout.addWidget(self.cartao_mosca, stretch=1)
