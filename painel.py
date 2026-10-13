import os

# Evita o erro do tema GNOME no Qt (tem que vir antes de importar o PyQt6)
os.environ["QT_QPA_PLATFORMTHEME"] = "generic"
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import sys

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
import pyqtgraph.opengl as gl


def array_to_pixmap(arr):
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w, _ = arr.shape
    img = QtGui.QImage(arr.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()
    return QtGui.QPixmap.fromImage(img)


class ImagePanel(QtWidgets.QWidget):
    """Painel que mostra uma imagem (array RGB) com um título."""

    def __init__(self, title):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.title = QtWidgets.QLabel(title)
        self.title.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.view = QtWidgets.QLabel()
        self.view.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.view.setMinimumSize(320, 240)
        self.view.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Ignored
        )
        self.view.setStyleSheet("background-color: black;")
        layout.addWidget(self.title)
        layout.addWidget(self.view, stretch=1)

    def show_array(self, arr):
        pix = array_to_pixmap(arr)
        self.view.setPixmap(
            pix.scaled(
                self.view.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )


class BrainPanel(QtWidgets.QWidget):
    """Painel do cérebro: nuvem 3D de neurônios + medidores de saída."""

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("3. Cérebro da mosca")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Nuvem 3D de neurônios (posições e regiões falsas)
        self.gl_view = gl.GLViewWidget()
        self.gl_view.setMinimumHeight(300)
        self.gl_view.setCameraPosition(distance=40)
        rng = np.random.default_rng(0)
        centros = np.array([[-8, 0, 0], [0, 6, 0], [8, 0, 4], [0, -6, -4], [0, 0, 8]])
        cores = np.array(
            [
                [0.2, 0.8, 1.0, 1],
                [0.8, 0.4, 1.0, 1],
                [1.0, 0.8, 0.2, 1],
                [0.4, 1.0, 0.5, 1],
                [1.0, 0.3, 0.3, 1],
            ]
        )
        pos, col = [], []
        for c, k in zip(centros, cores):
            pos.append(rng.normal(c, 2.5, size=(160, 3)))
            col.append(np.tile(k, (160, 1)))
        self.scatter = gl.GLScatterPlotItem(
            pos=np.vstack(pos), color=np.vstack(col), size=4, pxMode=True
        )
        self.gl_view.addItem(self.scatter)
        layout.addWidget(self.gl_view, stretch=1)

        # Medidores de saída (-1 a +1)
        self.bars = {}
        for nome in ["Direção (esq/dir)", "Acelerar"]:
            linha = QtWidgets.QHBoxLayout()
            rotulo = QtWidgets.QLabel(nome)
            rotulo.setMinimumWidth(130)
            barra = QtWidgets.QProgressBar()
            barra.setRange(0, 100)
            barra.setFormat("%v")
            linha.addWidget(rotulo)
            linha.addWidget(barra, stretch=1)
            layout.addLayout(linha)
            self.bars[nome] = barra

    def set_gauge(self, nome, valor):
        """valor entre -1 e +1."""
        self.bars[nome].setValue(int((valor + 1) * 50))

    def girar(self):
        self.gl_view.orbit(1, 0)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mosca jogadora - protótipo de layout")
        self.t = 0.0

        self.painel_jogo = ImagePanel("1. Jogo")
        self.painel_mosca = ImagePanel("2. Mosca 3D")
        self.painel_cerebro = BrainPanel()

        central = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(central)
        layout.addWidget(self.painel_jogo, stretch=1)
        layout.addWidget(self.painel_mosca, stretch=1)
        layout.addWidget(self.painel_cerebro, stretch=1)
        self.setCentralWidget(central)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)  # ~30 quadros por segundo

    def fake_jogo(self):
        h, w = 240, 320
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (30, 120, 40)  # grama
        cx = w / 2 + 60 * np.sin(self.t)
        x = np.arange(w)
        pista = np.abs(x - cx) < 45
        img[:, pista] = (90, 90, 90)
        return img

    def fake_mosca(self):
        h, w = 240, 320
        img = np.zeros((h, w, 3), dtype=np.uint8)
        yy, xx = np.mgrid[0:h, 0:w]
        cx = w / 2 + 50 * np.sin(self.t)
        corpo = ((xx - cx) / 25) ** 2 + ((yy - h / 2) / 45) ** 2 < 1
        img[corpo] = (200, 150, 60)
        return img

    def tick(self):
        self.t += 0.05
        self.painel_jogo.show_array(self.fake_jogo())
        self.painel_mosca.show_array(self.fake_mosca())
        self.painel_cerebro.set_gauge("Direção (esq/dir)", np.sin(self.t))
        self.painel_cerebro.set_gauge("Acelerar", np.sin(self.t * 0.5))
        self.painel_cerebro.girar()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.resize(1500, 650)
    win.show()
    sys.exit(app.exec())