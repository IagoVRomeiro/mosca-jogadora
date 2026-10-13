"""Dados do conectoma preparados para a Fase 5 (pula se ainda não foram gerados)."""

import unittest

import numpy as np

from preparar_conectoma import ARQUIVO_SAIDA


@unittest.skipUnless(ARQUIVO_SAIDA.exists(), "rode preparar_conectoma.py antes")
class TesteConectoma(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = np.load(ARQUIVO_SAIDA)

    def test_camadas_se_encaixam(self):
        v, c, dsc = (len(self.d[f"grupos_{k}"]) for k in ("visual", "central", "descendente"))
        self.assertEqual(self.d["ligacoes_visual_central"].shape, (v, c))
        self.assertEqual(self.d["ligacoes_central_central"].shape, (c, c))
        self.assertEqual(self.d["ligacoes_central_descendente"].shape, (c, dsc))
        self.assertEqual(self.d["ligacoes_visual_descendente"].shape, (v, dsc))

    def test_ligacoes_normalizadas_e_com_sinal(self):
        m = self.d["ligacoes_central_descendente"]
        soma = np.abs(m).sum(axis=0)
        self.assertTrue(np.all((np.isclose(soma, 1, atol=1e-4)) | (soma == 0)))
        self.assertTrue((m > 0).any() and (m < 0).any())  # excitatórias e inibitórias

    def test_quase_toda_saida_recebe_sinal(self):
        chega = np.abs(self.d["ligacoes_central_descendente"]).sum(axis=0) + np.abs(
            self.d["ligacoes_visual_descendente"]).sum(axis=0)
        self.assertGreater((chega > 0).mean(), 0.95)

    def test_desenho_tem_os_descendentes(self):
        classe = self.d["desenho_classe"]
        self.assertGreater((classe == "descending").sum(), 1000)
        self.assertEqual(len(self.d["desenho_posicao"]), len(classe))


if __name__ == "__main__":
    unittest.main()
