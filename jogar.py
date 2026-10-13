"""Mosca jogadora: painel do cérebro + a mosca jogando num PC 3D.

Uso:
    .venv-flygym/bin/python jogar.py              # jogo de demonstração
    .venv-flygym/bin/python jogar.py --janela     # captura a janela do Hollow Knight
    .venv-flygym/bin/python jogar.py --janela "Outro Jogo"

O cérebro aqui ainda é uma imitação (CerebroDemo): forma e regiões inventadas,
disparos gerados a partir da imagem do jogo e do que você pinta no painel.
Depois é só trocar pela ponte com o modelo do conectoma (Drosophila_brain_model)
mantendo o mesmo método `passo`.
"""

import mosca  # noqa: F401  (configura Qt/MuJoCo antes de importar o resto)

import argparse
import signal
import sys

from PyQt6 import QtCore, QtWidgets
import pyqtgraph as pg

from registro import baixar_treino
from mosca.aprendizado import Imitacao
from mosca.cerebro import CerebroDemo
from mosca.config import PASTA
from mosca.corpo3d import MoscaNoPC
from mosca.interface import ESTILO
from mosca.jogo import CapturaJanela, JogoDemo
from mosca.orquestrador import Orquestrador


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--janela", nargs="?", const="Hollow Knight", metavar="NOME",
        help="capturar a janela do jogo com esse nome (padrão: Hollow Knight)",
    )
    parser.add_argument(
        "--treino", type=int, metavar="N",
        help="usar a versão da mosca do treino #N (baixada do Supabase) em vez da mais recente",
    )
    args = parser.parse_args()

    if args.treino is None:
        modelo = Imitacao.carregar()
    else:
        arquivo, commit = baixar_treino(args.treino, PASTA / "modelos_baixados")
        try:
            modelo = Imitacao.carregar(arquivo)
        except (KeyError, ValueError) as e:
            sys.exit(
                f"O treino #{args.treino} não roda neste código ({e}). Rode a versão do código "
                f"com que ele foi treinado: git checkout {commit or '<commit da época>'}"
            )
        modelo.treino_id = args.treino

    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(ESTILO)
    pg.setConfigOptions(antialias=True)
    if args.janela:
        jogo = CapturaJanela(args.janela)
    else:
        jogo = JogoDemo()
    mosca = MoscaNoPC()
    app.aboutToQuit.connect(mosca.parar)
    orq = Orquestrador(jogo, CerebroDemo(modelo=modelo), mosca, manual=args.treino is not None)
    app.aboutToQuit.connect(orq.encerrar)  # nunca deixa tecla presa no jogo

    # Ctrl+C ou kill também passam pelo aboutToQuit (que solta as teclas). O timer
    # devolve o controle ao Python de vez em quando para os sinais serem tratados.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    vigia = QtCore.QTimer()
    vigia.timeout.connect(lambda: None)
    vigia.start(200)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
