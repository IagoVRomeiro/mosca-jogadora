"""Estímulos do jogo: o leitor do HUD (dano, morte, acerto, geo, cura), a parada,
ficar presa (contra parede, pulando onde não alcança), andar em círculos (loop) e a
exploração (salas novas e lugares novos no mapa)."""

from pathlib import Path

import numpy as np

from .config import PASTA, QUADRO_MS
from .olho import cinza, ver


# Versão da leitura do HUD, guardada nas gravações. Até a 1, o HUD escurecido
# (mapa aberto, transição) virava "morte" falsa: o treino ignora as mortes delas.
VERSAO_HUD = 2


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
    SUMIDO_MORTE = 45  # quadros sem HUD (~1,5 s) que, com 1 máscara, indicam morte
    # O HUD escurece em transições, com o mapa aberto e em menus: as máscaras
    # ficam opacas e pareceriam vazias. Só lê o HUD aceso (contorno do vaso de
    # alma a pelo menos ACESO do brilho normal); escurecido conta como fora da tela.
    ACESO = 0.85
    PRETO = 40  # contorno abaixo disto: tela preta (morte, passagem de sala), não só escurecida
    RECOMPENSA = {
        "dano": -1.0, "morte": -3.0, "cura": 0.3, "acerto": 0.3, "geo": 0.5, "parada": -0.2,
        "sala_nova": 1.0, "presa": -0.3, "mapa_novo": 0.5, "loop": -0.3,
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
        self._brilho_normal = 0.0  # brilho do contorno do vaso com o HUD aceso
        self.visivel = False

    def _caixa(self, cinza, cx, cy, r):
        h = cinza.shape[0]
        x, y, r = int(cx * h), int(cy * h), max(1, int(r * h))
        return cinza[max(0, y - r) : y + r + 1, max(0, x - r) : x + r + 1]

    def ler(self, quadro):
        """Leitura crua de um quadro: (brilho do contorno do vaso, máscaras cheias,
        alma 0..1, assinatura do geo)."""
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
        # O contorno do vaso é sempre claro com o HUD na tela
        borda = self._caixa(cinza, cx, cy - r * 0.9, 0.006)
        brilho = float(borda.max()) if borda.size else 0.0
        alma = float((vaso > 150).mean()) if vaso.size else 0.0
        x0, x1, y0, y1 = self.GEO
        geo = cinza[int(y0 * h) : int(y1 * h), int(x0 * h) : int(x1 * h)] > 150
        return brilho, cheias, alma, geo

    def passo(self, quadro):
        """Devolve (recompensa deste quadro, lista de eventos)."""
        brilho, cheias, alma, geo = self.ler(quadro)
        if brilho > 120:  # referência do HUD aceso: o maior brilho recente
            self._brilho_normal = max(self._brilho_normal * 0.9995, brilho)
        presente = brilho > 120 and brilho >= self.ACESO * self._brilho_normal
        self.visivel = presente and cheias > 0
        eventos = []
        if not self.visivel:
            self._repeticoes = self._geo_rep = 0
            self.alma = None  # ao voltar, a alma clareando não é "acerto"
            if presente:  # HUD aceso sem nenhuma máscara: morreu
                self._zeradas += 1
                if self._zeradas == self.ESTAVEL and self.vida is not None:
                    eventos.append("morte")
                    self.vida = None  # a vida de volta ao renascer não é cura
            elif brilho < self.PRETO:  # tela preta (escurecido pelo mapa/menu não conta)
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


class ExploradorSalas:
    """Reconhece salas pela "foto de entrada" e recompensa chegar numa sala nova.

    No Hollow Knight, passar de uma sala para outra escurece a tela por ~0,8 s e
    a sala nova aparece sempre do mesmo ponto de vista para a mesma porta. A
    foto tirada logo depois do escurecimento é comparada com a memória de salas
    (que fica salva e vale entre sessões): parecida com alguma (semelhança >=
    LIMITE) é sala conhecida; senão, é sala nova e entra na memória.

    Medido nas suas gravações: entradas repetidas dão semelhança >= 0,95 e salas
    diferentes ficam entre 0,6 e 0,85. Olhar a tela o tempo todo, em vez da
    entrada, não funciona: inimigos e a câmera mudam tudo dentro da mesma sala.
    """

    ESCURO = 4  # brilho médio (0-255) abaixo disto: tela escura
    TRANSICAO = (3, 60)  # quadros escuros de uma passagem de sala (mais: morte, banco)
    ESPERA = 20  # quadros depois de clarear para tirar a foto (~0,7 s)
    LIMITE = 0.92
    MAXIMO_SALAS = 5000

    def __init__(self, arquivo=PASTA / "memoria_salas.npz"):
        self.arquivo = Path(arquivo)
        self.memoria = np.zeros((0, 576), np.float32)
        if self.arquivo.exists():
            with np.load(self.arquivo) as dados:
                self.memoria = dados["salas"]
        self._escuro, self._foto_em = 0, None
        self.alterada = False

    @property
    def salas(self):
        return len(self.memoria)

    @staticmethod
    def foto(reduzida):
        """Assinatura da sala: brilho em 18 x 32 blocos, sem a média, normalizado."""
        b = ver(reduzida)[:576]
        b = b - b.mean()
        return (b / (np.linalg.norm(b) + 1e-6)).astype(np.float32)

    def entrada_de_sala(self, reduzida):
        """A foto de entrada (assinatura) quando a mosca acabou de entrar numa
        sala; None nos outros quadros. Não consulta a memória."""
        corpo = cinza(reduzida)[20:].mean()  # sem o HUD, no alto da tela
        if corpo < self.ESCURO:
            self._escuro += 1
            self._foto_em = None
            return None
        if self.TRANSICAO[0] <= self._escuro <= self.TRANSICAO[1]:
            self._foto_em = self.ESPERA  # passou de sala: foto daqui a pouco
        self._escuro = 0
        if self._foto_em is None:
            return None
        self._foto_em -= 1
        if self._foto_em > 0:
            return None
        self._foto_em = None
        return self.foto(reduzida)

    def lembrar(self, assinatura):
        """True se a sala é nova (e passa a ser lembrada); False se já conhecida."""
        if len(self.memoria) and float((self.memoria @ assinatura).max()) >= self.LIMITE:
            return False
        self.memoria = np.vstack([self.memoria, assinatura])[-self.MAXIMO_SALAS :]
        self.alterada = True
        return True

    def passo(self, reduzida):
        """Uma tela (em OLHO). Devolve ["sala_nova"] na entrada de uma sala nova."""
        assinatura = self.entrada_de_sala(reduzida)
        return ["sala_nova"] if assinatura is not None and self.lembrar(assinatura) else []

    def salvar(self):
        if self.alterada:
            temporario = self.arquivo.with_name(self.arquivo.stem + ".tmp.npz")
            np.savez_compressed(temporario, salas=self.memoria)
            temporario.replace(self.arquivo)
            self.alterada = False


def deslizamento(antes, depois):
    """Quanto a câmera andou (dx, dy em pixels de OLHO; dx > 0 = para a direita)
    de `antes` para `depois`, por correlação de fase, sem a faixa do HUD (que fica
    parada e puxaria para zero)."""
    a, b = cinza(antes)[24:].astype(np.float32), cinza(depois)[24:].astype(np.float32)
    janela = _janela(a.shape)
    a, b = (a - a.mean()) * janela, (b - b.mean()) * janela
    f = np.fft.rfft2(a) * np.conj(np.fft.rfft2(b))
    r = np.fft.irfft2(f / (np.abs(f) + 1e-6), s=a.shape)
    y, x = np.unravel_index(np.argmax(r), r.shape)
    if y > a.shape[0] // 2:
        y -= a.shape[0]
    if x > a.shape[1] // 2:
        x -= a.shape[1]
    return int(x), int(y)


_JANELAS = {}


def _janela(forma):
    if forma not in _JANELAS:
        _JANELAS[forma] = np.outer(np.hanning(forma[0]), np.hanning(forma[1])).astype(np.float32)
    return _JANELAS[forma]


class DetectorPresa:
    """Presa: apertando para andar, mas a câmera não sai do lugar na horizontal.

    O jogo segue o Cavaleiro com a câmera; a cada PASSO quadros mede quanto a
    imagem deslizou (sem o HUD). Se em JANELA_S segundos uma direção ficou
    apertada em >= 70% do tempo e a câmera não andou nada na horizontal (nem
    para lá e para cá), é "presa": contra uma parede ou pulando onde não alcança
    (o pulo mexe a câmera na vertical, por isso só a horizontal conta). Repete a
    cada REPETE_S enquanto continuar. Medido nas suas gravações: com 6 s, só ~4%
    dos trechos em que você andava contariam (câmera travada, luta na parede).
    """

    PASSO = 10  # quadros entre duas medidas (~0,33 s): quadro a quadro é < 1 pixel
    JANELA_S, REPETE_S = 6.0, 3.0
    LIMITE_PX = 6  # deslizamento horizontal total na janela

    def __init__(self, dt=QUADRO_MS / 1000):
        self.medidas = int(self.JANELA_S / dt) // self.PASSO
        self.repete = int(self.REPETE_S / dt)
        self.reiniciar()

    def reiniciar(self):
        self._quadro, self._anterior = 0, None
        self._dx, self._lados = [], []
        self._espera = 0
        self.lado = None  # "Esquerda" ou "Direita": para onde ela estava forçando

    def passo(self, reduzida, esquerda, direita, hud_visivel):
        """`esquerda`/`direita`: se a tecla está apertada neste quadro."""
        if not hud_visivel:
            self.reiniciar()
            return []
        self._lados.append(1 if direita else -1 if esquerda else 0)
        self._lados = self._lados[-self.medidas * self.PASSO :]
        self._espera = max(0, self._espera - 1)
        self._quadro += 1
        if self._quadro % self.PASSO:
            return []
        if self._anterior is not None:
            self._dx.append(abs(deslizamento(self._anterior, reduzida)[0]))
            self._dx = self._dx[-self.medidas :]
        self._anterior = reduzida
        lados = np.array(self._lados)
        forcando = max((lados == 1).mean(), (lados == -1).mean()) if len(lados) else 0
        if len(self._dx) < self.medidas or forcando < 0.7 or self._espera:
            return []
        if sum(self._dx) > self.LIMITE_PX:
            return []
        self.lado = "Direita" if (lados == 1).mean() >= (lados == -1).mean() else "Esquerda"
        self._espera = self.repete
        return ["presa"]


class LeitorMapa:
    """Onde a mosca está no mapa rápido (Tab), pela marca da Bússola Errante.

    - Posição: a marca (cabeça branca do Cavaleiro) achada por correlação com um
      modelo recortado do seu jogo (marca_bussola.npy, numa tela de 523 de altura).
    - Área: o título no alto do mapa ("Encruzilhada Esquecida"...), comparado pelo
      desenho das letras; cada título diferente é uma área numerada.
    - Exploração: o mapa da área é dividido em células de CELULA (fração da
      altura); chegar numa célula nunca vista é "mapa_novo". A memória fica salva.
    Sem a marca (mapa não abriu, área sem mapa), não lê nada.
    """

    MODELO = Path(__file__).with_name("marca_bussola.npy")
    ALTURA_MODELO = 523
    SEMELHANCA = 0.75  # medido: a marca dá 0,83-1,00; o resto do mapa ~0,5
    TITULO = (0.06, 0.13, 0.35)  # y0, y1, meia largura (fração da altura, centrado)
    MESMA_AREA = 0.6  # sobreposição mínima do desenho do título
    CELULA = 0.045

    def __init__(self, arquivo=PASTA / "memoria_mapa.npz"):
        self.arquivo = Path(arquivo)
        self._modelo = np.load(self.MODELO).astype(np.float32)
        self._modelos = {}
        self.titulos, self.celulas = [], set()
        if self.arquivo.exists():
            with np.load(self.arquivo) as dados:
                self.titulos = list(dados["titulos"])
                self.celulas = {tuple(int(v) for v in c) for c in dados["celulas"]}
        self.posicao = None  # (área, x, y em fração da altura), da última leitura

    def _modelo_na_escala(self, altura):
        if altura not in self._modelos:
            from PIL import Image

            escala = altura / self.ALTURA_MODELO
            h, w = (max(5, round(d * escala)) for d in self._modelo.shape)
            m = np.asarray(Image.fromarray(self._modelo).resize((w, h)), np.float32)
            m = m - m.mean()
            self._modelos[altura] = m / (np.linalg.norm(m) + 1e-6)
        return self._modelos[altura]

    def achar_marca(self, quadro):
        """(x, y) da marca em pixels e a semelhança, ou None se não achou."""
        from scipy.ndimage import uniform_filter
        from scipy.signal import fftconvolve

        img = cinza(quadro).astype(np.float32)
        t = self._modelo_na_escala(img.shape[0])
        h, w = t.shape
        num = fftconvolve(img, t[::-1, ::-1], mode="valid")
        corte = (slice(h // 2, h // 2 + num.shape[0]), slice(w // 2, w // 2 + num.shape[1]))
        media = uniform_filter(img, (h, w))[corte]
        media2 = uniform_filter(img**2, (h, w))[corte]
        semelhanca = num / np.sqrt(np.maximum(media2 - media**2, 1e-6) * h * w)
        y, x = np.unravel_index(np.argmax(semelhanca), semelhanca.shape)
        if semelhanca[y, x] < self.SEMELHANCA:
            return None
        return x + w // 2, y + h // 2, float(semelhanca[y, x])

    def _area(self, quadro):
        """Número da área pelo desenho do título (nova área se não parecer com nenhuma)."""
        img = cinza(quadro)
        alt, larg = img.shape
        y0, y1, meia = self.TITULO
        desenho = img[int(y0 * alt) : int(y1 * alt), larg // 2 - int(meia * alt) : larg // 2 + int(meia * alt)] > 170
        for i, conhecido in enumerate(self.titulos):
            if conhecido.shape == desenho.shape:
                uniao = np.count_nonzero(conhecido | desenho)
                if uniao and np.count_nonzero(conhecido & desenho) / uniao >= self.MESMA_AREA:
                    return i
        self.titulos.append(desenho)
        return len(self.titulos) - 1

    def ler(self, quadro):
        """Lê o mapa aberto. Devolve ["mapa_novo"] se chegou numa célula nova."""
        marca = self.achar_marca(quadro)
        if marca is None:
            return []
        alt = cinza(quadro).shape[0]
        area = self._area(quadro)
        x, y = marca[0] / alt, marca[1] / alt
        self.posicao = (area, x, y)
        celula = (area, int(x / self.CELULA), int(y / self.CELULA))
        if celula in self.celulas:
            return []
        self.celulas.add(celula)
        self.salvar()
        return ["mapa_novo"]

    def salvar(self):
        temporario = self.arquivo.with_name(self.arquivo.stem + ".tmp.npz")
        titulos = np.array(self.titulos) if self.titulos else np.zeros((0, 1, 1), bool)
        np.savez_compressed(temporario, titulos=titulos, celulas=np.array(sorted(self.celulas)).reshape(-1, 3))
        temporario.replace(self.arquivo)


class DetectorLoop:
    """Andando em círculos: indo e voltando no mesmo trecho sem nada de bom acontecer.

    A cada PASSO quadros mede o deslizamento horizontal da câmera. Em JANELA_S:
    andou bastante (soma > ANDOU_PX), mas o saldo ficou perto de zero (< SALDO_PX)
    e não houve nenhum evento bom (acerto, geo, sala ou lugar novo, cura). Lutar
    indo e voltando dá acertos, então não conta. Medido: ~1% dos trechos com você
    jogando, ~40% com a mosca. Repete a cada REPETE_S enquanto continuar.
    """

    PASSO = 10
    JANELA_S, REPETE_S = 15.0, 5.0
    ANDOU_PX, SALDO_PX = 60, 15

    def __init__(self, dt=QUADRO_MS / 1000):
        self.medidas = int(self.JANELA_S / dt) // self.PASSO
        self.repete = int(self.REPETE_S / dt)
        self.reiniciar()

    def reiniciar(self):
        self._quadro, self._anterior = 0, None
        self._dx, self._bom = [], []
        self._bom_agora = False
        self._espera = 0

    def passo(self, reduzida, algo_bom, hud_visivel):
        """`algo_bom`: houve recompensa positiva neste quadro."""
        if not hud_visivel:
            self.reiniciar()
            return []
        self._bom_agora = self._bom_agora or algo_bom
        self._espera = max(0, self._espera - 1)
        self._quadro += 1
        if self._quadro % self.PASSO:
            return []
        if self._anterior is not None:
            self._dx.append(deslizamento(self._anterior, reduzida)[0])
            self._bom.append(self._bom_agora)
            self._dx, self._bom = self._dx[-self.medidas :], self._bom[-self.medidas :]
        self._anterior, self._bom_agora = reduzida, False
        if len(self._dx) < self.medidas or self._espera or any(self._bom):
            return []
        andou, saldo = sum(abs(d) for d in self._dx), abs(sum(self._dx))
        if andou <= self.ANDOU_PX or saldo >= self.SALDO_PX:
            return []
        self._espera = self.repete
        return ["loop"]
