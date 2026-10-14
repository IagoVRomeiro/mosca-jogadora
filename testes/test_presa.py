"""Presa: apertando para andar e a câmera não sai do lugar na horizontal."""

import unittest

import numpy as np

from mosca.estimulos import DetectorPresa, deslizamento


def cenario(largura=400):
    rng = np.random.default_rng(0)
    blocos = rng.integers(10, 220, (30, largura // 5))
    return np.repeat(np.repeat(blocos, 5, 0), 5, 1).astype(np.uint8)  # 150 x largura


FUNDO = cenario()


def vista(x, y=0):
    """O que a câmera vê (90 x 160) com o canto em (x, y) do cenário."""
    return FUNDO[30 + y : 120 + y, x : x + 160]




class TestePresa(unittest.TestCase):
    def test_deslizamento(self):
        self.assertEqual(deslizamento(vista(50), vista(56)), (6, 0))
        self.assertEqual(deslizamento(vista(50), vista(44))[0], -6)

    def test_contra_a_parede(self):
        d = DetectorPresa()
        eventos = [e for i in range(300) for e in d.passo(vista(100), False, True, True)]
        self.assertIn("presa", eventos)
        self.assertEqual(d.lado, "Direita")

    def test_pulando_onde_nao_alcanca(self):
        d = DetectorPresa()  # a câmera sobe e desce com o pulo, mas não anda para o lado
        alturas = [int(10 * abs(np.sin(i / 8))) for i in range(300)]
        eventos = [e for i, y in enumerate(alturas) for e in d.passo(vista(100, y), False, True, True)]
        self.assertIn("presa", eventos)

    def test_andando_nao_e_presa(self):
        d = DetectorPresa()
        eventos = [e for i in range(300) for e in d.passo(vista(i // 2), False, True, True)]
        self.assertEqual(eventos, [])

    def test_parada_sem_apertar_nao_e_presa(self):
        d = DetectorPresa()  # isso é "parada", outro detector
        eventos = [e for i in range(300) for e in d.passo(vista(100), False, False, True)]
        self.assertEqual(eventos, [])

    def test_repete_enquanto_continuar_presa(self):
        d = DetectorPresa()
        eventos = [e for i in range(30 * 15) for e in d.passo(vista(100), True, False, True)]
        self.assertGreaterEqual(eventos.count("presa"), 3)  # 6 s para notar, depois a cada 3 s
        self.assertEqual(d.lado, "Esquerda")


if __name__ == "__main__":
    unittest.main()
