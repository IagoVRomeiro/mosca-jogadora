"""O cérebro da mosca no painel: os neurônios desenhados, o que eles disparam e as
ações que saem dele (`passo(imagem) -> (disparos, ações)`).

É o cérebro real (dados do preparar_conectoma.py): neurônios do FlyWire nas
posições de verdade, lobos ópticos vendo o jogo, os grupos da rede do conectoma
acendendo, zonas de comando nos neurônios descendentes e a dopamina nos PAM/PPL1.
"""

import collections

import numpy as np

from .conectoma import carregar_conectoma
from .config import ACOES, DURACAO_PULSO_S, PASTA, QUADRO_MS
from .olho import ATRASO_OLHO, GRADE_OLHO, _N_PERIFERIA, entrada, lembrar, reduzir, retrato


class FormaReal:
    """Neurônios reais do desenho, em coordenadas do painel (x de -1,45 a 1,45)."""

    CAMADAS = ("visual", "central", "descendente")

    def __init__(self, conectoma):
        pos = conectoma["desenho_posicao"]
        x0, x1 = np.percentile(pos[:, 0], [0.5, 99.5])
        y0, y1 = np.percentile(pos[:, 1], [0.5, 99.5])
        escala = 2.9 / (x1 - x0)
        # FlyWire: y cresce para baixo (ventral); no painel, y cresce para cima
        self.posicoes = np.column_stack(
            [(pos[:, 0] - (x0 + x1) / 2) * escala, -(pos[:, 1] - (y0 + y1) / 2) * escala]
        ).astype(np.float32)
        self.fundo = self._fundo((x0 + x1) / 2, (y0 + y1) / 2, escala)
        self.classe = conectoma["desenho_classe"]
        self.tipo = conectoma["desenho_tipo"]
        self.grupo = {k: conectoma[f"desenho_grupo_{k}"] for k in self.CAMADAS}
        self.nomes_grupos = {k: conectoma[f"grupos_{k}"] for k in self.CAMADAS}

    @staticmethod
    def _fundo(cx, cy, escala):
        """Silhueta (preparar_conectoma.py --fundo) nas coordenadas do painel:
        (densidade[x, y] de baixo para cima, (x0, y0, largura, altura)), ou None."""
        arquivo = PASTA / "dados_conectoma" / "fundo_cerebro.npz"
        if not arquivo.exists():
            return None
        with np.load(arquivo) as f:
            densidade, (x0, x1), (y0, y1) = f["densidade"], f["x"], f["y"]
        # no FlyWire y cresce para baixo: inverte as linhas para o dorsal ficar em cima
        return densidade[:, ::-1], ((x0 - cx) * escala, -(y1 - cy) * escala, (x1 - x0) * escala, (y1 - y0) * escala)


class CerebroDemo:
    """Rede de taxa de disparo sobre os neurônios desenhados.

    - Lobos ópticos: cada neurônio "olha" para um pedaço da imagem do jogo
      (retinotopia) e dispara com o movimento ali.
    - Zonas de comando (uma por ação): recebem o que você pintar/pulsar no
      painel e, de olho no jogo, regras fixas (sem treino) ou o modelo treinado.
      A taxa média de cada zona vira a ação.
    - Com o modelo do conectoma, cada neurônio real acende com a atividade do
      seu grupo na rede.
    """

    # Neurônios de dopamina do corpo de cogumelo: na mosca real, os PAM sinalizam
    # recompensa e os PPL1, punição. Piscam com os eventos do jogo (HUD).
    DURACAO_DOPAMINA_S = 0.6
    GRADE = (GRADE_OLHO[0], GRADE_OLHO[1] // 2)  # resolução do olho em cada metade
    ESPONTANEA = 0.3  # Hz
    GRUPOS_POR_ACAO = 10  # grupos descendentes reais (de 1 ou 2 neurônios) por zona de comando
    ATIVIDADE_HZ = 60  # taxa de um grupo no máximo de atividade

    def __init__(self, dt=QUADRO_MS / 1000, modelo=None):
        self.dt = dt
        self.rng = np.random.default_rng(0)
        self.real = FormaReal(carregar_conectoma())
        self.posicoes = self.real.posicoes
        classe, tipo = self.real.classe, self.real.tipo
        optico = (classe == "optic") | (classe == "visual_projection")
        self.dopamina = {
            "PAM": np.flatnonzero(np.char.startswith(tipo, "PAM")),
            "PPL1": np.flatnonzero(np.char.startswith(tipo, "PPL1")),
        }
        self.n = len(self.posicoes)
        x, y = self.posicoes.T
        self.optico_esq = np.flatnonzero(optico & (x < 0))
        self.optico_dir = np.flatnonzero(optico & (x >= 0))

        # Retinotopia: posição no lobo -> célula da grade na metade da imagem
        linhas, colunas = self.GRADE
        lobo = np.concatenate([self.optico_esq, self.optico_dir])
        y0, y1 = np.percentile(y[lobo], [2, 98])
        ax0, ax1 = np.percentile(np.abs(x[lobo]), [2, 98])
        lin = np.clip(((y1 - y) / (y1 - y0) * linhas).astype(int), 0, linhas - 1)
        col_ext = np.clip(((np.abs(x) - ax0) / (ax1 - ax0) * colunas).astype(int), 0, colunas - 1)
        col = np.where(x < 0, colunas - 1 - col_ext, colunas + col_ext)  # borda = periferia
        self.celula = lin * (2 * colunas) + col

        self._escala = {k: 1e-3 for k in FormaReal.CAMADAS}
        self.versao_zonas = 0
        self._modelo = None
        self.modelo = modelo  # monta as zonas de comando
        self.reiniciar()

    # --- zonas de comando ---

    @property
    def modelo(self):
        return self._modelo

    @modelo.setter
    def modelo(self, modelo):
        """Trocar o cérebro treinado muda quem são os neurônios de cada zona."""
        self._modelo = modelo
        self._ligado_ao_conectoma = (
            modelo is not None
            and getattr(modelo, "arquitetura", "mlp") == "conectoma"
            and all(np.array_equal(modelo.grupos[k], self.real.nomes_grupos[k]) for k in FormaReal.CAMADAS)
        )
        self.zona = self._zonas_de_comando()
        self._em_zona = np.zeros(self.n, bool)
        for idx in self.zona.values():
            self._em_zona[idx] = True
        self.versao_zonas += 1

    def _zonas_de_comando(self):
        grupo_d = self.real.grupo["descendente"]
        if self._ligado_ao_conectoma:
            # Os descendentes reais que mais empurram cada tecla na rede treinada;
            # cada grupo vai para uma tecla só (rodadas: cada tecla pega o seu melhor)
            leitura = self._modelo.rede.p["R"]  # descendentes x teclas
            no_desenho = np.isin(np.arange(leitura.shape[0]), grupo_d)
            livres, zonas = no_desenho.copy(), {a: [] for a in ACOES}
            for _ in range(self.GRUPOS_POR_ACAO):
                for acao in ACOES:
                    if acao in self._modelo.acoes:
                        candidatos = np.where(livres, leitura[:, self._modelo.acoes.index(acao)], -np.inf)
                    else:  # tecla que o modelo não conhece (ex.: uma ação nova): grupos livres
                        candidatos = np.where(livres, 0.0, -np.inf)
                    g = int(np.argmax(candidatos))
                    zonas[acao].append(g)
                    livres[g] = False
            return {a: np.flatnonzero(np.isin(grupo_d, gs)) for a, gs in zonas.items()}
        # Sem o modelo do conectoma: os descendentes divididos em regiões (ilustrativo)
        dn = np.flatnonzero(grupo_d >= 0)
        pos = self.posicoes[dn]
        centros = pos[np.linspace(0, len(dn) - 1, len(ACOES)).astype(int)]
        for _ in range(20):  # k-médias
            perto = np.argmin(((pos[:, None] - centros[None]) ** 2).sum(-1), axis=1)
            centros = np.array([pos[perto == k].mean(0) if (perto == k).any() else centros[k]
                                for k in range(len(ACOES))])
        ordem = np.argsort(centros[:, 0])  # da esquerda para a direita
        return {acao: dn[perto == ordem[i]] for i, acao in enumerate(ACOES)}

    def centro(self, indices):
        """Onde escrever o rótulo de uma zona (centro dos seus neurônios)."""
        return self.posicoes[indices].mean(axis=0) if len(indices) else np.zeros(2)

    def reiniciar(self):
        self.taxas = np.full(self.n, self.ESPONTANEA)  # Hz
        self.selecao = np.zeros(self.n, dtype=bool)
        self.pulso_selecao_ate = 0.0
        self.pulso_zona_ate = {nome: 0.0 for nome in self.zona}
        self.dopamina_ate = {nome: 0.0 for nome in self.dopamina}
        self.disparos = np.array([], dtype=int)
        self.reduzida = None  # última tela vista, em OLHO (o gravador reaproveita)
        self.retratos = collections.deque(maxlen=ATRASO_OLHO + 1)  # memória curta do olho
        self.memoria = None  # memória dos últimos segundos (olho versão 3)
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

    def pulsar_zona(self, nome, duracao=DURACAO_PULSO_S):
        self.pulso_zona_ate[nome] = self.t + duracao

    def recompensa(self, valor):
        """Evento do jogo: positivo acende os PAM, negativo os PPL1."""
        if valor:
            self.dopamina_ate["PAM" if valor > 0 else "PPL1"] = self.t + self.DURACAO_DOPAMINA_S

    def estimulados(self):
        mask = self.selecao.copy() if self.t < self.pulso_selecao_ate else np.zeros(self.n, bool)
        for nome, ate in self.pulso_zona_ate.items():
            if self.t < ate:
                mask[self.zona[nome]] = True
        return mask

    # --- simulação ---

    def _acender_grupos(self, alvo, atividades):
        """Cada neurônio real acende com a atividade do seu grupo na rede (fora
        das zonas de comando, que seguem as teclas)."""
        for camada in FormaReal.CAMADAS:
            a = atividades[camada]
            self._escala[camada] = max(0.98 * self._escala[camada], float(a.max()), 1e-3)
            g = self.real.grupo[camada]
            sel = (g >= 0) & ~self._em_zona
            alvo[sel] += self.ATIVIDADE_HZ * a[g[sel]] / self._escala[camada]

    def passo(self, imagem):
        """Recebe a imagem do jogo; devolve (índices que dispararam, ações 0..1)."""
        self.t += self.dt
        reduzida = reduzir(imagem)
        if self.reduzida is not None and self.reduzida.shape != reduzida.shape:
            self.reduzida = None
        atual = retrato(reduzida, self.reduzida)
        self.reduzida = reduzida
        self.retratos.append(atual)
        self.memoria = lembrar(self.memoria, atual)
        movimento = atual[_N_PERIFERIA // 2 : _N_PERIFERIA]  # movimento da periferia
        self.movimento_medio = float(movimento.mean())  # o detector de parada usa

        alvo = np.full(self.n, self.ESPONTANEA)
        optico = np.concatenate([self.optico_esq, self.optico_dir])
        alvo[optico] += 150 * movimento[self.celula[optico]]
        if self.modelo is not None:
            # O modelo treinado decide quanto cada zona de comando recebe
            x = entrada(self.modelo.versao_olho, atual, self.retratos[0], self.memoria)
            atividades = self.modelo.atividades(x)
            for nome, p in zip(self.modelo.acoes, atividades["prob"]):
                if nome in self.zona:
                    alvo[self.zona[nome]] += 40 * p
            if self._ligado_ao_conectoma:
                self._acender_grupos(alvo, atividades)
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
            nome: float(np.clip((self.taxas[idx].mean() - self.ESPONTANEA) / 40, 0, 1)) if len(idx) else 0.0
            for nome, idx in self.zona.items()
        }
        return self.disparos, acoes
