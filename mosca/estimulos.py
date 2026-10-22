"""Estímulos do jogo: o leitor do HUD (dano, morte, acerto, geo, cura), a parada,
ficar presa (contra parede, pulando onde não alcança), andar em círculos (loop) e a
exploração (salas novas)."""

from pathlib import Path

import numpy as np

from .config import PASTA, QUADRO_MS
from .olho import cinza, ver


# Versão da leitura do HUD, guardada nas gravações. Até a 1, o HUD escurecido
# (mapa aberto, transição) virava "morte" falsa: o treino ignora as mortes delas.
VERSAO_HUD = 3  # 3: máscara cheia pela fração clara (a última tremendo não pisca mais)


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
    MASCARA_CHEIA = 0.15  # fração clara da caixa que conta como máscara cheia
    ALMA = (0.187, 0.118, 0.040)  # centro x, centro y, raio
    # x0, x1, y0, y1: só a linha do número (0,144-0,170); logo abaixo aparece o
    # "+N" ao pegar geo, e ele sumindo contava como mudança do número
    GEO = (0.286, 0.495, 0.137, 0.174)
    ESTAVEL = 3  # quadros iguais para aceitar uma leitura
    SUMIDO_MORTE = 45  # quadros sem HUD (~1,5 s) que, com 1 máscara, indicam morte
    # O HUD escurece em transições, com o mapa aberto e em menus: as máscaras
    # ficam opacas e pareceriam vazias. Só lê o HUD aceso (contorno do vaso de
    # alma a pelo menos ACESO do brilho normal); escurecido conta como fora da tela.
    ACESO = 0.85
    PRETO = 40  # contorno abaixo disto: tela preta (morte, passagem de sala), não só escurecida
    RECOMPENSA = {
        # dano e morte pesam mais que parada e loop juntos (medido em 59 min da
        # mosca: com -1 e -3, ficar parada e andar em círculos puniam mais que morrer)
        "dano": -2.0, "morte": -8.0, "cura": 0.3, "acerto": 0.3, "geo": 0.5, "parada": -0.2,
        # sala nova pela tela vale pouco (dá para burlar entrando e saindo).
        # Presa e loop: -0,6 até 20/10. Mais punitivos porque eram o vício dela
        # (loop ~4,4 por minuto, em 227 min) e quase não pesavam no treino
        "sala_nova": 0.3, "presa": -1.5, "loop": -1.2,
        # forçando a parede por 4 s (quando entra o reflexo de escapar): sem isto a
        # punição de presa (6 s) quase nunca chegava, o reflexo a salvava antes
        "parede": -0.5,
        # só com o plugin: 1 min sem pedaço, sala ou banco novo e sem lutar
        # (fora do Salão dos Deuses); repete a cada 15 s
        "sem_novidade": -0.5,
        # só com o juiz de dentro do jogo (mosca/juiz.py): exatos, não dá para burlar
        "inimigo_morto": 1.0, "cena_nova": 1.0,
        "lugar_novo": 0.2,  # um pedaço novo de uma sala (8x8 unidades do jogo)
        "banco_novo": 1.0,  # descansou num banco nunca usado: progresso real
        # a mais na cura com 1-2 máscaras (curar quando importa). 0,3 até 21/10:
        # nas arenas ela curava 0,01 vez por minuto (você, 2,7)
        "cura_critica": 1.0,
        # magia: detectada pela alma gasta de uma vez (o plugin manda a alma)
        "magia": 0.0,
        "magia_sem_alvo": -0.5,  # nenhum golpe acertou no 1 s seguinte
        "magia_com_vida_baixa": -0.5,  # com 1-2 máscaras: a alma devia ter ido para curar
        # esquiva que não sai do lugar (bateu na parede) e golpe parado ou grudado na
        # parede que não acerta nada. Medido em 21/10: 92 esquivas por minuto de luta,
        # 58% na parede; 140 golpes por minuto, só 8% acertando
        "esquiva_na_parede": -0.1,
        "golpe_na_parede": -0.05,
        # a mais no dano ao cair em espinhos ou ácido (erro evitável). -1 até 20/10:
        # na arena dos Mantis Lords ela caía 11,7 vezes por minuto (você, 0,21)
        "perigo": -2.0,
        "vai_e_volta": -1.0,  # entrando e saindo pela mesma passagem sem ganhar nada
        # chefe vencido (Salão dos Deuses ou 200+ de vida): uma luta longa ganha precisa
        # valer mais que o dano tomado nela
        "chefe_derrotado": 5.0,
        # a cada 1% da vida de um chefe tirado (3 no chefe inteiro): o +5 do fim de
        # uma luta longa fica longe demais dos golpes que levaram até ele
        "dano_chefe": 0.03,
        "sombra_recuperada": 2.0,  # voltou onde morreu e pegou o geo de volta
        # o mesmo inimigo (cena e nome) morto de novo depois de renascer: farmar
        # saindo da sala ou descansando no banco quase não vale
        "inimigo_repetido": 0.1,
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
            # Cheia = boa parte da caixa clara. Só "algum pixel claro" não serve: com
            # 1 máscara o jogo faz a última tremer e a borda dela invade a caixa da
            # seguinte (medido: cheia >= 35% clara; a borda tremendo <= 2%)
            if caixa.size and (caixa > 150).mean() >= self.MASCARA_CHEIA:
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
            # o geo que aparecer na volta é a nova referência: depois de morrer
            # ele volta zerado, e isso não é "pegou geo"
            self._geo = None
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

    Medido nas gravações, salas diferentes ficam entre 0,6 e 0,8; a mesma sala
    vista de novo deu de 0,83 a 0,98 (a mosca entrando e saindo da mesma sala
    ganhava "sala nova" a cada vez com o limite antigo de 0,92). Olhar a tela o
    tempo todo, em vez da entrada, não funciona: tudo muda dentro da mesma sala.

    Entrar e sair não é explorar: uma sala só dá recompensa se a passagem
    anterior foi há pelo menos INTERVALO_MINIMO quadros (ela entra na memória
    mesmo assim).
    """

    ESCURO = 4  # brilho médio (0-255) abaixo disto: tela escura
    TRANSICAO = (3, 60)  # quadros escuros de uma passagem de sala (mais: morte, banco)
    ESPERA = 20  # quadros depois de clarear para tirar a foto (~0,7 s)
    LIMITE = 0.82
    INTERVALO_MINIMO = 8 * 30  # quadros (~8 s) entre duas passagens de sala
    MAXIMO_SALAS = 5000

    def __init__(self, arquivo=PASTA / "memoria_salas.npz"):
        self.arquivo = Path(arquivo)
        self.memoria = np.zeros((0, 576), np.float32)
        if self.arquivo.exists():
            with np.load(self.arquivo) as dados:
                self.memoria = dados["salas"]
        self._escuro, self._foto_em = 0, None
        self._quadro, self._ultima_entrada = 0, None
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

    def lembrar(self, assinatura, intervalo=None):
        """True se a sala é nova e vale recompensa. `intervalo`: quadros desde a
        passagem de sala anterior (None = não se sabe). Sala nova logo depois de
        outra passagem entra na memória, mas não dá recompensa."""
        if len(self.memoria) and float((self.memoria @ assinatura).max()) >= self.LIMITE:
            return False
        self.memoria = np.vstack([self.memoria, assinatura])[-self.MAXIMO_SALAS :]
        self.alterada = True
        return intervalo is None or intervalo >= self.INTERVALO_MINIMO

    def passo(self, reduzida):
        """Uma tela (em OLHO). Devolve ["sala_nova"] na entrada de uma sala nova."""
        self._quadro += 1
        assinatura = self.entrada_de_sala(reduzida)
        if assinatura is None:
            return []
        intervalo = None if self._ultima_entrada is None else self._quadro - self._ultima_entrada
        self._ultima_entrada = self._quadro
        return ["sala_nova"] if self.lembrar(assinatura, intervalo) else []

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

    Antes disso, com AVISO_S segundos encostada, liga `encostada` (sem punir):
    é a deixa para o reflexo de meia-volta agir cedo.

    Escalando a parede (Garra de Louva-a-deus) também não anda na horizontal,
    mas a câmera sobe (ou desce) de verdade: com saldo vertical acima de
    SUBIU_PX na janela não é presa. Pular onde não alcança sobe e volta, saldo ~0.
    """

    PASSO = 10  # quadros entre duas medidas (~0,33 s): quadro a quadro é < 1 pixel
    JANELA_S, REPETE_S, AVISO_S = 6.0, 3.0, 4.0
    LIMITE_PX = 6  # deslizamento horizontal total na janela
    SUBIU_PX = 15  # saldo vertical que indica escalada (ou descida) de verdade

    def __init__(self, dt=QUADRO_MS / 1000):
        self.medidas = int(self.JANELA_S / dt) // self.PASSO
        self.medidas_aviso = int(self.AVISO_S / dt) // self.PASSO
        self.repete = int(self.REPETE_S / dt)
        self.reiniciar()

    def reiniciar(self):
        self._quadro, self._anterior = 0, None
        self._dx, self._dy, self._lados = [], [], []
        self._espera = self._espera_aviso = 0
        self.lado = None  # "Esquerda" ou "Direita": para onde ela estava forçando
        self.encostada = False  # aviso de 4 s; quem usar desliga

    @staticmethod
    def _forcando(lados):
        if not len(lados):
            return 0.0, None
        dir_, esq = (lados == 1).mean(), (lados == -1).mean()
        return max(dir_, esq), "Direita" if dir_ >= esq else "Esquerda"

    def passo(self, reduzida, esquerda, direita, hud_visivel):
        """`esquerda`/`direita`: se a tecla está apertada neste quadro."""
        if not hud_visivel:
            self.reiniciar()
            return []
        self._lados.append(1 if direita else -1 if esquerda else 0)
        self._lados = self._lados[-self.medidas * self.PASSO :]
        self._espera = max(0, self._espera - 1)
        self._espera_aviso = max(0, self._espera_aviso - 1)
        self._quadro += 1
        if self._quadro % self.PASSO:
            return []
        if self._anterior is not None:
            dx, dy = deslizamento(self._anterior, reduzida)
            self._dx.append(abs(dx))
            self._dy.append(dy)  # com sinal: subir e descer se anulam
            self._dx, self._dy = self._dx[-self.medidas :], self._dy[-self.medidas :]
        self._anterior = reduzida
        lados = np.array(self._lados)
        recentes = lados[-self.medidas_aviso * self.PASSO :]
        forcando, lado = self._forcando(recentes)
        if (len(self._dx) >= self.medidas_aviso and forcando >= 0.7 and not self._espera_aviso
                and sum(self._dx[-self.medidas_aviso :]) <= self.LIMITE_PX
                and abs(sum(self._dy[-self.medidas_aviso :])) <= self.SUBIU_PX * self.AVISO_S / self.JANELA_S):
            self.lado, self.encostada = lado, True
            self._espera_aviso = self.repete
        forcando, lado = self._forcando(lados)
        if len(self._dx) < self.medidas or forcando < 0.7 or self._espera:
            return []
        if sum(self._dx) > self.LIMITE_PX or abs(sum(self._dy)) > self.SUBIU_PX:
            return []
        self.lado = lado
        self._espera = self.repete
        return ["presa"]


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
