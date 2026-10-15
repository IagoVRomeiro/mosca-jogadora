"""Treinar em outro computador: nomes dos arquivos da release e o que sobe ou sai."""

import unittest

from notebook import ler_nome, nome_sessao, pasta_da_sessao, planejar


class TesteNotebook(unittest.TestCase):
    def test_nome_vai_e_volta(self):
        for sessao in ("2026-10-14_231019_correcao", "mosca_2026-10-14_230425"):
            self.assertEqual(ler_nome(nome_sessao(sessao, 12)), (sessao, 12))
        self.assertIsNone(ler_nome("modelos.tar"))
        self.assertIsNone(ler_nome("conectoma__1234.tar"))

    def test_pastas(self):
        self.assertEqual(pasta_da_sessao("mosca_2026-10-14_230425").parts[-2:], ("gravacoes_mosca", "2026-10-14_230425"))
        self.assertEqual(pasta_da_sessao("2026-10-14_231019").parts[-2:], ("gravacoes", "2026-10-14_231019"))

    def test_planejar(self):
        remotos = [nome_sessao("a", 3), nome_sessao("b", 2), nome_sessao("mosca_velha", 5), "modelos.tar"]
        subir, apagar = planejar({"a": 3, "b": 4, "c": 1}, remotos)
        self.assertEqual(sorted(subir), ["b", "c"])  # b cresceu, c é nova
        self.assertEqual(sorted(apagar), [nome_sessao("b", 2), nome_sessao("mosca_velha", 5)])
        self.assertEqual(planejar({"a": 3}, [nome_sessao("a", 3)]), ([], []))
