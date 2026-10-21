"""Currículo de chefes: domínio, revisão, empacou e escolha sua."""

import tempfile
import types
import unittest
from pathlib import Path

from mosca.curriculo import Curriculo, nome_do_chefe
from mosca.orquestrador import Orquestrador

ORDEM = ["GG_Statue_Vengefly", "GG_Statue_Gruz", "GG_Statue_FalseKnight", "GG_Statue_Hornet"]


class TesteCurriculo(unittest.TestCase):
    def setUp(self):
        self.c = Curriculo(Path(tempfile.mkdtemp()) / "curriculo.json")

    def lutar(self, estatua, resultados, agora=0.0):
        avisos = []
        for i, venceu in enumerate(resultados):
            avisos += self.c.registrar(estatua, venceu, ORDEM, agora + i)
        return avisos

    def test_a_primeira_luta_define_o_chefe(self):
        self.lutar("GG_Statue_Gruz", [False])
        self.assertEqual(self.c.atual, "GG_Statue_Gruz")
        self.assertEqual(self.c.proxima(), "GG_Statue_Gruz")

    def test_domina_com_7_de_10_e_vai_para_o_proximo(self):
        avisos = self.lutar("GG_Statue_Gruz", [True] * 6 + [False] * 3)
        self.assertEqual(avisos, [])  # 6 de 9
        avisos = self.lutar("GG_Statue_Gruz", [True])  # 7 de 10
        self.assertEqual(self.c.atual, "GG_Statue_FalseKnight")
        self.assertIn("Dominou Gruz", avisos[0])
        self.assertIn("GG_Statue_Gruz", self.c.estado["dominados"])

    def test_fica_no_chefe_atual_sem_revisar_os_dominados(self):
        self.lutar("GG_Statue_Gruz", [True] * 10)
        proximas = []
        for _ in range(8):
            proximas.append(self.c.proxima())
            self.c.registrar(proximas[-1], False, ORDEM, 100.0)
        self.assertEqual(proximas, ["GG_Statue_FalseKnight"] * 8)

    def test_revisao_ligada_volta_a_funcionar(self):
        self.c.REVISAO_A_CADA = 4
        self.lutar("GG_Statue_Gruz", [True] * 10)
        proximas = []
        for _ in range(8):
            proximas.append(self.c.proxima())
            self.c.registrar(proximas[-1], False, ORDEM, 100.0)
        self.assertEqual(proximas.count("GG_Statue_Gruz"), 2)

    def test_empacou_avisa_a_cada_30_min_e_nunca_pula(self):
        self.assertEqual(self.lutar("GG_Statue_Gruz", [False]), [])
        avisos = self.c.registrar("GG_Statue_Gruz", False, ORDEM, 31 * 60)
        self.assertIn("Empacou", avisos[0])
        self.assertEqual(self.c.registrar("GG_Statue_Gruz", False, ORDEM, 40 * 60), [])
        self.assertIn("Empacou", self.c.registrar("GG_Statue_Gruz", False, ORDEM, 61 * 60)[0])  # de novo
        self.c.registrar("GG_Statue_Gruz", False, ORDEM, 300 * 60)
        self.assertEqual(self.c.atual, "GG_Statue_Gruz")  # 5 h depois, ainda nele

    def test_estatua_escolhida_por_voce_vira_a_atual(self):
        self.lutar("GG_Statue_Gruz", [False])
        self.lutar("GG_Statue_Hornet", [False])
        self.assertEqual(self.c.atual, "GG_Statue_Hornet")

    def test_fica_salvo(self):
        self.lutar("GG_Statue_Gruz", [True, False])
        de_novo = Curriculo(self.c.arquivo)
        self.assertEqual(de_novo.atual, "GG_Statue_Gruz")
        self.assertEqual(de_novo.texto(), "currículo: Gruz 1/2")

    def test_panteao_pronto_quando_todos_os_chefes_dominados(self):
        panteoes = [{"porta": "GG_Boss_Door_1", "liberado": True,
                     "salas": ["GG_Vengefly", "GG_Gruz_Mother", "GG_Spa", "GG_Engine"]},
                    {"porta": "GG_Boss_Door_5", "liberado": False, "salas": ["GG_Vengefly"]}]
        for i in range(10):
            self.c.registrar("GG_Statue_Vengefly", True, ORDEM, i, sala="GG_Vengefly")
        self.assertEqual(self.c.progresso_panteoes(panteoes), [("GG_Boss_Door_1", 1, 2)])  # banco e passagem não contam
        self.assertEqual(self.c.panteoes_novos_prontos(panteoes), [])
        for i in range(10):
            self.c.registrar("GG_Statue_Gruz", True, ORDEM, 20 + i, sala="GG_Gruz_Mother")
        avisos = self.c.panteoes_novos_prontos(panteoes)
        self.assertIn("GG_Boss_Door_1: os 2 chefes dominados", avisos[0])
        self.assertEqual(self.c.panteoes_novos_prontos(panteoes), [])  # avisa uma vez só

    def test_nome(self):
        self.assertEqual(nome_do_chefe("GG_Statue_GruzMother"), "GruzMother")


class TesteRevezamento(unittest.TestCase):
    def arquitetura(self, campea, seguidas):
        o = types.SimpleNamespace(
            modelos={"campea": types.SimpleNamespace(arquitetura=campea)},
            torneio=types.SimpleNamespace(estado={"seguidas_da_campea": seguidas}),
            OUTRA_ARQUITETURA_A_CADA=Orquestrador.OUTRA_ARQUITETURA_A_CADA,
        )
        return Orquestrador._arquitetura_do_treino(o)

    def test_a_outra_uma_vez_a_cada_tres(self):
        self.assertEqual([self.arquitetura("mlp", s) for s in (0, 1, 2)], ["mlp", "mlp", "conectoma"])
        self.assertEqual(self.arquitetura("conectoma", 2), "mlp")


if __name__ == "__main__":
    unittest.main()
