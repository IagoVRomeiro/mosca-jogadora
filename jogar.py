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

import os

# Tem que vir antes de importar o PyQt6 e o MuJoCo
os.environ["QT_QPA_PLATFORMTHEME"] = "generic"
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
os.environ.setdefault("MUJOCO_GL", "egl")  # renderiza a mosca fora da tela
os.environ.setdefault("QT_XCB_GL_INTEGRATION", "xcb_egl")  # Qt no mesmo EGL do MuJoCo

import argparse
import collections
import json
import re
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from registro import baixar_treino, marcar_torneio, registrar_partida

# Todos os controles de jogo do Hollow Knight, com as teclas configuradas no jogo. Mapa, inventário e
# Esc ficam de fora: são menus, não movimentos.
#   tecla: keysym do X11 · rotulo: o que aparece no painel · curto: nome no botão
#   zona: (x, y, raio) da zona de comando no cérebro
#   pata: pata que aperta a tecla · posicao: (linha, coluna) da tecla no teclado 3D
Acao = collections.namedtuple("Acao", "tecla rotulo curto zona pata posicao")
ACOES_JOGO = {
    "Esquerda": Acao("a", "A", "Esquerda", (-0.38, 0.0, 0.12), "lf", (1, 1)),
    "Direita": Acao("d", "D", "Direita", (0.38, 0.0, 0.12), "rf", (1, -1)),
    "Cima": Acao("w", "W", "Cima", (0.0, 0.28, 0.10), "lf", (2, 1)),
    "Baixo": Acao("s", "S", "Baixo", (0.0, 0.05, 0.09), "rf", (2, -1)),
    "Pular": Acao("space", "Space", "Pulo", (-0.2, -0.32, 0.09), "lm", (0, 1)),
    "Atacar": Acao("h", "H", "Ataque", (0.2, -0.32, 0.09), "rm", (0, -1)),
    "Esquiva": Acao("j", "J", "Esquiva", (0.0, -0.52, 0.08), "lh", (-1, 1)),
    "Foco": Acao("k", "K", "Foco/Magia", (-0.2, 0.18, 0.08), "lm", (0, 2)),
    "Super Investida": Acao("l", "L", "S. Investida", (-0.32, 0.38, 0.08), "lh", (-1, 2)),
    "Ferrão dos Sonhos": Acao("n", "N", "Ferrão", (0.32, 0.38, 0.08), "rh", (-1, -1)),
    "Magia Rápida": Acao("m", "M", "Magia Ráp.", (0.2, 0.18, 0.08), "rm", (0, -2)),
}
ACOES = list(ACOES_JOGO)
ROTULO_TECLA = {nome: a.rotulo for nome, a in ACOES_JOGO.items()}
OPOSTAS = [("Esquerda", "Direita"), ("Cima", "Baixo")]  # nunca apertadas juntas
# No Hollow Knight cada golpe precisa de um novo aperto: segurar a tecla dá um
# golpe só. Enquanto a mosca quer uma destas, a tecla é tocada a cada N segundos.
TOQUE_S = {"Atacar": 0.3, "Esquiva": 0.6, "Magia Rápida": 0.6}
DURACAO_TOQUE_S = 0.07
# O Foco só cura segurado por ~1 s: uma vez apertado, fica pelo menos isto
SEGURAR_MINIMO_S = {"Foco": 1.5}
QUADRO_MS = 33  # ~30 quadros por segundo
PASSOS_FISICA_POR_QUADRO = 50  # passos de física entre um quadro renderizado e outro
DURACAO_PULSO_S = 1.0

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


# ---------------------------------------------------------------------------
# Fontes do jogo
# ---------------------------------------------------------------------------


class JogoDemo:
    """Plataforma 2D simples no lugar do Hollow Knight, para testar o fluxo."""

    def __init__(self, w=480, h=270):
        self.w, self.h = w, h
        self.chao = h - 40
        self.reiniciar()

    def reiniciar(self):
        self.x, self.y, self.vy = self.w / 2, self.chao, 0.0
        self.inimigos = [[60.0, 1.5], [self.w - 60.0, -2.0]]
        self.ataque = 0

    def passo(self, acoes):
        direcao = acoes["Direita"] - acoes["Esquerda"]
        vx = 6 * direcao + (8 * np.sign(direcao) if acoes["Esquiva"] > 0.5 else 0)
        self.x = float(np.clip(self.x + vx, 10, self.w - 10))
        if acoes["Pular"] > 0.5 and self.y >= self.chao:
            self.vy = -9
        self.vy += 0.6
        self.y = min(self.y + self.vy, self.chao)
        self.ataque = 6 if acoes["Atacar"] > 0.5 else max(self.ataque - 1, 0)
        for ini in self.inimigos:
            ini[0] += ini[1]
            if not 10 < ini[0] < self.w - 10:
                ini[1] *= -1

    def quadro(self):
        img = np.zeros((self.h, self.w, 3), dtype=np.uint8)
        img[:] = (18, 22, 40)
        img[self.chao + 12 :] = (60, 60, 70)
        yy, xx = np.mgrid[0 : self.h, 0 : self.w]
        for ix, _ in self.inimigos:
            m = ((xx - ix) / 14) ** 2 + ((yy - self.chao) / 10) ** 2 < 1
            img[m] = (230, 120, 40)
        x, y = int(self.x), int(self.y)
        img[max(y - 22, 0) : y + 12, x - 7 : x + 7] = (235, 235, 245)
        if self.ataque:
            img[max(y - 10, 0) : y - 4, x + 7 : x + 32] = (250, 250, 180)
        return img


class CapturaJanela:
    """Captura uma janela X11 pelo nome exato (ex.: o Hollow Knight no Proton).

    Lê direto da janela, então funciona mesmo com outras janelas por cima. Só não
    funciona com ela minimizada: aí o jogo não desenha nada. As teclas, ao
    contrário, só chegam com o jogo em foco (ver `_foco`).
    """

    # Teclas padrão do Hollow Knight
    TECLAS = {nome: a.tecla for nome, a in ACOES_JOGO.items()}
    APERTAR, SOLTAR = 0.5, 0.35  # histerese para a tecla não ficar piscando

    def __init__(self, nome="Hollow Knight"):
        from Xlib import X, XK, display
        from Xlib.ext import xtest
        from Xlib.protocol import event

        self._X, self._evento, self._xtest = X, event, xtest
        self.nome = nome
        self.display = display.Display()
        self._wm_state = self.display.intern_atom("WM_STATE")
        self._janela_ativa = self.display.intern_atom("_NET_ACTIVE_WINDOW")
        self._codigos = {
            acao: self.display.keysym_to_keycode(XK.string_to_keysym(tecla))
            for acao, tecla in self.TECLAS.items()
        }
        self.janela = None
        self.aviso = None
        self.controlando = False  # só manda teclas quando ligado no painel
        self.apertadas = set()  # teclas fisicamente apertadas agora
        self._ativas = set()  # ações que a mosca quer (podem estar entre dois toques)
        self._desde, self._apertou_em = {}, {}
        self.janelas_proprias = set()  # o painel: pode devolver o foco ao jogo
        self.aviso_controle = None
        self._ultimo_foco = 0.0
        self._vazio = np.zeros((360, 640, 3), dtype=np.uint8)

    def reiniciar(self):
        self.soltar_tudo()

    # O jogo (Wine/Unity) ignora teclas enquanto não está em foco, então as teclas
    # são simuladas com XTEST, como um teclado de verdade. Como o XTEST digita na
    # janela em foco, só apertamos com o foco no jogo: nunca no VS Code etc.

    def _foco(self):
        prop = self.display.screen().root.get_full_property(self._janela_ativa, self._X.AnyPropertyType)
        return prop.value[0] if prop is not None and len(prop.value) else None

    def em_foco(self):
        return self.janela is not None and self._foco() == self.janela.id

    def teclas_do_usuario(self):
        """Teclas de ação que estão apertadas agora (na ordem de ACOES)."""
        mapa = self.display.query_keymap()
        return np.array(
            [bool(mapa[c // 8] & (1 << (c % 8))) for c in (self._codigos[a] for a in ACOES)]
        )

    def focar(self):
        """Pede ao gerenciador de janelas para trazer o jogo para o foco."""
        if self.janela is None or time.monotonic() - self._ultimo_foco < 0.5:
            return
        self._ultimo_foco = time.monotonic()
        root = self.display.screen().root
        ev = self._evento.ClientMessage(
            window=self.janela, client_type=self._janela_ativa,
            data=(32, [2, self._X.CurrentTime, 0, 0, 0]),  # 2 = pedido vindo de "ferramenta"
        )
        mascara = self._X.SubstructureRedirectMask | self._X.SubstructureNotifyMask
        root.send_event(ev, event_mask=mascara)
        self.display.flush()

    def _tecla(self, acao, apertar):
        tipo = self._X.KeyPress if apertar else self._X.KeyRelease
        self._xtest.fake_input(self.display, tipo, self._codigos[acao])
        if apertar:
            self.apertadas.add(acao)
        else:
            self.apertadas.discard(acao)

    def soltar_tudo(self):
        try:
            for acao in list(self.apertadas):
                self._tecla(acao, False)  # soltar é seguro com qualquer foco
            self.display.flush()
        except Exception:
            pass
        self.apertadas.clear()
        self._ativas.clear()

    def passo(self, acoes):
        self.aviso_controle = None
        if not self.controlando or self.janela is None or self.aviso:
            self.soltar_tudo()
            return
        desejadas = dict(acoes)
        # Direções opostas juntas não fazem sentido: fica só a mais forte. A que já
        # está apertada leva vantagem, senão o boneco fica trocando de lado
        for a, b in OPOSTAS:
            forca_a = acoes[a] + (0.2 if a in self._ativas else 0.0)
            forca_b = acoes[b] + (0.2 if b in self._ativas else 0.0)
            desejadas[a if forca_a < forca_b else b] = 0.0
        try:
            foco = self._foco()
            if foco != self.janela.id:
                self.soltar_tudo()  # nunca deixa tecla segurada fora do jogo
                if any(desejadas[a] > self.APERTAR for a in self.TECLAS):
                    if foco in self.janelas_proprias:
                        self.focar()  # você clicou no painel: devolve o foco ao jogo
                    else:
                        self.aviso_controle = "Clique na janela do jogo para a mosca jogar"
                return
            agora = time.monotonic()
            for acao in self.TECLAS:
                apertar = self._decidir(acao, desejadas[acao], agora)
                if apertar != (acao in self.apertadas):
                    self._tecla(acao, apertar)
                    if apertar:
                        self._apertou_em[acao] = agora
            self.display.flush()
        except Exception:
            self.soltar_tudo()
            self.janela = None

    def _decidir(self, acao, vontade, agora):
        """A tecla deve estar apertada agora? Histerese na vontade, toques
        repetidos (TOQUE_S) e tempo mínimo segurada (SEGURAR_MINIMO_S)."""
        limiar = self.SOLTAR if acao in self._ativas else self.APERTAR
        ativa = vontade > limiar
        if ativa and acao not in self._ativas:
            self._desde[acao] = agora
        (self._ativas.add if ativa else self._ativas.discard)(acao)
        if acao in TOQUE_S:
            return ativa and (agora - self._desde[acao]) % TOQUE_S[acao] < DURACAO_TOQUE_S
        if acao in SEGURAR_MINIMO_S and not ativa and acao in self.apertadas:
            return agora - self._apertou_em[acao] < SEGURAR_MINIMO_S[acao]
        return ativa

    def _procurar(self, w):
        try:
            nome = w.get_wm_name()
        except Exception:
            nome = None
        # Nome exato: "contém" pegaria, por exemplo, uma aba "Hollow Knight - Wiki"
        # do navegador, e as teclas iriam parar lá
        if nome == self.nome:
            return w
        for filho in w.query_tree().children:
            achada = self._procurar(filho)
            if achada:
                return achada
        return None

    def _minimizada(self):
        prop = self.janela.get_full_property(self._wm_state, self._X.AnyPropertyType)
        return prop is not None and prop.value[0] == 3  # IconicState

    def quadro(self):
        try:
            if self.janela is None:
                self.janela = self._procurar(self.display.screen().root)
                if self.janela is None:
                    self.aviso = f"Janela \"{self.nome}\" não encontrada"
                    return self._vazio
            if self._minimizada():
                self.aviso = f"{self.nome} está minimizado"
                return self._vazio
            g = self.janela.get_geometry()
            raw = self.janela.get_image(0, 0, g.width, g.height, self._X.ZPixmap, 0xFFFFFFFF)
        except Exception:  # janela fechou ou mudou: procura de novo no próximo quadro
            self.janela = None
            self.aviso = f"Janela \"{self.nome}\" não encontrada"
            return self._vazio
        self.aviso = None
        bgra = np.frombuffer(raw.data, np.uint8).reshape(g.height, g.width, 4)
        # O Wine desenha barra de título e borda; o filho marca onde começa o jogo
        filhos = self.janela.query_tree().children
        bx, by = (filhos[0].get_geometry().x, filhos[0].get_geometry().y) if filhos else (0, 0)
        bgra = bgra[by : g.height - bx, bx : g.width - bx]
        return bgra[::2, ::2, 2::-1]  # BGRA -> RGB, metade da resolução


# ---------------------------------------------------------------------------
# Olho da mosca, estímulos do jogo, gravação e imitação
# ---------------------------------------------------------------------------

PASTA = Path(__file__).resolve().parent
PASTA_GRAVACOES = PASTA / "gravacoes"  # você jogando
PASTA_GRAVACOES_MOSCA = PASTA / "gravacoes_mosca"  # a mosca jogando sozinha
ARQUIVO_MODELO = PASTA / "modelo_mosca.npz"  # a campeã: a versão que joga
ARQUIVO_DESAFIANTE = PASTA / "modelo_desafiante.npz"  # treinada, ainda disputando
ARQUIVO_TORNEIO = PASTA / "torneio.json"  # placar da disputa (sobrevive a reabrir)
OLHO = (90, 160)  # resolução da tela guardada na gravação e usada pelo olho
GRADE_OLHO = (18, 32)  # o olho junta a tela em blocos de 5 x 5 pixels


def reduzir(imagem, tamanho=OLHO):
    """Redimensiona (vizinho mais próximo) para `tamanho` = (altura, largura)."""
    h, w = imagem.shape[:2]
    linhas = np.linspace(0, h - 1, tamanho[0]).astype(int)
    colunas = np.linspace(0, w - 1, tamanho[1]).astype(int)
    return imagem[linhas][:, colunas]


def cinza(tela):
    """Tela RGB -> tons de cinza uint8 (o olho da mosca não usa cor)."""
    if tela.ndim == 2:
        return tela
    return (tela.astype(np.uint16).sum(axis=2) // 3).astype(np.uint8)


def ver(reduzida, anterior=None):
    """O que o olho da mosca entrega ao cérebro: brilho + movimento por bloco.

    `reduzida` é uma tela já em OLHO, colorida ou em cinza. Devolve um vetor
    float32 de 2 x 18 x 32.
    """
    reduzida, anterior = cinza(reduzida), None if anterior is None else cinza(anterior)
    cinza_ = reduzida.astype(np.float32) / 255
    gl, gc = GRADE_OLHO
    blocos = cinza_.reshape(gl, cinza_.shape[0] // gl, gc, cinza_.shape[1] // gc)
    brilho = blocos.mean(axis=(1, 3))
    if anterior is None:
        movimento = np.zeros_like(brilho)
    else:
        ant = anterior.astype(np.float32) / 255
        mov = np.abs(cinza_ - ant).reshape(blocos.shape).mean(axis=(1, 3))
        movimento = np.clip(mov * 6, 0, 1)
    return np.concatenate([brilho.ravel(), movimento.ravel()]).astype(np.float32)


class LeitorHUD:
    """Lê o HUD do Hollow Knight pela imagem e transforma em estímulos.

    Coordenadas em fração da altura da tela (o HUD escala com ela; 16:9):
    - máscaras de vida: cheia é branca, vazia é azul-escura -> dano/cura
    - vaso de alma: enche quando o Cavaleiro acerta um inimigo -> "acertou"
    - número de geo: mudou -> pegou geo
    Uma leitura só vale depois de repetir por alguns quadros (o HUD pisca e
    some em transições e menus).
    """

    MASCARA_X0, MASCARA_PASSO, MASCARA_Y = 0.263, 0.0457, 0.0876
    MAX_MASCARAS = 11
    ALMA = (0.187, 0.118, 0.040)  # centro x, centro y, raio
    GEO = (0.286, 0.495, 0.137, 0.181)  # x0, x1, y0, y1
    ESTAVEL = 3  # quadros iguais para aceitar uma leitura
    RECOMPENSA = {"dano": -1.0, "cura": 0.3, "acerto": 0.3, "geo": 0.5, "parada": -0.2}

    def __init__(self):
        self.reiniciar()

    def reiniciar(self):
        self.vida = None  # máscaras cheias aceitas
        self.alma = None
        self.gastando_alma = False  # vaso esvaziando: curando com o Foco ou usando magia
        self._geo = None
        self._candidato, self._repeticoes = None, 0
        self._geo_cand, self._geo_rep = None, 0
        self.visivel = False

    def _caixa(self, cinza, cx, cy, r):
        h = cinza.shape[0]
        x, y, r = int(cx * h), int(cy * h), max(1, int(r * h))
        return cinza[max(0, y - r) : y + r + 1, max(0, x - r) : x + r + 1]

    def ler(self, quadro):
        """Leitura crua de um quadro: (hud visível?, máscaras cheias, alma 0..1, assinatura do geo)."""
        cinza = quadro.astype(np.float32).mean(axis=2)
        h = cinza.shape[0]
        cheias = 0
        for i in range(self.MAX_MASCARAS):
            caixa = self._caixa(cinza, self.MASCARA_X0 + i * self.MASCARA_PASSO, self.MASCARA_Y, 0.008)
            if caixa.size and caixa.max() > 150:
                cheias += 1
            else:
                break
        cx, cy, r = self.ALMA
        vaso = self._caixa(cinza, cx, cy, r)
        # O contorno do vaso é sempre claro; sem ele, o HUD não está na tela
        borda = self._caixa(cinza, cx, cy - r * 0.9, 0.006)
        visivel = bool(borda.size and borda.max() > 120 and cheias > 0)
        alma = float((vaso > 150).mean()) if vaso.size else 0.0
        x0, x1, y0, y1 = self.GEO
        geo = cinza[int(y0 * h) : int(y1 * h), int(x0 * h) : int(x1 * h)] > 150
        return visivel, cheias, alma, geo

    def passo(self, quadro):
        """Devolve (recompensa deste quadro, lista de eventos)."""
        visivel, cheias, alma, geo = self.ler(quadro)
        self.visivel = visivel
        eventos = []
        if not visivel:
            self._repeticoes = self._geo_rep = 0
            return 0.0, eventos

        # Vida: só aceita um valor novo se ele se repetir (evita piscadas)
        if cheias == self._candidato:
            self._repeticoes += 1
        else:
            self._candidato, self._repeticoes = cheias, 1
        if self._repeticoes >= self.ESTAVEL and cheias != self.vida:
            if self.vida is not None:
                if cheias < self.vida:
                    eventos += ["dano"] * (self.vida - cheias)
                else:
                    eventos += ["cura"] * (cheias - self.vida)
            self.vida = cheias

        # Alma: subir de repente = acertou um inimigo (descer = gastou, neutro)
        if self.alma is not None and alma - self.alma > 0.04:
            eventos.append("acerto")
        self.gastando_alma = self.alma is not None and alma - self.alma < -0.02
        self.alma = alma if self.alma is None else 0.5 * self.alma + 0.5 * alma

        # Geo: o desenho do número mudou e ficou assim
        if self._geo_cand is not None and geo.shape == self._geo_cand.shape and (
            np.count_nonzero(geo != self._geo_cand) <= 3
        ):
            self._geo_rep += 1
        else:
            self._geo_cand, self._geo_rep = geo, 1
        if self._geo_rep == self.ESTAVEL:
            if self._geo is not None and self._geo.shape == geo.shape and (
                np.count_nonzero(geo != self._geo) > 8
            ) and "dano" not in eventos:
                eventos.append("geo")
            self._geo = geo

        return sum(self.RECOMPENSA[e] for e in eventos), eventos


# --- Olho versão 2: periferia + fóvea + memória curta -------------------------
#
# A periferia (ver) junta a tela toda em blocos grandes: um inimigo pequeno vira
# borrão. A fóvea olha com 3x mais detalhe a região onde o Cavaleiro costuma
# ficar (a câmera do jogo o segue: meio da tela, um pouco abaixo do centro). O
# brilho de ATRASO_OLHO quadros atrás entra junto: comparando com o atual, a rede
# percebe direção e velocidade das coisas.

FOVEA = (slice(30, 84), slice(32, 128))  # região do Cavaleiro em OLHO (90 x 160)
GRADE_FOVEA = (18, 24)  # blocos de 3 x 4 pixels
ATRASO_OLHO = 5  # quadros (~170 ms)
VERSAO_OLHO = 2  # a que o treinar.py usa agora; modelos antigos guardam a sua
_N_PERIFERIA = 2 * GRADE_OLHO[0] * GRADE_OLHO[1]
_N_FOVEA = GRADE_FOVEA[0] * GRADE_FOVEA[1]
# Posições do brilho (periferia e fóvea) dentro de um retrato
BRILHO_RETRATO = np.r_[0 : _N_PERIFERIA // 2, _N_PERIFERIA : _N_PERIFERIA + _N_FOVEA]


def retrato(reduzida, anterior=None):
    """Tudo o que o olho extrai de um quadro: periferia (`ver`) + fóvea (brilho e
    movimento). As entradas de qualquer versão do olho saem daqui."""
    periferia = ver(reduzida, anterior)
    atual = cinza(reduzida)[FOVEA].astype(np.float32) / 255
    gl, gc = GRADE_FOVEA
    forma = (gl, atual.shape[0] // gl, gc, atual.shape[1] // gc)
    brilho = atual.reshape(forma).mean(axis=(1, 3))
    if anterior is None:
        movimento = np.zeros_like(brilho)
    else:
        ant = cinza(anterior)[FOVEA].astype(np.float32) / 255
        movimento = np.clip(np.abs(atual - ant).reshape(forma).mean(axis=(1, 3)) * 6, 0, 1)
    return np.concatenate([periferia, brilho.ravel(), movimento.ravel()]).astype(np.float32)


def entrada(versao, atual, passado):
    """Entrada da rede a partir de retratos (aceita um quadro ou um lote).

    versão 1: só a periferia do quadro atual (olho dos treinos #1 a #4).
    versão 2: retrato atual + brilho de ATRASO_OLHO quadros atrás.
    """
    if versao == 1:
        return atual[..., :_N_PERIFERIA]
    return np.concatenate([atual, passado[..., BRILHO_RETRATO]], axis=-1)


def tamanho_entrada(versao):
    vazio = np.zeros(_N_PERIFERIA + 2 * _N_FOVEA, dtype=np.float32)
    return entrada(versao, vazio, vazio).shape[-1]


class DetectorParada:
    """Pune ficar parado: o jogo segue o Cavaleiro com a câmera, então andando a
    tela inteira se mexe e parado quase nada muda.

    Parado = movimento médio do último segundo abaixo de LIMITE por ESPERA_S
    seguidos; aí sai um evento "parada" e outro a cada REPETE_S. Medido nas suas
    gravações: andando a mediana é ~0,17, sem tecla ~0,03. Não conta curando
    (alma esvaziando) nem com o HUD fora da tela (menus, transições).
    Limitação: em salas de câmera fixa, andar mexe pouco a tela e pode contar.
    """

    LIMITE = 0.05
    ESPERA_S, REPETE_S = 3.0, 2.0

    def __init__(self, dt=QUADRO_MS / 1000):
        self.espera, self.repete = int(self.ESPERA_S / dt), int(self.REPETE_S / dt)
        self.janela = int(1.0 / dt)
        self.reiniciar()

    def reiniciar(self):
        self.media, self.contador = 1.0, 0

    def passo(self, movimento, hud_visivel, curando):
        """`movimento`: média do movimento no olho da mosca. Devolve eventos."""
        if not hud_visivel:
            self.reiniciar()
            return []
        self.media += (movimento - self.media) / self.janela
        if self.media >= self.LIMITE or curando:
            self.contador = 0
            return []
        self.contador += 1
        passou = self.contador - self.espera
        return ["parada"] if passou >= 0 and passou % self.repete == 0 else []


class Imitacao:
    """Rede pequena olho -> interneurônios -> zonas de comando.

    Treinada pelo `treinar.py` com as suas partidas gravadas: aprende, para cada
    tela, qual tecla você estaria apertando.
    """

    def __init__(self, pesos):
        self.w1, self.b1 = pesos["w1"], pesos["b1"]
        self.w2, self.b2 = pesos["w2"], pesos["b2"]
        self.media, self.desvio = pesos["media"], pesos["desvio"]
        self.acoes = [str(a) for a in pesos["acoes"]]
        self.n_quadros = int(pesos["n_quadros"])
        self.metodo = str(pesos["metodo"]) if "metodo" in pesos else "imitação"
        # Modelos de antes do olho v2 não guardam a versão: são do olho 1
        self.versao_olho = int(pesos["versao_olho"]) if "versao_olho" in pesos else 1
        if self.w1.shape[0] != tamanho_entrada(self.versao_olho):
            raise ValueError(f"o modelo não bate com o olho versão {self.versao_olho}")
        self.treino_id = None  # número do treino no Supabase, se foi registrado
        self.papel = None  # "campeã" ou "desafiante", quando está num torneio

    @classmethod
    def carregar(cls, arquivo=ARQUIVO_MODELO):
        if not Path(arquivo).exists():
            return None
        with np.load(arquivo) as pesos:
            modelo = cls({k: pesos[k] for k in pesos.files})
        info = Path(arquivo).with_suffix(".json")  # escrito pelo treinar.py
        if info.exists():
            modelo.treino_id = json.loads(info.read_text()).get("treino_id")
        return modelo

    def interneuronios(self, x):
        return np.maximum(0, ((x - self.media) / self.desvio) @ self.w1 + self.b1)

    def prever(self, x):
        """Probabilidade de cada tecla estar apertada, na ordem de self.acoes."""
        z = self.interneuronios(x) @ self.w2 + self.b2
        return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


class Gravador:
    """Guarda (tela reduzida, teclas apertadas) enquanto alguém joga: você
    (gravacoes/) ou a mosca sozinha (gravacoes_mosca/).

    Salva em <pasta>/<data>/parte_NNN.npz a cada QUADROS_POR_PARTE quadros,
    numa thread, para não travar o painel. As telas vão em tons de cinza:
    o olho não usa cor e o arquivo fica 3x menor (~8 KB por quadro).
    """

    QUADROS_POR_PARTE = 900  # ~30 s

    def __init__(self, base=PASTA_GRAVACOES):
        nome = time.strftime("%Y-%m-%d_%H%M%S")
        self.pasta = base / nome
        n = 2
        while self.pasta.exists():  # duas gravações no mesmo segundo
            self.pasta, n = base / f"{nome}_{n}", n + 1
        self.pasta.mkdir(parents=True)
        self.inicio = time.monotonic()
        self.total = 0
        self._parte = 0
        self._telas, self._teclas = [], []
        self._recompensas, self._vidas = [], []
        self._salvando = []

    def adicionar(self, reduzida, teclas, recompensa=0.0, vida=None):
        """`recompensa` e `vida` vêm do HUD; ficam guardadas para o aprendizado
        por reforço no futuro (o treino de imitação não usa)."""
        self._telas.append(cinza(reduzida))
        self._teclas.append(teclas)
        self._recompensas.append(recompensa)
        self._vidas.append(-1 if vida is None else vida)
        self.total += 1
        if len(self._telas) >= self.QUADROS_POR_PARTE:
            self._salvar()

    def _salvar(self):
        if not self._telas:
            return
        arquivo = self.pasta / f"parte_{self._parte:03d}.npz"
        telas, teclas = np.stack(self._telas), np.stack(self._teclas)
        recompensas = np.array(self._recompensas, dtype=np.float32)
        vidas = np.array(self._vidas, dtype=np.int8)
        self._telas, self._teclas = [], []
        self._recompensas, self._vidas = [], []
        self._parte += 1
        t = threading.Thread(
            target=np.savez_compressed,
            args=(arquivo,),
            kwargs=dict(
                telas=telas, teclas=teclas, recompensas=recompensas, vidas=vidas,
                acoes=np.array(ACOES),
            ),
        )
        t.start()
        self._salvando.append(t)

    def parar(self):
        self._salvar()
        for t in self._salvando:
            t.join()
        if self.total == 0:
            self.pasta.rmdir()


class Torneio:
    """Campeã x desafiante: a mosca só troca de cérebro quando o novo prova que
    joga melhor.

    Todo treino gera uma desafiante (modelo_desafiante.npz); a campeã
    (modelo_mosca.npz) segue sendo a versão que joga. Com o "Controlar jogo"
    ligado, as duas se alternam em rodadas de RODADA_S. Com MINIMO_S de jogo de
    cada uma, compara a recompensa por minuto: a desafiante vira campeã se fizer
    MARGEM a mais; é descartada se fizer MARGEM a menos, ou se chegar a MAXIMO_S
    sem diferença clara. Descartada, continua guardada no Supabase.
    """

    RODADA_S = 60
    MINIMO_S = 240
    MAXIMO_S = 600
    MARGEM = 0.5  # de recompensa por minuto
    PAPEIS = ("campea", "desafiante")

    def __init__(self, arquivo=ARQUIVO_TORNEIO, campea=ARQUIVO_MODELO, desafiante=ARQUIVO_DESAFIANTE):
        self.arquivo, self.campea, self.desafiante = Path(arquivo), Path(campea), Path(desafiante)
        self.estado = {"placar": self._placar_zerado(), "vez": "desafiante", "na_rodada": 0.0,
                       "mosca_desde_treino": 0.0}
        if self.arquivo.exists():
            self.estado.update(json.loads(self.arquivo.read_text()))

    def _placar_zerado(self):
        return {papel: {"segundos": 0.0, "recompensa": 0.0} for papel in self.PAPEIS}

    def salvar(self):
        self.arquivo.write_text(json.dumps(self.estado))

    @property
    def em_disputa(self):
        return self.desafiante.exists() and self.campea.exists()

    def nova_desafiante(self):
        """Uma desafiante acabou de ser treinada. Sem campeã ainda, ela já assume."""
        self.estado.update(placar=self._placar_zerado(), vez="desafiante", na_rodada=0.0)
        self.salvar()
        if not self.campea.exists():
            self._promover()
            return "primeira versão treinada: já é a campeã"
        return None

    def quem_joga(self):
        return self.estado["vez"] if self.em_disputa else "campea"

    def contar(self, papel, segundos, recompensa):
        """Um quadro de jogo da mosca. Devolve True quando é hora de trocar de versão."""
        self.estado["mosca_desde_treino"] += segundos
        if not self.em_disputa:
            return False
        placar = self.estado["placar"][papel]
        placar["segundos"] += segundos
        placar["recompensa"] += recompensa
        self.estado["na_rodada"] += segundos
        if self.estado["na_rodada"] >= self.RODADA_S:
            self.estado["na_rodada"] = 0.0
            self.estado["vez"] = "campea" if papel == "desafiante" else "desafiante"
            self.salvar()
            return True
        return False

    def por_minuto(self, papel):
        p = self.estado["placar"][papel]
        return p["recompensa"] / p["segundos"] * 60 if p["segundos"] else 0.0

    def veredito(self):
        """None (ainda disputando), "venceu" ou "perdeu" (para a desafiante)."""
        if not self.em_disputa:
            return None
        tempos = [self.estado["placar"][p]["segundos"] for p in self.PAPEIS]
        if min(tempos) < self.MINIMO_S:
            return None
        diferenca = self.por_minuto("desafiante") - self.por_minuto("campea")
        if diferenca > self.MARGEM:
            return "venceu"
        if diferenca < -self.MARGEM or min(tempos) >= self.MAXIMO_S:
            return "perdeu"
        return None

    def encerrar(self, resultado):
        """Aplica o veredito: promove ou descarta a desafiante."""
        if resultado == "venceu":
            self._promover()
        else:
            for arquivo in (self.desafiante, self.desafiante.with_suffix(".json")):
                arquivo.unlink(missing_ok=True)
        self.estado.update(placar=self._placar_zerado(), vez="desafiante", na_rodada=0.0)
        self.salvar()

    def _promover(self):
        info = self.desafiante.with_suffix(".json")
        if info.exists():
            os.replace(info, self.campea.with_suffix(".json"))
        os.replace(self.desafiante, self.campea)

    def ciclo_cumprido(self, segundos):
        return self.estado["mosca_desde_treino"] >= segundos

    def zerar_ciclo(self):
        self.estado["mosca_desde_treino"] = 0.0
        self.salvar()


# ---------------------------------------------------------------------------
# Cérebro (zonas inventadas + imitação aprendida)
# ---------------------------------------------------------------------------


def _dentro_elipse(x, y, cx, cy, a, b, ang=0.0):
    c, s = np.cos(ang), np.sin(ang)
    dx, dy = x - cx, y - cy
    u, v = c * dx + s * dy, -s * dx + c * dy
    return (u / a) ** 2 + (v / b) ** 2 < 1


def forma_cerebro(n, rng):
    """Pontos 2D com a silhueta de um cérebro de mosca visto de frente."""
    pontos = []
    while sum(len(p) for p in pontos) < n:
        x = rng.uniform(-1.45, 1.45, 4 * n)
        y = rng.uniform(-0.8, 0.8, 4 * n)
        dentro = (
            _dentro_elipse(x, y, 0, 0.02, 0.6, 0.45)  # cérebro central
            | _dentro_elipse(np.abs(x), y, 0.32, 0.38, 0.24, 0.17)  # corpos de cogumelo
            | _dentro_elipse(x, y, 0, -0.38, 0.3, 0.2)  # gânglio subesofágico
            | _dentro_elipse(np.abs(x), y, 1.02, 0.0, 0.36, 0.56, -0.25)  # medula
            | _dentro_elipse(np.abs(x), y, 0.7, -0.05, 0.22, 0.42)  # lóbulo
        )
        dentro &= ~_dentro_elipse(x, y, 0, -0.15, 0.07, 0.06)  # esôfago
        pontos.append(np.column_stack([x[dentro], y[dentro]]))
    pos = np.vstack(pontos)[:n]
    return pos + rng.normal(0, 0.008, pos.shape)


class CerebroDemo:
    """Rede de taxa de disparo com regiões inventadas.

    - Lobos ópticos: cada neurônio "olha" para um pedaço da imagem do jogo
      (retinotopia) e dispara com o movimento ali.
    - Zonas de comando (uma por ação): recebem o que você pintar/pulsar no
      painel e, de olho no jogo, ou regras fixas (sem treino) ou a rede de
      imitação treinada com as suas partidas (`modelo`). A taxa média de cada
      zona vira a ação.
    """

    ZONAS = {nome: a.zona for nome, a in ACOES_JOGO.items()}
    # Neurônios de dopamina do corpo de cogumelo: na mosca real, os PAM sinalizam
    # recompensa e os PPL1, punição. Aqui piscam com os eventos do jogo (HUD).
    DOPAMINA = {"PAM": (-0.13, 0.43, 0.07), "PPL1": (0.13, 0.43, 0.07)}
    DURACAO_DOPAMINA_S = 0.6
    GRADE = (GRADE_OLHO[0], GRADE_OLHO[1] // 2)  # resolução do olho em cada metade
    ESPONTANEA = 0.3  # Hz

    def __init__(self, n=14000, dt=QUADRO_MS / 1000, modelo=None):
        self.n, self.dt = n, dt
        self.modelo = modelo
        self.rng = np.random.default_rng(0)
        self.posicoes = forma_cerebro(n, self.rng)
        x, y = self.posicoes.T

        self.zona = {
            nome: np.flatnonzero((x - cx) ** 2 + (y - cy) ** 2 < r**2)
            for nome, (cx, cy, r) in self.ZONAS.items()
        }
        self.dopamina = {
            nome: np.flatnonzero((x - cx) ** 2 + (y - cy) ** 2 < r**2)
            for nome, (cx, cy, r) in self.DOPAMINA.items()
        }
        self.optico_esq = np.flatnonzero(x < -0.55)
        self.optico_dir = np.flatnonzero(x > 0.55)

        # Retinotopia: posição no lobo -> célula da grade na metade da imagem
        linhas, colunas = self.GRADE
        lin = np.clip(((0.6 - y) / 1.2 * linhas).astype(int), 0, linhas - 1)
        col_ext = np.clip(((np.abs(x) - 0.5) / 0.95 * colunas).astype(int), 0, colunas - 1)
        col = np.where(x < 0, colunas - 1 - col_ext, colunas + col_ext)  # borda = periferia
        self.celula = lin * (2 * colunas) + col

        self.reiniciar()

    def reiniciar(self):
        self.taxas = np.full(self.n, self.ESPONTANEA)  # Hz
        self.selecao = np.zeros(self.n, dtype=bool)
        self.pulso_selecao_ate = 0.0
        self.pulso_zona_ate = {nome: 0.0 for nome in self.ZONAS}
        self.dopamina_ate = {nome: 0.0 for nome in self.DOPAMINA}
        self.disparos = np.array([], dtype=int)
        self.reduzida = None  # última tela vista, em OLHO (o gravador reaproveita)
        self.retratos = collections.deque(maxlen=ATRASO_OLHO + 1)  # memória curta do olho
        self.movimento_medio = 0.0
        self.t = 0.0

    @property
    def origem(self):
        if self.modelo is None:
            return "regras fixas (sem treino)"
        n = f"{self.modelo.n_quadros:,}".replace(",", ".")
        treino = f"treino #{self.modelo.treino_id} · " if self.modelo.treino_id else ""
        papel = f"{self.modelo.papel} · " if self.modelo.papel else ""
        return f"{papel}{treino}{self.modelo.metodo}, {n} quadros"

    # --- estímulos vindos do painel ---

    def pintar(self, x, y, raio, apagar=False):
        perto = (self.posicoes[:, 0] - x) ** 2 + (self.posicoes[:, 1] - y) ** 2 < raio**2
        self.selecao[perto] = not apagar

    def pulsar_selecao(self):
        self.pulso_selecao_ate = self.t + DURACAO_PULSO_S

    def pulsar_zona(self, nome):
        self.pulso_zona_ate[nome] = self.t + DURACAO_PULSO_S

    def recompensa(self, valor):
        """Evento do jogo: positivo acende os PAM, negativo os PPL1.

        Por enquanto é só o sinal: nada aprende com ele ainda."""
        if valor:
            self.dopamina_ate["PAM" if valor > 0 else "PPL1"] = self.t + self.DURACAO_DOPAMINA_S

    def estimulados(self):
        mask = self.selecao.copy() if self.t < self.pulso_selecao_ate else np.zeros(self.n, bool)
        for nome, ate in self.pulso_zona_ate.items():
            if self.t < ate:
                mask[self.zona[nome]] = True
        return mask

    # --- simulação ---

    def passo(self, imagem):
        """Recebe a imagem do jogo; devolve (índices que dispararam, ações 0..1)."""
        self.t += self.dt
        reduzida = reduzir(imagem)
        if self.reduzida is not None and self.reduzida.shape != reduzida.shape:
            self.reduzida = None
        atual = retrato(reduzida, self.reduzida)
        self.reduzida = reduzida
        self.retratos.append(atual)
        movimento = atual[_N_PERIFERIA // 2 : _N_PERIFERIA]  # movimento da periferia
        self.movimento_medio = float(movimento.mean())  # o detector de parada usa

        alvo = np.full(self.n, self.ESPONTANEA)
        optico = np.concatenate([self.optico_esq, self.optico_dir])
        alvo[optico] += 150 * movimento[self.celula[optico]]
        if self.modelo is not None:
            # A rede treinada decide quanto cada zona de comando recebe
            x = entrada(self.modelo.versao_olho, atual, self.retratos[0])
            for nome, p in zip(self.modelo.acoes, self.modelo.prever(x)):
                if nome in self.zona:
                    alvo[self.zona[nome]] += 40 * p
        else:
            esq = self.taxas[self.optico_esq].mean()
            dir_ = self.taxas[self.optico_dir].mean()
            alvo[self.zona["Esquerda"]] += 4 * esq
            alvo[self.zona["Direita"]] += 4 * dir_
            alvo[self.zona["Atacar"]] += 3 * max(esq, dir_)
        alvo[self.estimulados()] += 90
        for nome, ate in self.dopamina_ate.items():
            if self.t < ate:
                alvo[self.dopamina[nome]] += 120
        self.taxas += 0.25 * (alvo - self.taxas)

        self.disparos = np.flatnonzero(self.rng.random(self.n) < self.taxas * self.dt)
        acoes = {
            nome: float(np.clip((self.taxas[idx].mean() - self.ESPONTANEA) / 40, 0, 1))
            for nome, idx in self.zona.items()
        }
        return self.disparos, acoes


# ---------------------------------------------------------------------------
# Mosca 3D no PC (FlyGym, ilustrativa)
# ---------------------------------------------------------------------------


class MoscaNoPC:
    """A mosca na frente de um PC, apertando as teclas do jogo com as patas.

    O corpo fica preso (TetheredWorld) em cima do teclado; cada ação tem a sua
    tecla, perto da pata que a aperta (ver ACOES_JOGO). O monitor mostra o jogo
    ao vivo. Roda numa thread própria: o contexto OpenGL do MuJoCo não pode ficar
    na thread do Qt.
    """

    CAMERAS = ["Mesa", "Teclado", "Tela"]
    BATIDAS_HZ = 7.0  # velocidade com que a pata bate na tecla
    TELA = (640, 360)  # textura do monitor (altura, largura), já girada para o plano

    def __init__(self, resolucao=(540, 720)):
        self.acoes = {a: 0.0 for a in ACOES}
        self.imagem = None
        self.ultimo = np.zeros((*resolucao, 3), dtype=np.uint8)
        self.camera = "Mesa"
        self.batidas_por_s = 0.0
        self.pausado = False
        self.pedido_reinicio = False
        self.erro = None  # mensagem para o painel se a simulação 3D quebrar
        self.rodando = True
        self._ultimo_render = 0.0
        self.thread = threading.Thread(target=self._loop, args=(resolucao,), daemon=True)
        self.thread.start()

    def _loop(self, resolucao):
        try:
            self._montar(resolucao)
            while self.rodando:
                if self.pedido_reinicio:
                    self._reiniciar()
                if self.pausado:
                    time.sleep(0.05)
                    continue
                inicio = time.monotonic()
                self._avancar()
                # No máximo tempo real: mais rápido só gasta CPU e acelera as patas
                passo_s = PASSOS_FISICA_POR_QUADRO * self.sim.timestep
                time.sleep(max(0.0, passo_s - (time.monotonic() - inicio)))
        except Exception as e:
            self.erro = f"Simulação 3D parou: {type(e).__name__}: {e}"
            raise
        finally:
            if hasattr(self, "mj_renderer"):
                self.mj_renderer.close()
            if hasattr(self, "sim"):
                self.sim.close()

    def parar(self):
        self.rodando = False
        self.thread.join()

    def _montar(self, resolucao):
        import mujoco
        from flygym import Simulation
        from flygym.compose.world.tethered_world import TetheredWorld
        from flygym.utils.math import Rotation3D
        from flygym_demo.complex_terrain import (
            PreprogrammedSteps,
            get_default_locomotion_dof_order,
            make_locomotion_fly,
        )
        from flygym.compose import ActuatorType

        self._mujoco = mujoco
        self._tipo_atuador = ActuatorType.POSITION
        fly = make_locomotion_fly(name="mosca", add_adhesion=False, colorize=True)
        world = TetheredWorld()
        spec = world.mjcf_root
        for tex in spec.textures:
            if tex.name == "skybox":
                tex.rgb1, tex.rgb2 = [0.05, 0.05, 0.07], [0.0, 0.0, 0.0]
        wb = spec.worldbody
        caixa = mujoco.mjtGeom.mjGEOM_BOX
        sem_colisao = dict(contype=0, conaffinity=0)

        def objeto(pos, tamanho, cor, **kw):
            return wb.add_geom(type=caixa, pos=pos, size=tamanho, rgba=cor, **sem_colisao, **kw)

        objeto((0, 0, -0.85), (14, 26, 0.25), (0.13, 0.13, 0.15, 1))  # mesa
        objeto((-0.2, 0, -0.42), (3.0, 9.2, 0.18), (0.05, 0.05, 0.06, 1))  # base do teclado

        # Teclas: grade de 5 x 17; as das ações ficam embaixo das patas
        nomes_teclas = {}
        for x in range(-2, 3):
            for y in range(-8, 9):
                nome = f"tecla_{x}_{y}"
                objeto((x, y, -0.12), (0.42, 0.42, 0.12), (0.16, 0.16, 0.18, 1), name=nome)
                nomes_teclas[(x, y)] = nome

        # Monitor com o jogo (textura atualizada a cada quadro)
        th, tw = self.TELA
        tex = spec.add_texture(name="tela", type=mujoco.mjtTexture.mjTEXTURE_2D, width=tw, height=th, nchannel=3)
        tex.data = bytes(th * tw * 3)
        material = spec.add_material(name="tela", emission=1.0)
        material.textures[int(mujoco.mjtTextureRole.mjTEXROLE_RGB)] = "tela"
        wb.add_geom(
            type=mujoco.mjtGeom.mjGEOM_PLANE, pos=(8.0, 0, 5.2), size=(4.5, 8.0, 0.1),
            material="tela", euler=(0, -np.pi / 2, 0), **sem_colisao,
        )
        objeto((8.15, 0, 5.2), (0.12, 8.4, 4.9), (0.02, 0.02, 0.02, 1))  # moldura
        objeto((8.6, 0, -0.1), (0.25, 0.7, 0.6), (0.05, 0.05, 0.06, 1))  # haste
        objeto((8.6, 0, -0.55), (1.5, 2.5, 0.06), (0.05, 0.05, 0.06, 1))  # pé

        wb.add_light(pos=(-4, 6, 14), dir=(0.3, -0.4, -1), diffuse=(0.6, 0.6, 0.65), castshadow=True)
        wb.add_light(pos=(7, 0, 5), dir=(-1, 0, -0.3), diffuse=(0.25, 0.3, 0.45), castshadow=False)
        for nome, pos, alvo in (
            ("Mesa", (-14, 11, 9.5), (4, -0.5, 3)),
            ("Teclado", (-3.5, 4.5, 3.2), (0.6, 0, 0)),
            ("Tela", (-5, -1.8, 2.6), (8, 0.5, 4.5)),
        ):
            wb.add_camera(name=nome, **self._olhar(pos, alvo))

        world.add_fly(fly, [0, 0, 0], Rotation3D("quat", [1, 0, 0, 0]))
        self.sim = Simulation(world)
        modelo = self.sim.mj_model
        self.mj_renderer = mujoco.Renderer(modelo, *resolucao)
        self._tex_id = mujoco.mj_name2id(modelo, mujoco.mjtObj.mjOBJ_TEXTURE, "tela")
        adr = modelo.tex_adr[self._tex_id]
        self._tex = modelo.tex_data[adr : adr + th * tw * 3]

        def geom(nome):
            return mujoco.mj_name2id(modelo, mujoco.mjtObj.mjOBJ_GEOM, nome)

        self._tecla_geom = {nome: geom(nomes_teclas[a.posicao]) for nome, a in ACOES_JOGO.items()}
        self._tecla_z = modelo.geom_pos[next(iter(self._tecla_geom.values()))][2]

        self.passos = PreprogrammedSteps()
        self._ordem = get_default_locomotion_dof_order()
        self._pernas = list(self.passos.legs)
        self._reiniciar()

    @staticmethod
    def _olhar(pos, alvo):
        """Câmera em `pos` olhando para `alvo`."""
        pos, alvo = np.asarray(pos, float), np.asarray(alvo, float)
        z = (pos - alvo) / np.linalg.norm(pos - alvo)
        x = np.cross([0, 0, 1], z)
        x /= np.linalg.norm(x)
        return dict(pos=pos, xyaxes=np.concatenate([x, np.cross(z, x)]))

    def _reiniciar(self):
        self.pedido_reinicio = False
        self.sim.reset()
        self.sim.warmup()
        self.fases = np.full(len(self._pernas), np.pi)
        self.amplitudes = np.zeros(len(self._pernas))
        self._apertando = np.zeros(len(self._pernas), dtype=bool)
        self._batidas = collections.deque()

    def passo(self, acoes, imagem=None):
        """Chamado pela interface: guarda ações e a tela do jogo; devolve o último quadro."""
        self.acoes, self.imagem = acoes, imagem
        return self.ultimo

    def _mostrar_no_monitor(self):
        if self.imagem is None:
            return
        th, tw = self.TELA
        h, w = self.imagem.shape[:2]
        linhas = np.linspace(0, h - 1, tw).astype(int)
        colunas = np.linspace(0, w - 1, th).astype(int)
        quadro = self.imagem[linhas][:, colunas]  # redimensiona para tw x th
        self._tex[:] = np.rot90(quadro, -1).ravel()  # gira para casar com o plano
        self._mujoco.mjr_uploadTexture(self.sim.mj_model, self.mj_renderer._mjr_context, self._tex_id)

    def _avancar(self):
        acoes = self.acoes
        dt = PASSOS_FISICA_POR_QUADRO * self.sim.timestep
        acoes_ativas = [nome for nome in ACOES_JOGO if acoes[nome] > 0.5]
        ativas = np.zeros(len(self._pernas), dtype=bool)
        for nome in acoes_ativas:
            ativas[self._pernas.index(ACOES_JOGO[nome].pata)] = True

        # Pata ativa bate na tecla (ciclo de passo no lugar); as outras voltam ao repouso
        self.amplitudes += 0.35 * (ativas.astype(float) - self.amplitudes)
        self.fases[ativas] += 2 * np.pi * self.BATIDAS_HZ * dt
        angulos = self.passos.get_joint_angles_by_dof_order(self.fases, self.amplitudes, self._ordem)
        self.sim.set_actuator_inputs("mosca", self._tipo_atuador, angulos)
        for _ in range(PASSOS_FISICA_POR_QUADRO):
            self.sim.step()

        # Tecla afunda e acende quando a pata está na fase de apoio
        modelo = self.sim.mj_model
        apoio = self.passos.get_adhesion_onoff_by_phase(self.fases).astype(bool)
        apertando = ativas & apoio & (self.amplitudes > 0.5)
        agora = self.sim.time
        self._batidas.extend([agora] * np.count_nonzero(apertando & ~self._apertando))
        while self._batidas and self._batidas[0] < agora - 1.0:
            self._batidas.popleft()
        self.batidas_por_s = len(self._batidas)  # no último segundo (tempo simulado)
        self._apertando = apertando
        for nome, acao in ACOES_JOGO.items():
            g = self._tecla_geom[nome]
            batendo = nome in acoes_ativas and apertando[self._pernas.index(acao.pata)]
            modelo.geom_pos[g][2] = self._tecla_z - (0.09 if batendo else 0.0)
            if batendo:
                modelo.geom_rgba[g] = (1.0, 0.77, 0.27, 1)
            elif nome in acoes_ativas:
                modelo.geom_rgba[g] = (0.49, 0.36, 1.0, 1)
            else:
                modelo.geom_rgba[g] = (0.24, 0.24, 0.3, 1)  # teclas de ação um pouco mais claras
        self._mujoco.mj_kinematics(modelo, self.sim.mj_data)

        # Renderizar mais que a tela mostra (QUADRO_MS) só gasta CPU/GPU
        agora = time.monotonic()
        if agora - self._ultimo_render < QUADRO_MS / 1000:
            return
        self._ultimo_render = agora
        self._mostrar_no_monitor()
        self.mj_renderer.update_scene(self.sim.mj_data, camera=self.camera)
        self.ultimo = self.mj_renderer.render().copy()


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


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
        self.base = pg.ScatterPlotItem(pos=pos, size=2.2, pen=None, brush=pg.mkBrush(*COR_REPOUSO))
        self.camada_estimulo = pg.ScatterPlotItem(size=3.2, pen=None, brush=pg.mkBrush(*COR_ESTIMULADO))
        self.brilho = pg.ScatterPlotItem(size=9, pen=None, brush=pg.mkBrush(255, 196, 70, 40))
        self.camada_disparo = pg.ScatterPlotItem(size=3.5, pen=None, brush=pg.mkBrush(*COR_DISPARO))
        self.camada_pam = pg.ScatterPlotItem(size=4.5, pen=None, brush=pg.mkBrush(*COR_RECOMPENSA))
        self.camada_ppl1 = pg.ScatterPlotItem(size=4.5, pen=None, brush=pg.mkBrush(*COR_PUNICAO))
        for item in (
            self.base, self.camada_estimulo, self.brilho, self.camada_disparo,
            self.camada_pam, self.camada_ppl1,
        ):
            self.vista.addItem(item)
        for nome, texto in (("PAM", "+"), ("PPL1", "−")):
            cx, cy, _ = cerebro.DOPAMINA[nome]
            txt = pg.TextItem(texto, color=(200, 205, 225, 170), anchor=(0.5, 0.5))
            txt.setPos(cx, cy)
            self.vista.addItem(txt)
        for nome, (cx, cy, _) in cerebro.ZONAS.items():
            txt = pg.TextItem(ROTULO_TECLA[nome], color=(200, 205, 225, 170), anchor=(0.5, 0.5))
            txt.setPos(cx, cy)
            self.vista.addItem(txt)
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
        for i, (nome, acao) in enumerate(ACOES_JOGO.items()):
            bt = QtWidgets.QPushButton(f"{acao.rotulo}  {acao.curto}")
            bt.setToolTip(f"{nome} (tecla {acao.rotulo})")
            bt.clicked.connect(lambda _, n=nome: cerebro.pulsar_zona(n))
            acoes.addWidget(bt, i // 6, i % 6)
        layout.addLayout(acoes)

        self.vista.pincelada.connect(self.pintar)
        self.vista.fim_pincelada.connect(self.fim_pincelada)
        self.vista.cursor.connect(self.mover_circulo)
        self.atualizar_selecao()

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

    def atualizar(self):
        pos = self.cerebro.posicoes
        # Selecionados aparecem roxos; durante o pulso, tudo que está sendo estimulado
        self.camada_estimulo.setData(pos=pos[self.cerebro.selecao | self.cerebro.estimulados()])
        disparos = self.cerebro.disparos
        disparando = pos[disparos]
        self.camada_disparo.setData(pos=disparando)
        self.brilho.setData(pos=disparando)
        self.camada_pam.setData(pos=pos[np.intersect1d(disparos, self.cerebro.dopamina["PAM"])])
        self.camada_ppl1.setData(pos=pos[np.intersect1d(disparos, self.cerebro.dopamina["PPL1"])])


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
        self.bt_gravar = QtWidgets.QPushButton("⏺  Gravar")
        self.bt_gravar.setCheckable(True)
        self.bt_gravar.setObjectName("gravar")
        self.bt_gravar.setToolTip(
            "Você joga e o programa grava a tela e as suas teclas,\n"
            "para depois treinar a mosca com o treinar.py"
        )
        self.bt_controlar = QtWidgets.QPushButton("🎮  Controlar jogo")
        self.bt_controlar.setCheckable(True)
        self.bt_controlar.setToolTip(
            "A mosca aperta as teclas no jogo (" + ", ".join(ROTULO_TECLA.values()) + ")"
        )
        self.bt_pausar = QtWidgets.QPushButton("❚❚  Pausar")
        self.bt_reiniciar = QtWidgets.QPushButton("↺  Reiniciar")
        linha.addWidget(self.bt_gravar)
        linha.addWidget(self.bt_controlar)
        linha.addWidget(self.bt_pausar)
        linha.addWidget(self.bt_reiniciar)
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

    def atualizar_recompensa(self, soma, vida, ultimo):
        """`soma` dos últimos 10 s, vida lida no HUD e último evento (ou None)."""
        cor = "#4ade80" if soma > 0 else "#f87171" if soma < 0 else COR_TEXTO
        self.m_recompensa.valor.setStyleSheet(f"color: {cor};")
        self.m_recompensa.definir_texto(f"{soma:+.1f}", abs(soma) / 3)
        partes = [f"♥ {vida}" if vida is not None else "HUD não visível"]
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
        elif self.mosca.pausado:
            texto = "❚❚ Pausada"
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
        }
        nome_d, nome_c = self._nome("desafiante"), self._nome("campea")
        self._terminar_partida()
        t.encerrar(resultado)
        self._envios.append(marcar_torneio(desafiante.treino_id if desafiante else None, placar))
        if resultado == "venceu":
            self.modelos["campea"] = desafiante
            texto = (f"🏆 A {nome_d} venceu ({placar['por_minuto']:+.1f}/min contra "
                     f"{placar['por_minuto_campea']:+.1f}/min) e virou a campeã")
        else:
            texto = (f"A {nome_d} perdeu ({placar['por_minuto']:+.1f}/min contra "
                     f"{placar['por_minuto_campea']:+.1f}/min): a {nome_c} continua")
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
        return f"⚔ {self._nome(self.papel)} jogando · " + " × ".join(partes)

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
        "parada": "ficou parada",
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
