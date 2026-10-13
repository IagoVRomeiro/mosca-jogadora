"""Medida de melhoria entre versões: positivo é sempre melhor."""

import unittest

from comparar import Versao, comparar_duas, melhoria_percentual, texto_melhoria


def versao(*partidas):
    v = Versao(1, "teste")
    v.partidas = [{"segundos": s, "recompensa_total": r} for s, r in partidas]
    return v


class TesteMelhoria(unittest.TestCase):
    def test_recompensa_negativa_que_sobe_e_melhoria(self):
        self.assertEqual(melhoria_percentual(-4, -2), 50)
        self.assertEqual(melhoria_percentual(-2, -4), -100)

    def test_cruzar_o_zero(self):
        self.assertEqual(melhoria_percentual(-1, 1), 200)

    def test_medidas_que_melhoram_caindo(self):
        self.assertEqual(melhoria_percentual(2, 1, maior_melhor=False), 50)  # mortes 2 -> 1
        self.assertEqual(melhoria_percentual(1, 2, maior_melhor=False), -100)

    def test_antes_zero_nao_tem_porcentagem(self):
        self.assertIsNone(melhoria_percentual(0, 1))

    def test_uma_partida_nao_tem_incerteza(self):
        _, _, pct, inc = comparar_duas(versao((60, -4)), versao((60, -2)), "recompensa_total", True)
        self.assertEqual(pct, 50)
        self.assertIsNone(inc)
        self.assertIn("desconhecida", texto_melhoria(pct, inc))

    def test_partidas_muito_variaveis_podem_ser_sorte(self):
        x = versao((60, -10), (60, 2))  # média -4/min, muito variável
        y = versao((60, -8), (60, 4))  # média -2/min
        _, _, pct, inc = comparar_duas(x, y, "recompensa_total", True)
        self.assertEqual(pct, 50)
        self.assertIn("pode ser sorte", texto_melhoria(pct, inc))

    def test_partidas_consistentes_nao_sao_sorte(self):
        x = versao((60, -4.1), (60, -3.9), (60, -4.0))
        y = versao((60, -2.1), (60, -1.9), (60, -2.0))
        _, _, pct, inc = comparar_duas(x, y, "recompensa_total", True)
        self.assertNotIn("sorte", texto_melhoria(pct, inc))


if __name__ == "__main__":
    unittest.main()
