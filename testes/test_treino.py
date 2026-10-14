"""Treino: pesos pela recompensa, fases de ataque, olho e as redes que aprendem."""

import unittest

import numpy as np

import treinar
from mosca.aprendizado import Imitacao
from mosca.conectoma import ARQUIVO_CONECTOMA
from mosca.config import ACOES
from mosca.jogo import JogoDemo
from mosca.olho import (
    ATRASO_OLHO, VERSAO_OLHO, entrada, lembrar, memorias_da_sessao, reduzir, retrato, tamanho_entrada,
)


def sessao(retratos, teclas, recompensa, nome="s", da_mosca=False):
    return {"nome": nome, "retratos": retratos.astype(np.float16), "teclas": teclas,
            "recompensa": recompensa.astype(np.float32), "da_mosca": da_mosca}


class TestePesos(unittest.TestCase):
    def test_retorno_desconta_o_futuro(self):
        r = np.zeros(400, np.float32)
        r[300] = -1.0
        g = treinar.retornos(r)
        self.assertAlmostEqual(float(g[300]), -1.0)
        self.assertAlmostEqual(float(g[200]), -(treinar.DESCONTO ** 100), places=5)  # ~3 s antes: metade
        self.assertAlmostEqual(float(g[301]), 0.0)

    def test_vantagem_num_trecho_dificil(self):
        """Num trecho difícil tudo leva a dano, mas a melhor ação ali ainda ganha
        mais peso que a pior; num trecho fácil, idem."""
        rng = np.random.default_rng(0)
        n = 3600
        dificil = (np.arange(n) // 600) % 2 == 1  # alterna trechos de 20 s
        boa = rng.random(n) < 0.5
        retratos = rng.normal(0, 0.05, (n, 2016)).astype(np.float32)
        retratos[:, :100] += dificil[:, None] * 1.0  # o trecho difícil "parece" diferente
        recompensa = np.zeros(n, np.float32)
        recompensa[dificil] -= 0.05  # apanha o tempo todo
        recompensa[boa] += 0.3  # a ação boa ajuda (como um acerto), em qualquer trecho
        teclas = np.zeros((n, len(ACOES)), np.float32)
        dados = treinar.Dados([sessao(retratos, teclas, recompensa)])
        dados.normalizar()
        treinar.pesar_pela_vantagem(dados)
        idx = np.sort(dados.treino)
        w, d, b = dados.pesos[idx], dificil[idx], boa[idx]
        self.assertGreater(w[d & b].mean(), w[d & ~b].mean())  # difícil: boa > ruim
        self.assertGreater(w[d & b].mean(), 0.8)  # e não é jogada fora só por ser difícil
        self.assertGreater(w[~d & b].mean(), w[~d & ~b].mean())
        self.assertAlmostEqual(float(w.mean()), 1.0, places=4)

    def test_partidas_da_mosca_pesam_menos(self):
        n = 600
        zeros = np.zeros((n, 2016), np.float32)
        dados = treinar.Dados([
            sessao(zeros, np.zeros((n, len(ACOES)), np.float32), np.zeros(n)),
            sessao(zeros, np.zeros((n, len(ACOES)), np.float32), np.zeros(n), "mosca_x", True),
        ])
        dados.normalizar()
        treinar.pesar_pela_vantagem(dados)
        idx = np.sort(dados.treino)
        self.assertAlmostEqual(float(dados.pesos[idx][dados.sessao[idx] == 1].mean()), treinar.PESO_MOSCA, places=4)

    def test_fases_de_ataque(self):
        y = np.zeros((40, len(ACOES)), np.float32)
        j = ACOES.index("Atacar")
        y[10, j] = 1  # um toque
        fases = treinar.fases_de_toque(y)
        self.assertEqual(int(fases[:, j].sum()), 9)  # 0,3 s a 30 quadros/s
        self.assertEqual(fases[10, j], 1)
        self.assertEqual(fases[9, j], 0)
        np.testing.assert_array_equal(fases[:, ACOES.index("Esquerda")], 0)  # andar não muda


class Parte(dict):
    """Imita um .npz aberto: `files` e acesso por chave."""

    @property
    def files(self):
        return list(self)


class TesteDanoEMorte(unittest.TestCase):
    def test_gravacao_antiga_deduz_pelo_valor(self):
        # parada, dano, morte com o último dano, acerto, dano junto com acerto, presa marcada
        r = np.array([-0.2, -1.0, -4.0, 0.3, -0.7, -0.6], np.float32)
        parte = Parte(presas=np.array([0, 0, 0, 0, 0, 1], bool), valor_presa=np.float32(-0.6))
        treinar.ajustar_dano_e_morte(r, parte)
        d, m = treinar.RECOMPENSA_DANO, treinar.RECOMPENSA_MORTE
        np.testing.assert_allclose(r, [-0.2, d, d + m, 0.3, d + 0.3, -0.6], atol=1e-5)

    def test_piscada_da_vida_e_desfeita(self):
        # 1 máscara tremendo: lida 1 -> 2 -> 1 em 3 quadros (cura + dano falsos);
        # depois um dano de verdade (1 -> 0 ... fica)
        vidas = np.array([1, 1, 2, 2, 1, 1, 1, 1] + [1] * 40 + [0] * 5, np.int8)
        r = np.zeros(len(vidas), np.float32)
        r[2], r[4], r[48] = 0.3, -1.0, -1.0
        parte = Parte(vidas=vidas)
        desfeitos = treinar.tirar_piscadas_da_vida(r, parte)
        self.assertEqual(desfeitos, [2, 4])
        self.assertAlmostEqual(float(r[2]), 0.0, places=5)
        self.assertAlmostEqual(float(r[4]), 0.0, places=5)
        self.assertAlmostEqual(float(r[48]), -1.0, places=5)  # o dano de verdade fica

    def test_gravacao_nova_usa_as_marcas(self):
        r = np.array([-1.0, -0.2], np.float32)  # gravada com dano valendo -1
        parte = Parte(danos=np.array([1, 0], bool), mortes=np.array([0, 0], bool),
                      valor_dano=np.float32(-1.0), valor_morte=np.float32(-3.0))
        treinar.ajustar_dano_e_morte(r, parte)
        np.testing.assert_allclose(r, [treinar.RECOMPENSA_DANO, -0.2], atol=1e-5)


class TesteMain(unittest.TestCase):
    def test_nada_usado_depois_de_apagado(self):
        """O main apaga as sessões para liberar memória; usar depois quebrava o
        fim do treino (e deixava a desafiante sem número)."""
        import ast
        import inspect

        main = ast.parse(inspect.getsource(treinar.main))
        apagadas = {alvo.id: n.lineno for n in ast.walk(main) if isinstance(n, ast.Delete)
                    for alvo in n.targets}
        usos = [n.id for n in ast.walk(main)
                if isinstance(n, ast.Name) and n.lineno > apagadas.get(n.id, 10**9)]
        self.assertEqual(usos, [])


class TestePartirDaMelhor(unittest.TestCase):
    """A versão nova parte dos pesos da melhor: no começo responde igual a ela,
    mesmo com outra normalização e com entradas a mais (olho mais novo)."""

    def checar(self, arquitetura, criar):
        rng = np.random.default_rng(1)
        n_base, n_novo = 3024, 3316  # olho 2 -> olho 3 (as entradas da memória vêm depois)
        base_rede = criar(n_base)
        base = {**base_rede.para_salvar(), "media": rng.normal(0, 1, n_base).astype(np.float32),
                "desvio": rng.uniform(0.5, 2, n_base).astype(np.float32)}
        dados = type("D", (), {"media": rng.normal(0, 1, n_novo).astype(np.float32),
                               "desvio": rng.uniform(0.5, 2, n_novo).astype(np.float32)})()
        nova = criar(n_novo)
        self.assertTrue(treinar.partir_de(nova, base, arquitetura, dados))
        x = rng.normal(0, 1, (8, n_novo)).astype(np.float32)  # entradas cruas
        antes = base_rede.prever((x[:, :n_base] - base["media"]) / base["desvio"])
        depois = nova.prever((x - dados.media) / dados.desvio)
        np.testing.assert_allclose(depois, antes, rtol=1e-3, atol=1e-4)

    def test_rede_inventada(self):
        rng = np.random.default_rng(2)
        self.checar("mlp", lambda n: treinar.RedeMLP.iniciar(n, len(ACOES), rng))

    @unittest.skipUnless(ARQUIVO_CONECTOMA.exists(), "rode preparar_conectoma.py antes")
    def test_conectoma(self):
        rng = np.random.default_rng(3)
        conectoma = treinar.carregar_conectoma()
        self.checar("conectoma", lambda n: treinar.RedeConectoma.iniciar(n, len(ACOES), conectoma, rng))

    def test_acao_que_saiu_e_casada_pelo_nome(self):
        """A versão de partida tinha uma ação a mais (o Mapa): as outras saídas
        continuam as mesmas, cada uma na sua ação."""
        rng = np.random.default_rng(5)
        acoes_base = list(ACOES[:3]) + ["Mapa"] + list(ACOES[3:])
        base_rede = treinar.RedeMLP.iniciar(50, len(acoes_base), rng)
        base = {**base_rede.para_salvar(), "acoes": np.array(acoes_base),
                "media": np.zeros(50, np.float32), "desvio": np.ones(50, np.float32)}
        dados = type("D", (), {"media": np.zeros(50, np.float32), "desvio": np.ones(50, np.float32)})()
        nova = treinar.RedeMLP.iniciar(50, len(ACOES), rng)
        self.assertTrue(treinar.partir_de(nova, base, "mlp", dados))
        x = rng.normal(0, 1, (6, 50)).astype(np.float32)
        antes, depois = base_rede.prever(x), nova.prever(x)
        for i, acao in enumerate(ACOES):
            np.testing.assert_allclose(depois[:, i], antes[:, acoes_base.index(acao)], rtol=1e-4, atol=1e-5)

    def test_formato_diferente_comeca_do_zero(self):
        rng = np.random.default_rng(4)
        base = {**treinar.RedeMLP.iniciar(100, len(ACOES) + 1, rng).para_salvar(),
                "media": np.zeros(100, np.float32), "desvio": np.ones(100, np.float32)}
        dados = type("D", (), {"media": np.zeros(200, np.float32), "desvio": np.ones(200, np.float32)})()
        self.assertFalse(treinar.partir_de(treinar.RedeMLP.iniciar(200, len(ACOES), rng), base, "mlp", dados))


class TesteOlho(unittest.TestCase):
    def test_tamanhos(self):
        jogo = JogoDemo()
        a, b = reduzir(jogo.quadro()), reduzir(jogo.quadro())
        r = retrato(b, a)
        self.assertEqual(entrada(1, r, r).shape[0], tamanho_entrada(1))
        self.assertEqual(entrada(2, r, r).shape[0], tamanho_entrada(2))
        self.assertEqual(entrada(3, r, r, lembrar(None, r)).shape[0], tamanho_entrada(3))
        self.assertEqual(entrada(2, np.stack([r, r]), np.stack([r, r])).shape, (2, tamanho_entrada(2)))

    def test_memoria_igual_no_painel_e_no_treino(self):
        """O treino calcula a memória da sessão inteira de uma vez; o painel,
        quadro a quadro. Têm que dar o mesmo, senão a mosca joga com outra entrada."""
        rng = np.random.default_rng(0)
        retratos = rng.random((200, 2016)).astype(np.float32)
        lote = memorias_da_sessao(retratos)
        memoria = None
        for i, r in enumerate(retratos):
            memoria = lembrar(memoria, r)
            np.testing.assert_allclose(memoria, lote[i], rtol=1e-4, atol=1e-5)

    def test_memoria_esquece_devagar(self):
        claro, escuro = np.ones(2016, np.float32), np.zeros(2016, np.float32)
        lote = memorias_da_sessao(np.stack([claro] * 30 + [escuro] * 30))  # 1 s claro, 1 s escuro
        rapida, lenta = lote[-1, 0], lote[-1, 145]  # brilho de um bloco nas duas memórias
        self.assertAlmostEqual(float(rapida), np.exp(-1), delta=0.05)  # tau 1 s: lembra ~37%
        self.assertGreater(lenta, rapida)  # tau 4 s: lembra mais
        x = entrada(VERSAO_OLHO, escuro, escuro, lote[-1])
        self.assertGreater(x[-1], 0.5)  # "a cena mudou" em relação ao que lembra

    def test_passado_nao_atravessa_sessoes(self):
        y = np.zeros((10, len(ACOES)), np.float32)
        dados = treinar.Dados([sessao(np.zeros((10, 2016)), y, np.zeros(10), "a"),
                               sessao(np.ones((10, 2016)), y, np.zeros(10), "b")])
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
    dados = treinar.Dados([sessao(np.stack(retratos), np.stack(teclas), np.zeros(900), "demo")])
    dados.normalizar()
    return dados


class TesteAprende(unittest.TestCase):
    def aprende(self, arquitetura, epocas, extras=None):
        dados = dados_do_jogo_demo()
        antes = treinar.EPOCAS, treinar.EPOCAS_CONECTOMA
        treinar.EPOCAS = treinar.EPOCAS_CONECTOMA = epocas
        try:
            rede, _, aprendeu = treinar.treinar(dados, arquitetura)
            self.assertTrue(aprendeu)  # do zero, sempre
        finally:
            treinar.EPOCAS, treinar.EPOCAS_CONECTOMA = antes
        prev = treinar.prever(rede, dados, dados.valid) > 0.5
        real = dados.teclas[dados.valid] > 0.5
        acerto = (prev[:, ACOES.index("Direita")] == real[:, ACOES.index("Direita")]).mean()
        self.assertGreater(acerto, 0.9)

        # e o modelo salvo é lido pelo painel do mesmo jeito
        idx_valid = dados.valid
        modelo = Imitacao({
            **rede.para_salvar(), **(extras or {}), "media": dados.media, "desvio": dados.desvio,
            "acoes": np.array(ACOES), "n_quadros": 900, "versao_olho": VERSAO_OLHO, "arquitetura": arquitetura,
        })
        idx = dados.valid[:5]
        np.testing.assert_allclose(
            modelo.prever(entrada(VERSAO_OLHO, dados.retratos[idx], dados.retratos[dados.passado[idx]],
                                  dados.memoria[idx].astype(np.float32))),
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
