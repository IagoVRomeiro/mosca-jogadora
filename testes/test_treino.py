"""Treino: pesos pela recompensa, fases de ataque, olho e as redes que aprendem."""

import unittest

import numpy as np

import treinar
from mosca.aprendizado import Imitacao
from mosca.conectoma import ARQUIVO_CONECTOMA
from mosca.config import ACOES
from mosca.jogo import JogoDemo
from mosca.olho import ATRASO_OLHO, entrada, reduzir, retrato, tamanho_entrada


class TestePesos(unittest.TestCase):
    def test_dano_enfraquece_o_que_veio_antes_e_geo_reforca(self):
        r = np.zeros(300, np.float32)
        r[100], r[200] = -1.0, 0.5
        w = treinar.pesos_por_recompensa(r)
        self.assertLess(w[95], 0.5)  # logo antes do dano: "não copie"
        self.assertGreater(w[195], 1.5)  # logo antes do geo: "copie"
        self.assertAlmostEqual(float(w.mean()), 1.0, places=5)

    def test_fases_de_ataque(self):
        y = np.zeros((40, len(ACOES)), np.float32)
        j = ACOES.index("Atacar")
        y[10, j] = 1  # um toque
        fases = treinar.fases_de_toque(y)
        self.assertEqual(int(fases[:, j].sum()), 9)  # 0,3 s a 30 quadros/s
        self.assertEqual(fases[10, j], 1)
        self.assertEqual(fases[9, j], 0)
        np.testing.assert_array_equal(fases[:, ACOES.index("Esquerda")], 0)  # andar não muda


class TesteOlho(unittest.TestCase):
    def test_tamanhos(self):
        jogo = JogoDemo()
        a, b = reduzir(jogo.quadro()), reduzir(jogo.quadro())
        r = retrato(b, a)
        self.assertEqual(entrada(1, r, r).shape[0], tamanho_entrada(1))
        self.assertEqual(entrada(2, r, r).shape[0], tamanho_entrada(2))
        self.assertEqual(entrada(2, np.stack([r, r]), np.stack([r, r])).shape, (2, tamanho_entrada(2)))

    def test_passado_nao_atravessa_sessoes(self):
        sessoes = [
            ("a", np.zeros((10, 2016), np.float32), np.zeros((10, len(ACOES)), np.float32), np.ones(10)),
            ("b", np.ones((10, 2016), np.float32), np.zeros((10, len(ACOES)), np.float32), np.ones(10)),
        ]
        dados = treinar.Dados(sessoes)
        self.assertEqual(dados.passado[10], 10)  # 1º quadro da sessão b olha para ele mesmo
        self.assertEqual(dados.passado[19], 19 - ATRASO_OLHO)


def dados_do_jogo_demo():
    """No jogo demo, o "jogador" anda para a direita quando o boneco está à esquerda."""
    jogo = JogoDemo()
    retratos, teclas, anterior = [], [], None
    for i in range(900):
        tela = reduzir(jogo.quadro())
        retratos.append(retrato(tela, anterior))
        anterior = tela
        y = np.zeros(len(ACOES), np.float32)
        y[ACOES.index("Direita")] = jogo.x < 240
        y[ACOES.index("Esquerda")] = jogo.x >= 240
        teclas.append(y)
        acoes = {a: 0.0 for a in ACOES}
        acoes["Direita" if (i // 70) % 2 == 0 else "Esquerda"] = 1.0
        jogo.passo(acoes)
    dados = treinar.Dados([("demo", np.stack(retratos), np.stack(teclas), np.ones(900, np.float32))])
    dados.normalizar()
    return dados


class TesteAprende(unittest.TestCase):
    def aprende(self, arquitetura, epocas, extras=None):
        dados = dados_do_jogo_demo()
        antes = treinar.EPOCAS, treinar.EPOCAS_CONECTOMA
        treinar.EPOCAS = treinar.EPOCAS_CONECTOMA = epocas
        try:
            rede, _ = treinar.treinar(dados, arquitetura)
        finally:
            treinar.EPOCAS, treinar.EPOCAS_CONECTOMA = antes
        prev = treinar.prever(rede, dados, dados.valid) > 0.5
        real = dados.teclas[dados.valid] > 0.5
        acerto = (prev[:, ACOES.index("Direita")] == real[:, ACOES.index("Direita")]).mean()
        self.assertGreater(acerto, 0.9)

        # e o modelo salvo é lido pelo painel do mesmo jeito
        modelo = Imitacao({
            **rede.para_salvar(), **(extras or {}), "media": dados.media, "desvio": dados.desvio,
            "acoes": np.array(ACOES), "n_quadros": 900, "versao_olho": 2, "arquitetura": arquitetura,
        })
        idx = dados.valid[:5]
        np.testing.assert_allclose(
            modelo.prever(entrada(2, dados.retratos[idx], dados.retratos[dados.passado[idx]])),
            rede.prever(dados.entrada(idx)), rtol=1e-4, atol=1e-5,
        )
        return modelo

    def test_rede_inventada_aprende_uma_regra_simples(self):
        self.aprende("mlp", 10)

    @unittest.skipUnless(ARQUIVO_CONECTOMA.exists(), "rode preparar_conectoma.py antes")
    def test_cerebro_do_conectoma_aprende_uma_regra_simples(self):
        conectoma = np.load(ARQUIVO_CONECTOMA)
        grupos = {f"grupos_{k}": conectoma[f"grupos_{k}"] for k in ("visual", "central", "descendente")}
        modelo = self.aprende("conectoma", 10, grupos)
        ativ = modelo.atividades(np.zeros(modelo.w1.shape[0], np.float32))
        self.assertEqual(len(ativ["descendente"]), len(grupos["grupos_descendente"]))


if __name__ == "__main__":
    unittest.main()
