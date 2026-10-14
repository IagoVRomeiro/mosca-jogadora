"""Gravações com a contagem de eventos e o estado do jogo: o treino reajusta exato."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import treinar
from mosca.aprendizado import Gravador
from mosca.config import ACOES
from mosca.estimulos import LeitorHUD


def estado(**mudancas):
    e = {"cena": "Fungus2_13", "x": 10.0, "y": 5.0, "vx": 0.0, "vy": 0.0, "vida": 5, "vida_max": 5,
         "vida_azul": 0, "geo": 100, "alma": 0, "golpes": 0, "inimigos_mortos": 0, "morta": False,
         "no_chao": True, "na_parede": False, "curando": False}
    e.update(mudancas)
    return e


def gravar(pasta, quadros):
    """`quadros`: lista de (recompensa, eventos, estado do jogo ou None)."""
    g = Gravador(pasta)
    rng = np.random.default_rng(0)
    for recompensa, eventos, jogo in quadros:
        tela = rng.integers(0, 255, (90, 160, 3), dtype=np.uint8)
        g.adicionar(tela, np.zeros(len(ACOES), bool), recompensa, 5, eventos, jogo)
    g.parar()
    return g.pasta


class TesteGravacao(unittest.TestCase):
    def test_guarda_contagens_pesos_e_estado(self):
        pasta = gravar(Path(tempfile.mkdtemp()), [
            (0.0, [], estado()),
            (-4.0 + 0.3, ["dano", "dano", "acerto"], estado(vida=3, golpes=1, cena="Fungus2_14")),
            (0.0, [], None),  # plugin fora neste quadro
        ])
        with np.load(next(pasta.glob("parte_*.npz"))) as p:
            nomes = [str(n) for n in p["eventos_nomes"]]
            self.assertEqual(p["eventos"][1, nomes.index("dano")], 2)
            self.assertEqual(p["eventos"][1, nomes.index("acerto")], 1)
            self.assertAlmostEqual(float(p["valores"][nomes.index("dano")]), LeitorHUD.RECOMPENSA["dano"])
            np.testing.assert_array_equal(p["jogo_vida"][:2], [5, 3])
            self.assertTrue(np.isnan(p["jogo_vida"][2]))
            cenas = [str(c) for c in p["jogo_cenas"]]
            self.assertEqual([cenas[i] if i >= 0 else None for i in p["jogo_cena"]],
                             ["Fungus2_13", "Fungus2_14", None])

    def test_peso_mudou_depois_de_gravar(self):
        pasta = Path(tempfile.mkdtemp())
        antigos = dict(LeitorHUD.RECOMPENSA, dano=-1.0, inimigo_morto=1.0)
        with mock.patch.dict(LeitorHUD.RECOMPENSA, antigos):
            sessao = gravar(pasta, [(0.0, [], estado())] * 10
                            + [(-1.0, ["dano"], estado(vida=4)), (1.0, ["inimigo_morto"], estado())]
                            + [(0.0, [], estado())] * 10)
        atuais = dict(LeitorHUD.RECOMPENSA, dano=-2.5, inimigo_morto=1.5)
        with mock.patch.dict(LeitorHUD.RECOMPENSA, atuais), \
             mock.patch.object(treinar, "PASTA_CACHE", Path(tempfile.mkdtemp())):
            d = treinar.processar_sessao(sessao)
        self.assertAlmostEqual(float(d["hud"][10]), -2.5, places=5)
        self.assertAlmostEqual(float(d["hud"][11]), 1.5, places=5)
        self.assertAlmostEqual(float(np.abs(d["hud"]).sum()), 4.0, places=5)  # nada mais mudou


if __name__ == "__main__":
    unittest.main()
