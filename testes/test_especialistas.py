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

    def test_candidato_reveza_com_a_geral_e_assume_se_vencer_pelo_menos_tanto(self):
        self.lutar("geral", [True] * 3 + [False] * 7)  # a geral venceu 3 de 10
        self.criar("candidato", 80)
        self.e.treinou(ARENA)
        modelo, quem = self.e.modelo(ARENA)
        self.assertEqual((modelo, quem), ("modelo:GG_Gruz_Mother.candidato.npz", "candidato"))
        avisos = []
        for i in range(19):  # revezam: candidato, geral, ...; na 10ª do candidato (a 19ª), o veredito
            quem = self.e.quem_joga(ARENA) or "geral"
            self.assertEqual(quem, "candidato" if i % 2 == 0 else "geral")
            venceu = i % 4 == 0 if quem == "candidato" else i % 6 == 1  # cand. 5/10, geral ~2/10
            avisos += self.e.registrar_luta(ARENA, quem, venceu)
        self.assertIn("assumiu", avisos[-1])
        self.assertTrue(self.e.arquivo(ARENA, "atual").exists())
        self.assertFalse(self.e.arquivo(ARENA, "candidato").exists())
        self.assertEqual(self.e.modelo(ARENA)[1], "atual")

    def test_candidato_sai_assim_que_nao_alcanca_o_atual(self):
        self.criar("atual", 80)
        self.lutar("atual", [True] * 7 + [False] * 3)  # o atual vence 7 de 10
        self.criar("candidato", 104)
        self.e.treinou(ARENA)
        avisos = []
        for _ in range(3):
            self.assertEqual(self.e.quem_joga(ARENA), "candidato")
            avisos += self.e.registrar_luta(ARENA, "candidato", False)
            self.assertEqual(self.e.quem_joga(ARENA), "atual")  # revezam: agora o atual
            avisos += self.e.registrar_luta(ARENA, "atual", True)
        # o atual venceu as 3 lutas dele na avaliação (ritmo de 10/10); o candidato, 0/3,
        # chegaria no máximo a 7: sai já na luta 3
        self.assertIn("descartado já na luta 3", avisos[-1])
        self.assertFalse(self.e.arquivo(ARENA, "candidato").exists())
        self.assertEqual(self.e.quem_joga(ARENA), "atual")

    def test_revisar_descarta_candidato_que_ja_perdeu(self):
        self.criar("atual", 80)
        self.lutar("atual", [True] * 7 + [False] * 3)
        self.criar("candidato", 104)
        self.e.treinou(ARENA)
        self.e.estado[ARENA]["lutas"]["candidato"] = [0] * 6  # como o #104: 0 de 6
        avisos = self.e.revisar()
        self.assertIn("descartado", avisos[0])

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


class TesteSoAArena(unittest.TestCase):
    """treinar.so_a_arena: gravação que cresceu durante o treino não derruba o treino."""

    def test_gravacao_que_cresceu_e_relida_ou_fica_de_fora(self):
        import types
        from unittest import mock
        import treinar
        dados = types.SimpleNamespace(sessao=np.array([0, 0, 0, 1, 1]), retratos=np.zeros((5, 1)),
                                      treino=np.arange(5), valid=np.array([], int))
        cenas = {"a": np.array(["X", "Y", "X"]), "b": np.array(["X"])}  # "b" cresceu: 1 sala, 2 quadros
        with mock.patch.object(treinar, "cenas_da_sessao", return_value=np.array(["X"])):
            treinar.so_a_arena(dados, ["a", "b"], cenas, "X", {"a": None, "b": None})
        self.assertEqual(list(dados.treino), [0, 2])  # "b" ficou de fora; o treino seguiu
        dados.treino = np.arange(5)
        with mock.patch.object(treinar, "cenas_da_sessao", return_value=np.array(["X", "X"])):
            treinar.so_a_arena(dados, ["a", "b"], cenas, "X", {"a": None, "b": None})
        self.assertEqual(list(dados.treino), [0, 2, 3, 4])  # relida: "b" entra
