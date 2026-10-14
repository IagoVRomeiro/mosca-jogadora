"""Presa: apertando para andar e a câmera não sai do lugar na horizontal."""

import unittest

import numpy as np

from mosca.estimulos import DetectorLoop, DetectorPresa, deslizamento


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

    def test_escalando_a_parede_nao_e_presa(self):
        d = DetectorPresa()  # forçando para a parede, mas a câmera sobe de verdade
        eventos = [e for i in range(300) for e in d.passo(vista(100, 30 - i // 5), False, True, True)]
        self.assertEqual(eventos, [])
        self.assertFalse(d.encostada)

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

    def test_avisa_encostada_antes_de_punir(self):
        d = DetectorPresa()  # com 4 s liga o aviso (reflexo), a punição só vem com 6 s
        aviso = presa = None
        for i in range(300):
            if d.passo(vista(100), False, True, True) and presa is None:
                presa = i
            if d.encostada and aviso is None:
                aviso = i
        self.assertIsNotNone(aviso)
        self.assertLess(aviso, presa)
        self.assertAlmostEqual(aviso / 30, DetectorPresa.AVISO_S, delta=0.7)

    def test_andando_nao_avisa(self):
        d = DetectorPresa()
        for i in range(300):
            d.passo(vista(i // 2), False, True, True)
        self.assertFalse(d.encostada)


class TesteLoop(unittest.TestCase):
    def indo_e_voltando(self, i):
        return 100 + int(30 * np.sin(i / 20))  # vai e volta ~60 px a cada ~4 s

    def test_indo_e_voltando_sem_nada_de_bom_e_loop(self):
        d = DetectorLoop()
        eventos = [e for i in range(30 * 25) for e in d.passo(vista(self.indo_e_voltando(i)), False, True)]
        self.assertIn("loop", eventos)

    def test_lutando_indo_e_voltando_nao_e_loop(self):
        d = DetectorLoop()  # acertos de vez em quando: está lutando, não em círculos
        eventos = [e for i in range(30 * 25)
                   for e in d.passo(vista(self.indo_e_voltando(i)), i % 120 == 0, True)]
        self.assertEqual(eventos, [])

    def test_andando_para_um_lado_nao_e_loop(self):
        d = DetectorLoop()
        eventos = [e for i in range(30 * 25) for e in d.passo(vista(i % 230), False, True)]
        self.assertEqual(eventos, [])

    def test_parada_nao_e_loop(self):
        d = DetectorLoop()  # parada tem detector próprio
        eventos = [e for i in range(30 * 25) for e in d.passo(vista(100), False, True)]
        self.assertEqual(eventos, [])


if __name__ == "__main__":
    unittest.main()
