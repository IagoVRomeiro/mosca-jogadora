"""Leitor do HUD e detector de parada, com telas desenhadas de propósito."""

import unittest

import numpy as np

from mosca.estimulos import DetectorParada, LeitorHUD

ALTURA, LARGURA = 523, 956  # o que a captura entrega com o jogo em 1920x1080


def tela(mascaras, hud=True):
    """Tela preta com o HUD: `mascaras` cheias e o contorno do vaso de alma."""
    img = np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8)
    if not hud:
        return img
    h = ALTURA
    for i in range(mascaras):
        x = int((LeitorHUD.MASCARA_X0 + i * LeitorHUD.MASCARA_PASSO) * h)
        y = int(LeitorHUD.MASCARA_Y * h)
        img[y - 4 : y + 5, x - 3 : x + 4] = 230
    cx, cy, r = LeitorHUD.ALMA
    img[int((cy - r * 0.9) * h) - 1 : int((cy - r * 0.9) * h) + 2, int(cx * h) - 2 : int(cx * h) + 3] = 200
    return img


def eventos(leitor, sequencia):
    """`sequencia`: lista de (tela, quadros). Devolve todos os eventos na ordem."""
    todos = []
    for img, quadros in sequencia:
        for _ in range(quadros):
            todos += leitor.passo(img)[1]
    return todos


class TesteHUD(unittest.TestCase):
    def test_le_as_mascaras(self):
        leitor = LeitorHUD()
        eventos(leitor, [(tela(5), 5)])
        self.assertEqual(leitor.vida, 5)
        self.assertTrue(leitor.visivel)

    def test_dano(self):
        self.assertEqual(eventos(LeitorHUD(), [(tela(5), 5), (tela(4), 5)]), ["dano"])

    def test_cura(self):
        self.assertEqual(eventos(LeitorHUD(), [(tela(3), 5), (tela(4), 5)]), ["cura"])

    def test_morte_com_mascaras_zeradas_e_renascer_nao_e_cura(self):
        e = eventos(LeitorHUD(), [(tela(1), 5), (tela(0), 5), (tela(0, hud=False), 60), (tela(5), 10)])
        self.assertEqual(e, ["morte"])

    def test_morte_quando_o_hud_some_com_uma_mascara(self):
        e = eventos(LeitorHUD(), [(tela(1), 5), (tela(0, hud=False), 40), (tela(5), 10)])
        self.assertEqual(e, ["morte"])

    def test_menu_nao_e_morte_nem_dano(self):
        e = eventos(LeitorHUD(), [(tela(3), 5), (tela(0, hud=False), 90), (tela(3), 10)])
        self.assertEqual(e, [])

    def test_piscada_nao_conta(self):
        # um quadro só com 4 máscaras no meio de 5: não é dano
        self.assertEqual(eventos(LeitorHUD(), [(tela(5), 5), (tela(4), 1), (tela(5), 5)]), [])

    def test_recompensas(self):
        r = LeitorHUD.RECOMPENSA
        self.assertLess(r["morte"], r["dano"])  # morrer é pior que apanhar
        self.assertLess(r["dano"], r["parada"])
        self.assertGreater(r["acerto"], 0)


class TesteParada(unittest.TestCase):
    def test_parada_depois_de_alguns_segundos(self):
        d = DetectorParada()
        quadros = [i for i in range(300) if d.passo(0.0, True, False)]
        self.assertTrue(quadros)
        self.assertLess(quadros[0] / 30, 7)  # ~3 s para notar + 3 s de espera

    def test_andando_nao_e_parada(self):
        d = DetectorParada()
        self.assertFalse(any(d.passo(0.2, True, False) for _ in range(300)))

    def test_curando_nao_e_parada(self):
        d = DetectorParada()
        self.assertFalse(any(d.passo(0.0, True, True) for _ in range(300)))

    def test_menu_nao_e_parada(self):
        d = DetectorParada()
        self.assertFalse(any(d.passo(0.0, False, False) for _ in range(300)))


if __name__ == "__main__":
    unittest.main()
