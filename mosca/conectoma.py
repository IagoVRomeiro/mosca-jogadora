"""O cérebro com a fiação real da mosca (conectoma FlyWire v783), em grupos de neurônios.

    olho -> [aprendida] -> visual (654 grupos) -> [conectoma] -> central (1.500)
         -> [conectoma, 1 passo entre centrais] -> descendentes (932) -> [aprendida] -> teclas

Cada grupo é um tipo celular de um lado do cérebro, com a atividade média dos seus
neurônios. Nas camadas do conectoma, a fiação é fixa: só existem as ligações que
existem na mosca, cada uma com o seu sinal (excitatória ou inibitória) e o seu
peso relativo (número de sinapses). O treino só ajusta o ganho de cada grupo de
destino: peso = peso_real x exp(s[destino]), com s aprendido. Ajustar cada
ligação separada (245 mil) fazia a rede decorar os dados em vez de aprender.
Os dados vêm do preparar_conectoma.py.
"""

import numpy as np

from .config import PASTA

ARQUIVO_CONECTOMA = PASTA / "dados_conectoma" / "conectoma_mosca.npz"
CAMADAS_CONECTOMA = ("visual_central", "central_central", "central_descendente", "visual_descendente")
LIMITE_S = (-5.0, 3.0)  # ganho de cada grupo entre exp(-5) e exp(3) vezes o real
REGULARIZAR = {"A": 0.01, "R": 0.01}  # L2 nas camadas aprendidas (entrada e saída)


def carregar_conectoma():
    if not ARQUIVO_CONECTOMA.exists():
        raise FileNotFoundError(
            "Dados do conectoma não encontrados: rode .venv-flygym/bin/python preparar_conectoma.py"
        )
    with np.load(ARQUIVO_CONECTOMA) as d:
        return {k: d[k] for k in d.files}


class RedeConectoma:
    """Pesos, passo para frente (com o que o treino precisa para voltar) e gradientes.

    `pesos` traz os pesos efetivos (prontos para usar no painel). No treino,
    `iniciar` cria também os ganhos `s` e as ligações reais `m` de cada camada.
    """

    regularizar = REGULARIZAR

    def __init__(self, pesos):
        self.p = pesos

    @classmethod
    def iniciar(cls, n_entrada, n_saida, conectoma, rng):
        m = {k: conectoma[f"ligacoes_{k}"].astype(np.float32) for k in CAMADAS_CONECTOMA}
        n_v, n_c = m["visual_central"].shape
        n_d = m["central_descendente"].shape[1]
        p = {
            "A": rng.normal(0, np.sqrt(2 / n_entrada), (n_entrada, n_v)).astype(np.float32),
            "a": np.zeros(n_v, np.float32),
            "bc": np.zeros(n_c, np.float32),
            "bd": np.zeros(n_d, np.float32),
            "R": rng.normal(0, np.sqrt(1 / n_d), (n_d, n_saida)).astype(np.float32),
            "r": np.zeros(n_saida, np.float32),
        }
        # Ganho inicial por camada: as ligações reais estão normalizadas (somam 1 em
        # módulo por destino); começar ~2x evita o sinal sumir de camada em camada
        for k in CAMADAS_CONECTOMA:
            p[f"s_{k}"] = np.full(m[k].shape[1], np.log(2.0), np.float32)
        rede = cls(p)
        rede.m = m
        return rede

    # --- pesos efetivos ---

    def pesos(self, k):
        """Peso efetivo da camada `k` do conectoma (real x ganho do destino)."""
        if k in self.p:  # modelo salvo: já vem pronto
            return self.p[k]
        return self.m[k] * np.exp(self.p[f"s_{k}"])[None, :]

    def treinaveis(self):
        return [k for k in self.p if not k.startswith(CAMADAS_CONECTOMA)]

    # --- passo para frente ---

    def frente(self, x):
        """Atividade de cada camada e a probabilidade de cada tecla."""
        p, w = self.p, {k: self.pesos(k) for k in CAMADAS_CONECTOMA}
        v = np.maximum(0, x @ p["A"] + p["a"])
        c1 = np.maximum(0, v @ w["visual_central"] + p["bc"])
        c2 = np.maximum(0, c1 + c1 @ w["central_central"])
        d = np.maximum(0, c2 @ w["central_descendente"] + v @ w["visual_descendente"] + p["bd"])
        z = d @ p["R"] + p["r"]
        prob = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        return {"x": x, "v": v, "c1": c1, "c2": c2, "d": d, "w": w, "prob": prob}

    def prever(self, x):
        return self.frente(x)["prob"]

    # --- gradientes (treino) ---

    def gradientes(self, f, dz):
        """`dz`: gradiente da perda na saída (antes do sigmoide)."""
        p, w = self.p, f["w"]
        g = {"R": f["d"].T @ dz, "r": dz.sum(0)}
        dd = (dz @ p["R"].T) * (f["d"] > 0)
        g["bd"] = dd.sum(0)
        dw = {"central_descendente": f["c2"].T @ dd, "visual_descendente": f["v"].T @ dd}
        dc2 = (dd @ w["central_descendente"].T) * (f["c2"] > 0)
        dw["central_central"] = f["c1"].T @ dc2
        dc1 = (dc2 + dc2 @ w["central_central"].T) * (f["c1"] > 0)
        dw["visual_central"] = f["v"].T @ dc1
        g["bc"] = dc1.sum(0)
        dv = (dc1 @ w["visual_central"].T + dd @ w["visual_descendente"].T) * (f["v"] > 0)
        g["A"], g["a"] = f["x"].T @ dv, dv.sum(0)
        for k in CAMADAS_CONECTOMA:  # peso = real x exp(s[destino]) => d/ds = soma(d/dpeso x peso)
            g[f"s_{k}"] = (dw[k] * w[k]).sum(axis=0)
        return g

    def limitar(self):
        for k in CAMADAS_CONECTOMA:
            np.clip(self.p[f"s_{k}"], *LIMITE_S, out=self.p[f"s_{k}"])

    def para_salvar(self):
        """Pesos efetivos (o painel não precisa das máscaras nem do conectoma)."""
        salvar = {k: v for k, v in self.p.items() if not k.startswith("s_")}
        for k in CAMADAS_CONECTOMA:
            salvar[k] = self.pesos(k).astype(np.float32)
        return salvar
