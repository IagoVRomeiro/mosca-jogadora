"""Painel: treino depois de gravar, revezamento de cérebros e atalhos."""

import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

from mosca.orquestrador import Orquestrador

class TesteTorneioETreino(unittest.TestCase):
    def orq(self, campea="mlp", ultima=None, em_disputa=False):
        o = types.SimpleNamespace(
            modelos={"campea": types.SimpleNamespace(arquitetura=campea)},
            torneio=types.SimpleNamespace(estado={"ultima_arquitetura": ultima}, em_disputa=em_disputa),
            treinos=[], avisos=[], encerradas=[],
        )
        o.treinar = lambda: o.treinos.append(1)
        o._encerrar_torneio = lambda resultado: o.encerradas.append(resultado)
        o._avisar = lambda texto, s: o.avisos.append(texto)
        return o

    def test_reveza_arquiteturas(self):
        f = Orquestrador._arquitetura_do_treino
        self.assertEqual(f(self.orq("mlp", None)), "mlp")
        self.assertEqual(f(self.orq("mlp", "mlp")), "conectoma")  # depois de uma igual à campeã
        self.assertEqual(f(self.orq("mlp", "conectoma")), "mlp")
        self.assertEqual(f(self.orq("conectoma", "conectoma")), "mlp")

    def test_gravacao_treina_na_hora_mesmo_com_disputa(self):
        o = self.orq(em_disputa=True)
        Orquestrador._pedir_treino(o)
        self.assertEqual(o.encerradas, ["interrompida"])  # a campeã não muda
        self.assertEqual(o.treinos, [1])
        o = self.orq(em_disputa=False)
        Orquestrador._pedir_treino(o)
        self.assertEqual((o.encerradas, o.treinos), ([], [1]))

class TesteAtalhos(unittest.TestCase):
    def orq(self, controlar_habilitado=True):
        class Botao:
            def __init__(self, habilitado=True):
                self.marcado, self.habilitado = False, habilitado
            def isVisible(self): return True
            def isEnabled(self): return self.habilitado
            def isChecked(self): return self.marcado
            def toggle(self): self.marcado = not self.marcado
        cartao = types.SimpleNamespace(bt_gravar=Botao(), bt_controlar=Botao(controlar_habilitado))
        o = types.SimpleNamespace(painel=types.SimpleNamespace(cartao_mosca=cartao), avisos=[])
        o._notificar = o.avisos.append
        return o, cartao

    def test_mesmo_atalho_liga_e_desliga(self):
        o, cartao = self.orq()
        Orquestrador.atalho(o, "gravar")
        self.assertTrue(cartao.bt_gravar.isChecked())
        Orquestrador.atalho(o, "gravar")
        self.assertFalse(cartao.bt_gravar.isChecked())
        Orquestrador.atalho(o, "controlar")
        self.assertTrue(cartao.bt_controlar.isChecked())
        self.assertEqual(len(o.avisos), 3)

    def test_controlar_gravando_so_avisa(self):
        o, cartao = self.orq(controlar_habilitado=False)  # gravando: botão desabilitado
        Orquestrador.atalho(o, "controlar")
        self.assertFalse(cartao.bt_controlar.isChecked())
        self.assertIn("Pare a gravação", o.avisos[0])


if __name__ == "__main__":
    unittest.main()
