"""Especialistas por chefe: quando treinar, quem joga e o veredito do candidato."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from mosca.especialistas import Especialistas

ARENA = "GG_Gruz_Mother"


class TesteEspecialistas(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp()) / "especialistas"
        self.carregados = []
        self.e = Especialistas(self.pasta, carregar=lambda arq: self.carregados.append(arq) or f"modelo:{arq.name}")

    def criar(self, quem, treino_id):
        arquivo = self.e.arquivo(ARENA, quem)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        np.savez(arquivo, x=np.zeros(1))
        arquivo.with_suffix(".json").write_text(json.dumps({"treino_id": treino_id}))

    def lutar(self, quem, resultados):
        avisos = []
        for venceu in resultados:
            avisos += self.e.registrar_luta(ARENA, quem, venceu)
        return avisos

    def test_sem_especialista_joga_a_geral(self):
        self.assertEqual(self.e.modelo(ARENA), (None, None))
        self.assertIsNone(self.e.quem_joga(ARENA))

    def test_treina_depois_de_10_lutas(self):
        self.lutar("geral", [False] * 9)
        self.assertIsNone(self.e.precisa_treinar())
        self.lutar("geral", [True])
        self.assertEqual(self.e.precisa_treinar(), ARENA)
        self.criar("candidato", 80)  # treinou: há candidato, não treina de novo
        self.e.treinou(ARENA)
        self.assertIsNone(self.e.precisa_treinar())

    def test_candidato_joga_e_assume_se_vencer_pelo_menos_tanto(self):
        self.lutar("geral", [True] * 3 + [False] * 7)  # a geral venceu 3 de 10
        self.criar("candidato", 80)
        self.e.treinou(ARENA)
        modelo, quem = self.e.modelo(ARENA)
        self.assertEqual(quem, "candidato")
        self.assertEqual(modelo, "modelo:GG_Gruz_Mother.candidato.npz")
        avisos = self.lutar("candidato", [True] * 4 + [False] * 6)
        self.assertIn("assumiu", avisos[0])
        self.assertTrue(self.e.arquivo(ARENA, "atual").exists())
        self.assertFalse(self.e.arquivo(ARENA, "candidato").exists())
        self.assertEqual(json.loads(self.e.arquivo(ARENA, "atual").with_suffix(".json").read_text())["treino_id"], 80)
        self.assertEqual(self.e.modelo(ARENA)[1], "atual")

    def test_candidato_pior_e_descartado(self):
        self.criar("atual", 80)
        self.lutar("atual", [True] * 6 + [False] * 4)
        self.criar("candidato", 81)
        self.e.treinou(ARENA)
        avisos = self.lutar("candidato", [True] * 5 + [False] * 5)
        self.assertIn("descartado", avisos[0])
        self.assertFalse(self.e.arquivo(ARENA, "candidato").exists())
        self.assertEqual(self.e.quem_joga(ARENA), "atual")

    def test_estado_fica_salvo(self):
        self.lutar("geral", [True, False])
        de_novo = Especialistas(self.pasta)
        self.assertEqual(de_novo.estado[ARENA]["lutas"]["geral"], [1, 0])


if __name__ == "__main__":
    unittest.main()


class TesteLutasNoPainel(unittest.TestCase):
    """O painel manda cada luta terminada para o currículo (só as de estátua) e
    para o especialista da sala (estátua ou panteão)."""

    def orq(self, lutas, ultima_arena=None):
        import types
        from mosca.orquestrador import Orquestrador
        registros = {"curriculo": [], "especialistas": []}
        o = types.SimpleNamespace(
            juiz=types.SimpleNamespace(pegar_lutas=lambda: lutas, panteoes=[]),
            _estado_jogo={"estatuas": []}, _juiz_ativo=True, _mosca_joga=True, _ultima_arena=ultima_arena,
            curriculo=types.SimpleNamespace(registrar=lambda e, v, o, sala="": registros["curriculo"].append((e, v)) or [],
                                            proxima=lambda: "", panteoes_novos_prontos=lambda p: []),
            especialistas=types.SimpleNamespace(
                registrar_luta=lambda a, q, v: registros["especialistas"].append((a, q, v)) or [],
                precisa_treinar=lambda: None),
            jogo=types.SimpleNamespace(estatua_alvo=""), treino=None, _fila_especialistas=[],
            _notificar=lambda t: None, _info_treino=None, _info_ate=0.0,
        )
        Orquestrador._seguir_curriculo(o)
        return registros

    def test_panteao_vai_so_para_o_especialista_da_sala(self):
        r = self.orq([("", "GG_Vengefly", True)], ultima_arena=("GG_Vengefly", "atual"))
        self.assertEqual(r["curriculo"], [])
        self.assertEqual(r["especialistas"], [("GG_Vengefly", "atual", True)])

    def test_estatua_vai_para_os_dois(self):
        r = self.orq([("GG_Statue_Gruz", "GG_Gruz_Mother", False)], ultima_arena=("GG_Gruz_Mother", "candidato"))
        self.assertEqual(r["curriculo"], [("GG_Statue_Gruz", False)])
        self.assertEqual(r["especialistas"], [("GG_Gruz_Mother", "candidato", False)])

    def test_sem_saber_quem_jogou_conta_como_a_geral(self):
        r = self.orq([("", "GG_Hornet_1", False)], ultima_arena=("GG_Vengefly", "atual"))
        self.assertEqual(r["especialistas"], [("GG_Hornet_1", "geral", False)])
