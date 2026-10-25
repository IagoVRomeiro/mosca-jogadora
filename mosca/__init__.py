"""Mosca Knight: a mosca da Drosophila jogando Hollow Knight.

Módulos: config, jogo, olho, estimulos, aprendizado, cerebro, corpo3d, interface,
orquestrador. O ponto de entrada é o jogar.py, na raiz do projeto.
"""

import os

# Tem que vir antes de importar o PyQt6 e o MuJoCo
os.environ["QT_QPA_PLATFORMTHEME"] = "generic"
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
os.environ.setdefault("MUJOCO_GL", "egl")  # renderiza a mosca fora da tela
os.environ.setdefault("QT_XCB_GL_INTEGRATION", "xcb_egl")  # Qt no mesmo EGL do MuJoCo


# O cérebro da mosca faz contas pequenas por quadro: com uma thread por núcleo
# (o padrão do OpenBLAS) elas só ficam girando e roubam CPU do jogo. O
# treinar.py, que precisa de mais, escolhe o próprio número.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")
