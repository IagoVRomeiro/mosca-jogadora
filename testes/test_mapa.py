"""Leitura do mapa pela Bússola, fila de treino durante a disputa e revezamento."""

import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

from mosca.estimulos import LeitorMapa
from mosca.orquestrador import Orquestrador

ALTURA, LARGURA = 523, 956
MARCA = np.load(LeitorMapa.MODELO)


def mapa(x, y, titulo=1, marca=True):
    """Tela do mapa aberto: fundo escuro, linhas, título e a marca da Bússola em (x, y)."""
    rng = np.random.default_rng(0)
    img = rng.integers(10, 40, (ALTURA, LARGURA)).astype(np.float32)
    img[150:160, 100:850] = 150  # um corredor do mapa
    t = np.random.default_rng(titulo).random((14, 160)) > 0.6
    img[40:54, 400:560][t] = 230  # o título da área (cada área, um desenho)
    if marca:
        h, w = MARCA.shape
        img[y - h // 2 : y - h // 2 + h, x - w // 2 : x - w // 2 + w] = MARCA
    return np.repeat(img.astype(np.uint8)[:, :, None], 3, axis=2)


class TesteMapa(unittest.TestCase):
    def setUp(self):
        self.leitor = LeitorMapa(Path(tempfile.mkdtemp()) / "mapa.npz")

    def test_acha_a_marca(self):
        x, y, s = self.leitor.achar_marca(mapa(437, 198))
        self.assertEqual((x, y), (437, 198))
        self.assertGreater(s, 0.95)

    def test_sem_marca_nao_le(self):
        self.assertIsNone(self.leitor.achar_marca(mapa(437, 198, marca=False)))
        self.assertEqual(self.leitor.ler(mapa(437, 198, marca=False)), [])

    def test_lugar_novo_so_uma_vez(self):
        self.assertEqual(self.leitor.ler(mapa(437, 198)), ["mapa_novo"])
        self.assertEqual(self.leitor.ler(mapa(440, 200)), [])  # mesma célula
        self.assertEqual(self.leitor.ler(mapa(600, 300)), ["mapa_novo"])

    def test_areas_diferentes_pelo_titulo(self):
        self.leitor.ler(mapa(437, 198, titulo=1))
        self.leitor.ler(mapa(437, 198, titulo=2))  # mesma posição, outra área
        self.assertEqual(len(self.leitor.titulos), 2)
        self.assertEqual(len(self.leitor.celulas), 2)

    def test_memoria_vale_entre_sessoes(self):
        self.leitor.ler(mapa(437, 198))
        de_novo = LeitorMapa(self.leitor.arquivo)
        self.assertEqual(de_novo.ler(mapa(437, 198)), [])


class TesteTorneioETreino(unittest.TestCase):
    def orq(self, campea="mlp", ultima=None, em_disputa=False):
        o = types.SimpleNamespace(
            modelos={"campea": types.SimpleNamespace(arquitetura=campea)},
            torneio=types.SimpleNamespace(estado={"ultima_arquitetura": ultima}, em_disputa=em_disputa),
            _treino_pendente=False, treinos=[], avisos=[],
        )
        o.treinar = lambda: o.treinos.append(1)
        o._avisar = lambda texto, s: o.avisos.append(texto)
        return o

    def test_reveza_arquiteturas(self):
        f = Orquestrador._arquitetura_do_treino
        self.assertEqual(f(self.orq("mlp", None)), "mlp")
        self.assertEqual(f(self.orq("mlp", "mlp")), "conectoma")  # depois de uma igual à campeã
        self.assertEqual(f(self.orq("mlp", "conectoma")), "mlp")
        self.assertEqual(f(self.orq("conectoma", "conectoma")), "mlp")

    def test_treino_espera_a_disputa_terminar(self):
        o = self.orq(em_disputa=True)
        Orquestrador._pedir_treino(o)
        self.assertEqual(o.treinos, [])
        self.assertTrue(o._treino_pendente)
        o = self.orq(em_disputa=False)
        Orquestrador._pedir_treino(o)
        self.assertEqual(o.treinos, [1])


if __name__ == "__main__":
    unittest.main()
