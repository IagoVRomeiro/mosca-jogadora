"""Estatísticas por chefe: como uma gravação vira lutas."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from mosca.estatisticas import EVENTOS, e_luta, lutas_da_gravacao, resumo


def gravar(pasta, cenas, eventos):
    """Uma parte de gravação com a sala e os eventos de cada quadro."""
    nomes = sorted(set(cenas))
    np.savez(pasta / "parte_000.npz", teclas=np.zeros((len(cenas), 3)), jogo_cenas=np.array(nomes),
             jogo_cena=np.array([nomes.index(c) for c in cenas]), eventos_nomes=np.array(EVENTOS),
             eventos=np.array(eventos, np.int16))


def quadro(**ev):
    return [ev.get(e, 0) for e in EVENTOS]


class TesteEstatisticas(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp()) / "2026-10-21_150000"
        self.pasta.mkdir()

    def test_salas_que_nao_sao_luta(self):
        self.assertTrue(e_luta("GG_Gruz_Mother_V"))
        for sala in ("GG_Workshop", "GG_Atrium", "GG_Spa", "GG_Engine_Prime", "Crossroads_01", ""):
            self.assertFalse(e_luta(sala))

    def test_vitoria_derrota_e_luta_cortada(self):
        cenas = (["GG_Workshop"] * 10 + ["GG_Gruz_Mother"] * 60 + ["GG_Workshop"] * 10   # venceu
                 + ["GG_Gruz_Mother"] * 30 + ["GG_Workshop"] * 10                         # perdeu
                 + ["GG_Gruz_Mother"] * 20)                                                # cortada
        ev = [quadro() for _ in cenas]
        ev[20] = quadro(acerto=2, dano_chefe=50)
        ev[60] = quadro(chefe_derrotado=1, dano_chefe=50)
        ev[90] = quadro(dano=3)
        ev[112] = quadro(morte=1)  # a derrota chega na volta, já fora da arena
        gravar(self.pasta, cenas, ev)
        lutas = lutas_da_gravacao(self.pasta, "mosca")
        self.assertEqual([(x["venceu"], x["completa"]) for x in lutas], [(True, True), (False, True), (False, False)])
        self.assertEqual((lutas[0]["dano_chefe"], lutas[0]["segundos"]), (100, 2.0))
        r = resumo(lutas)
        self.assertEqual((r["lutas"], r["vitorias"], r["melhor_chefe"]), (2, 1, 100))
        self.assertAlmostEqual(r["dano"], 60.0)  # 3 danos em 3 s de lutas completas (2 s + 1 s)

    def test_dano_por_minuto(self):
        cenas = ["GG_Workshop"] + ["GG_Hornet_1"] * 60 + ["GG_Workshop"]
        ev = [quadro() for _ in cenas]
        ev[10] = quadro(dano=2)
        gravar(self.pasta, cenas, ev)
        r = resumo(lutas_da_gravacao(self.pasta, "voce"))
        self.assertAlmostEqual(r["dano"], 60.0)  # 2 danos em 2 s = 60 por minuto


if __name__ == "__main__":
    unittest.main()
