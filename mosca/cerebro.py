"""O cérebro da mosca. Hoje: regiões inventadas + a rede de imitação aprendida.
É aqui que o conectoma de verdade (Drosophila_brain_model) vai entrar, mantendo
o mesmo método `passo(imagem) -> (disparos, ações)`."""

import collections

import numpy as np

from .config import ACOES_JOGO, DURACAO_PULSO_S, QUADRO_MS
from .olho import ATRASO_OLHO, GRADE_OLHO, _N_PERIFERIA, entrada, reduzir, retrato


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
