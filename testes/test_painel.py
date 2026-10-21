"""Painel: treino depois de gravar, revezamento de cérebros e atalhos."""

import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path

import numpy as np

import mosca.orquestrador as orquestrador
from mosca.orquestrador import Orquestrador

class TesteTorneioETreino(unittest.TestCase):
    def orq(self, campea="mlp", seguidas=0, em_disputa=False, na_frente=False):
        o = types.SimpleNamespace(
            modelos={"campea": types.SimpleNamespace(arquitetura=campea)},
            torneio=types.SimpleNamespace(estado={"seguidas_da_campea": seguidas}, em_disputa=em_disputa),
            OUTRA_ARQUITETURA_A_CADA=Orquestrador.OUTRA_ARQUITETURA_A_CADA,
            treinos=[], avisos=[], encerradas=[], _treino_pendente=False,
        )
        o._desafiante_na_frente = lambda: na_frente
        o._nome = lambda papel: papel
        o.treinar = lambda: o.treinos.append(1)
        o._encerrar_torneio = lambda resultado: o.encerradas.append(resultado)
        o._avisar = lambda texto, s: o.avisos.append(texto)
        return o

    def test_reveza_arquiteturas(self):
        f = Orquestrador._arquitetura_do_treino
        self.assertEqual(f(self.orq("mlp", 0)), "mlp")
        self.assertEqual(f(self.orq("mlp", 1)), "mlp")
        self.assertEqual(f(self.orq("mlp", 2)), "conectoma")  # depois de duas iguais à campeã
        self.assertEqual(f(self.orq("conectoma", 2)), "mlp")

    def test_gravacao_treina_na_hora_mesmo_com_disputa(self):
        o = self.orq(em_disputa=True)
        Orquestrador._pedir_treino(o)
        self.assertEqual(o.encerradas, ["interrompida"])  # a campeã não muda
        self.assertEqual(o.treinos, [1])
        o = self.orq(em_disputa=False)
        Orquestrador._pedir_treino(o)
        self.assertEqual((o.encerradas, o.treinos), ([], [1]))

    def test_desafiante_na_frente_nao_e_interrompida(self):
        o = self.orq(em_disputa=True, na_frente=True)
        Orquestrador._pedir_treino(o)
        self.assertEqual((o.encerradas, o.treinos), ([], []))  # espera o veredito
        self.assertTrue(o._treino_pendente)

    def test_na_frente_so_com_tempo_e_placar(self):
        def placar(seg_d, rec_d, seg_c, rec_c):
            estado = {"placar": {"desafiante": {"segundos": seg_d, "recompensa": rec_d},
                                 "campea": {"segundos": seg_c, "recompensa": rec_c}}}
            t = types.SimpleNamespace(estado=estado)
            t.por_minuto = lambda papel: (estado["placar"][papel]["recompensa"] / estado["placar"][papel]["segundos"] * 60
                                          if estado["placar"][papel]["segundos"] else 0.0)
            return Orquestrador._desafiante_na_frente(types.SimpleNamespace(torneio=t, LIDERANDO_MINIMO_S=60))
        self.assertTrue(placar(120, -2, 120, -8))
        self.assertFalse(placar(120, -8, 120, -2))  # atrás
        self.assertFalse(placar(30, -1, 120, -8))  # pouco tempo para saber


class TesteSubstituida(unittest.TestCase):
    def test_desafiante_sem_resultado_fica_como_substituida(self):
        marcados = []
        placar = {p: {"segundos": 30.0, "recompensa": -1.0} for p in ("campea", "desafiante")}
        torneio = types.SimpleNamespace(estado={"placar": placar}, por_minuto=lambda papel: -2.0)
        o = types.SimpleNamespace(
            modelos={"desafiante": types.SimpleNamespace(treino_id=41), "campea": types.SimpleNamespace(treino_id=40)},
            torneio=torneio, _envios=[],
        )
        with mock.patch.object(orquestrador, "marcar_torneio", lambda tid, r: marcados.append((tid, r["resultado"]))):
            Orquestrador._registrar_substituida(o)
            self.assertEqual(marcados, [(41, "substituida")])
            self.assertIsNone(o.modelos["desafiante"])
            Orquestrador._registrar_substituida(o)  # sem desafiante: nada
        self.assertEqual(len(marcados), 1)


class TesteEscapar(unittest.TestCase):
    """Presa na parede: primeiro tenta escalar; se continuar presa, meia-volta."""

    def orq(self):
        pulsos = []
        o = types.SimpleNamespace(
            _lado_presa="Direita", _escalada_em=float("-inf"), _pulos_escalada=[],
            _sorteio=types.SimpleNamespace(random=lambda: 0.9), _mosca_joga=True,
            cerebro=types.SimpleNamespace(pulsar_zona=lambda nome, d=1.0: pulsos.append((nome, d))),
            ESCALAR_S=Orquestrador.ESCALAR_S, PULOS_ESCALADA_S=Orquestrador.PULOS_ESCALADA_S,
            DE_NOVO_ESCALAR_S=Orquestrador.DE_NOVO_ESCALAR_S,
        )
        return o, pulsos

    def test_primeiro_escala_depois_meia_volta(self):
        o, pulsos = self.orq()
        relogio = [100.0]
        with mock.patch.object(orquestrador.time, "monotonic", lambda: relogio[0]):
            texto = Orquestrador._escapar(o)
            self.assertIn("escalar", texto)
            self.assertEqual(pulsos, [("Direita", Orquestrador.ESCALAR_S)])  # para o lado da parede
            for t in (100.0, 100.8, 101.5):  # os pulos, separados
                relogio[0] = t
                Orquestrador._pular_na_escalada(o)
            self.assertEqual([p for p in pulsos if p[0] == "Pular"], [("Pular", 0.4)] * 3)
            relogio[0] = 104.0  # continuou presa: a tentativa não deu certo
            texto = Orquestrador._escapar(o)
        self.assertIn("meia-volta", texto)
        self.assertEqual(pulsos[-1][0], "Esquerda")

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


class TesteMemoriaDoTreino(unittest.TestCase):
    """Com pouca memória livre, o treino espera em vez de derrubar o jogo."""

    def orq(self, livre):
        o = types.SimpleNamespace(treino=None, _treinar_de_novo=False, _fila_especialistas=[], avisos=[],
                                  MEMORIA_TREINO_GB=4.5, MEMORIA_ESPECIALISTA_GB=3.0, ESPERA_MEMORIA_S=30)
        o._memoria_livre_gb = lambda: livre
        o._avisar = lambda texto, s: o.avisos.append(texto)
        o._memoria_basta = lambda gb, oque: Orquestrador._memoria_basta(o, gb, oque)
        return o

    def test_pouca_memoria_adia_o_treino_geral(self):
        o = self.orq(livre=2.0)
        Orquestrador.treinar(o)
        self.assertIsNone(o.treino)
        self.assertTrue(o._geral_adiado)
        self.assertIn("adiado", o.avisos[0])

    def test_pouca_memoria_devolve_o_especialista_para_a_fila(self):
        o = self.orq(livre=2.0)
        Orquestrador.treinar_especialista(o, "GG_Gruz_Mother")
        self.assertEqual(o._fila_especialistas, ["GG_Gruz_Mother"])
