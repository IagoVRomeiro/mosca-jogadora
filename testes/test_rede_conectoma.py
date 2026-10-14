"""Rede com a fiação do conectoma: gradientes certos e a fiação real respeitada."""

import unittest

import numpy as np

from mosca.conectoma import CAMADAS_CONECTOMA, RedeConectoma


def conectoma_pequeno(rng, v=5, c=6, d=4):
    def fiacao(n, m):
        w = rng.normal(0, 1, (n, m)) * (rng.random((n, m)) < 0.5)
        return (w / np.maximum(np.abs(w).sum(0, keepdims=True), 1e-9)).astype(np.float32)
    return {
        "ligacoes_visual_central": fiacao(v, c), "ligacoes_central_central": fiacao(c, c),
        "ligacoes_central_descendente": fiacao(c, d), "ligacoes_visual_descendente": fiacao(v, d),
    }


def perda(rede, x, y):
    prob = np.clip(rede.prever(x), 1e-9, 1 - 1e-9)
    return float(-(y * np.log(prob) + (1 - y) * np.log(1 - prob)).sum())


class TesteRedeConectoma(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.rede = RedeConectoma.iniciar(7, 3, conectoma_pequeno(rng), rng)
        for k, v in self.rede.p.items():  # pesos em float64 para a conta numérica
            self.rede.p[k] = v.astype(np.float64) + (rng.normal(0, 0.1, v.shape) if k.startswith(("a", "b")) else 0)
        self.rede.m = {k: v.astype(np.float64) for k, v in self.rede.m.items()}
        self.x = rng.normal(0, 1, (4, 7))
        self.y = (rng.random((4, 3)) < 0.5).astype(float)

    def test_gradientes_batem_com_a_conta_numerica(self):
        f = self.rede.frente(self.x)
        g = self.rede.gradientes(f, f["prob"] - self.y)
        eps = 1e-6
        for k in ("A", "a", "bc", "bd", "R", "r", *(f"s_{c}" for c in CAMADAS_CONECTOMA)):
            p = self.rede.p[k]
            for idx in list(zip(*np.nonzero(np.ones_like(p))))[:6]:
                guardado = p[idx]
                p[idx] = guardado + eps
                mais = perda(self.rede, self.x, self.y)
                p[idx] = guardado - eps
                menos = perda(self.rede, self.x, self.y)
                p[idx] = guardado
                with self.subTest(parametro=k, posicao=idx):
                    self.assertAlmostEqual(g[k][idx], (mais - menos) / (2 * eps), places=5)

    def test_fiacao_real_nao_muda_sinal_nem_cria_ligacao(self):
        rng = np.random.default_rng(0)
        for k in CAMADAS_CONECTOMA:
            self.rede.p[f"s_{k}"] += rng.normal(0, 3, self.rede.p[f"s_{k}"].shape)
        self.rede.limitar()
        for k in CAMADAS_CONECTOMA:
            real, efetivo = self.rede.m[k], self.rede.pesos(k)
            np.testing.assert_array_equal(np.sign(efetivo), np.sign(real))
            np.testing.assert_array_equal(efetivo[real == 0], 0)

    def test_modelo_salvo_preve_igual(self):
        salvo = RedeConectoma(self.rede.para_salvar())
        np.testing.assert_allclose(salvo.prever(self.x), self.rede.prever(self.x), rtol=1e-6)


if __name__ == "__main__":
    unittest.main()
