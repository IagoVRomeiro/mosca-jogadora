"""Mosca jogadora: a mosca da Drosophila jogando Hollow Knight.

Módulos: config, jogo, olho, estimulos, aprendizado, cerebro, corpo3d, interface,
orquestrador. O ponto de entrada é o jogar.py, na raiz do projeto.
"""

import os

# Tem que vir antes de importar o PyQt6 e o MuJoCo
os.environ["QT_QPA_PLATFORMTHEME"] = "generic"
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
os.environ.setdefault("MUJOCO_GL", "egl")  # renderiza a mosca fora da tela
os.environ.setdefault("QT_XCB_GL_INTEGRATION", "xcb_egl")  # Qt no mesmo EGL do MuJoCo

