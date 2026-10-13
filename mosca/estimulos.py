"""Estímulos do jogo: o leitor do HUD (dano, morte, acerto, geo, cura) e a parada."""

import numpy as np

from .config import QUADRO_MS
from .olho import cinza


class LeitorHUD:
    """Lê o HUD do Hollow Knight pela imagem e transforma em estímulos.

    Coordenadas em fração da altura da tela (o HUD escala com ela; 16:9):
    - máscaras de vida: cheia é branca, vazia é azul-escura -> dano/cura
    - vaso de alma: enche quando o Cavaleiro acerta um inimigo -> "acertou"
    - número de geo: mudou -> pegou geo
    - morte: máscaras zeradas com o HUD na tela, ou o HUD some com 1 máscara e
      volta com mais (morreu, tela preta, renasceu no banco). A vida de volta
      ao renascer NÃO conta como cura (antes contava: morrer dava recompensa).
    Uma leitura só vale depois de repetir por alguns quadros (o HUD pisca e
    some em transições e menus).
    """

    MASCARA_X0, MASCARA_PASSO, MASCARA_Y = 0.263, 0.0457, 0.0876
    MAX_MASCARAS = 11
    ALMA = (0.187, 0.118, 0.040)  # centro x, centro y, raio
    GEO = (0.286, 0.495, 0.137, 0.181)  # x0, x1, y0, y1
    ESTAVEL = 3  # quadros iguais para aceitar uma leitura
    SUMIDO_MORTE = 30  # quadros sem HUD (~1 s) que, com 1 máscara, indicam morte
    RECOMPENSA = {
        "dano": -1.0, "morte": -3.0, "cura": 0.3, "acerto": 0.3, "geo": 0.5, "parada": -0.2,
    }

    def __init__(self):
        self.reiniciar()

    def reiniciar(self):
        self.vida = None  # máscaras cheias aceitas
        self.alma = None
        self.gastando_alma = False  # vaso esvaziando: curando com o Foco ou usando magia
        self._geo = None
        self._candidato, self._repeticoes = None, 0
        self._geo_cand, self._geo_rep = None, 0
        self._zeradas = self._sumido = 0
        self.visivel = False

    def _caixa(self, cinza, cx, cy, r):
        h = cinza.shape[0]
        x, y, r = int(cx * h), int(cy * h), max(1, int(r * h))
        return cinza[max(0, y - r) : y + r + 1, max(0, x - r) : x + r + 1]

    def ler(self, quadro):
        """Leitura crua de um quadro: (hud na tela?, máscaras cheias, alma 0..1, assinatura do geo)."""
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
        presente = bool(borda.size and borda.max() > 120)
        alma = float((vaso > 150).mean()) if vaso.size else 0.0
        x0, x1, y0, y1 = self.GEO
        geo = cinza[int(y0 * h) : int(y1 * h), int(x0 * h) : int(x1 * h)] > 150
        return presente, cheias, alma, geo

    def passo(self, quadro):
        """Devolve (recompensa deste quadro, lista de eventos)."""
        presente, cheias, alma, geo = self.ler(quadro)
        self.visivel = presente and cheias > 0
        eventos = []
        if not self.visivel:
            self._repeticoes = self._geo_rep = 0
            if presente:  # HUD na tela sem nenhuma máscara: morreu
                self._zeradas += 1
                if self._zeradas == self.ESTAVEL and self.vida is not None:
                    eventos.append("morte")
                    self.vida = None  # a vida de volta ao renascer não é cura
            else:
                self._sumido += 1
            return sum(self.RECOMPENSA[e] for e in eventos), eventos

        # O HUD sumiu com 1 máscara e voltou com mais: morreu e renasceu
        if self._sumido >= self.SUMIDO_MORTE and self.vida is not None and self.vida <= 1 < cheias:
            eventos.append("morte")
            self.vida = None
        self._zeradas = self._sumido = 0

        # Vida: só aceita um valor novo se ele se repetir (evita piscadas)
        if cheias == self._candidato:
            self._repeticoes += 1
        else:
            self._candidato, self._repeticoes = cheias, 1
        if self._repeticoes >= self.ESTAVEL and cheias != self.vida:
            if self.vida is not None:  # None: começo ou depois de morrer, só aceita
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
