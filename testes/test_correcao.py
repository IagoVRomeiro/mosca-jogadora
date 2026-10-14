"""Correção ao vivo: você assume quando a mosca erra e ela volta quando você solta."""

import types
import unittest
from unittest import mock

import numpy as np

import mosca.orquestrador as orquestrador
from mosca.config import ACOES
from mosca.correcao import Correcao
from mosca.orquestrador import Orquestrador

QUADRO_S = 1 / 30


def rodar(c, apertando, inicio=0.0):
    """Quadro a quadro; devolve as mudanças (tempo, tipo)."""
    mudancas = []
    for i, voce in enumerate(apertando):
        agora = inicio + i * QUADRO_S
        m = c.passo(voce, agora)
        if m:
            mudancas.append((round(agora, 2), m))
    return mudancas


class TesteCorrecao(unittest.TestCase):
    def test_assume_e_devolve_depois_de_soltar(self):
        c = Correcao()
        mudancas = rodar(c, [False] * 30 + [True] * 90 + [False] * 90)  # 3 s jogando
        self.assertEqual([m for _, m in mudancas], ["assumiu", "devolveu"])
        self.assertAlmostEqual(mudancas[1][0] - mudancas[0][0], 3 + Correcao.SOLTOU_S, delta=0.1)
        self.assertAlmostEqual(c.segundos, 3, delta=0.1)

    def test_toque_rapido_e_sem_querer(self):
        c = Correcao()
        mudancas = rodar(c, [True] * 5 + [False] * 90)
        self.assertEqual([m for _, m in mudancas], ["assumiu", "sem_querer"])

    def test_pausas_curtas_nao_devolvem(self):
        c = Correcao()  # soltar por 1 s no meio da correção não devolve o controle
        mudancas = rodar(c, ([True] * 30 + [False] * 30) * 3 + [False] * 90)
        self.assertEqual([m for _, m in mudancas], ["assumiu", "devolveu"])

    def test_em_apuros_so_com_problema_recente(self):
        c = Correcao()
        c.eventos(["presa"], 10.0)
        c.passo(True, 12.0)  # 2 s depois de ficar presa
        self.assertTrue(c.em_apuros)
        c.terminar()
        c = Correcao()
        c.eventos(["presa"], 10.0)
        c.passo(True, 20.0)  # 10 s depois: não estava mais em apuros
        self.assertFalse(c.em_apuros)
        c = Correcao()
        c.eventos(["acerto", "geo"], 10.0)  # coisas boas não são apuros
        c.passo(True, 11.0)
        self.assertFalse(c.em_apuros)


class GravadorFalso:
    criados = []

    def __init__(self, base=None, sufixo=""):
        self.sufixo, self.quadros, self.ajustes = sufixo, 0, []
        self.parado = self.descartado = False
        GravadorFalso.criados.append(self)

    def adicionar(self, *args):
        self.quadros += 1

    def parar(self):
        self.parado = True

    def descartar(self):
        self.descartado = True

    def ajustar_ultima(self, valor):
        self.ajustes.append(valor)
        return True


class TesteNoPainel(unittest.TestCase):
    """O orquestrador com um jogo falso: quem aperta as teclas em cada momento."""

    def orq(self):
        jogo = types.SimpleNamespace(controlando=True, aviso=None, apertadas={"Direita"}, soltas=0,
                                     usuario=set())
        jogo.em_foco = lambda: True
        jogo.teclas_do_usuario = lambda: np.array([a in jogo.usuario | jogo.apertadas for a in ACOES])
        jogo.da_mosca = lambda: set(jogo.apertadas)

        def soltar_tudo():
            jogo.apertadas.clear()
            jogo.soltas += 1

        jogo.soltar_tudo = soltar_tudo
        o = types.SimpleNamespace(
            hud=types.SimpleNamespace(vida=5), _vida=5, _estado_jogo=None, jogo=jogo, correcao=Correcao(), gravador_correcao=None,
            _correcao_s=0.0, _eventos_quadro=[], _recompensa_quadro=0.0, gravador_mosca=GravadorFalso(),
            partida={"eventos": __import__("collections").Counter(), "recompensa": 0.0},
            torneio=None, cerebro=types.SimpleNamespace(reduzida=None, recompensa=lambda v: None),
            avisos=[],
        )
        o._notificar = o.avisos.append
        o._fim_correcao = lambda tipo: Orquestrador._fim_correcao(o, tipo)
        o._suas_teclas = lambda: Orquestrador._suas_teclas(o)
        return o

    def test_sua_tecla_tira_a_mosca_e_ela_volta(self):
        o = self.orq()
        relogio = [0.0]
        with mock.patch.object(orquestrador, "Gravador", GravadorFalso), \
             mock.patch.object(orquestrador.time, "monotonic", lambda: relogio[0]):
            self.assertIsNone(Orquestrador._vigiar_correcao(o))  # só a mosca apertando (Direita)
            o._eventos_quadro = ["presa"]
            Orquestrador._vigiar_correcao(o)
            o._eventos_quadro = []
            o.jogo.usuario = {"Esquerda"}  # você aperta Esquerda
            relogio[0] = 0.1
            suas = Orquestrador._vigiar_correcao(o)
            self.assertEqual(o.jogo.apertadas, set())  # a mosca soltou tudo
            self.assertEqual(suas["Esquerda"], 1.0)
            correcao = o.gravador_correcao
            self.assertEqual(correcao.sufixo, "_correcao")
            for i in range(60):  # 2 s jogando
                relogio[0] = 0.1 + i * QUADRO_S
                Orquestrador._vigiar_correcao(o)
            o.jogo.usuario = set()
            for i in range(70):  # soltou: 2 s depois a mosca volta
                relogio[0] = 2.1 + i * QUADRO_S
                resultado = Orquestrador._vigiar_correcao(o)
        self.assertIsNone(resultado)
        self.assertTrue(correcao.parado)
        self.assertGreater(correcao.quadros, 50)
        self.assertEqual(o.partida["eventos"]["ajuda"], 1)
        self.assertEqual(o.gravador_mosca.ajustes, [Correcao.PUNICAO])  # estava presa: estímulo ruim
        self.assertGreater(o._correcao_s, 1.5)

    def test_sem_apuros_nao_pune(self):
        o = self.orq()
        relogio = [0.0]
        with mock.patch.object(orquestrador, "Gravador", GravadorFalso), \
             mock.patch.object(orquestrador.time, "monotonic", lambda: relogio[0]):
            o.jogo.usuario = {"Pular"}
            for i in range(60):
                relogio[0] = i * QUADRO_S
                Orquestrador._vigiar_correcao(o)
            o.jogo.usuario = set()
            for i in range(70):
                relogio[0] = 2 + i * QUADRO_S
                Orquestrador._vigiar_correcao(o)
        self.assertEqual(o.partida["eventos"]["ajuda"], 1)
        self.assertEqual(o.gravador_mosca.ajustes, [])

    def test_pelo_controle_com_o_plugin(self):
        """Com o plugin, as ações vêm do jogo (teclado ou controle): o controle
        também assume, e o que a mosca aperta não conta como seu."""
        o = self.orq()
        o._estado_jogo = {"acoes": ["Direita", "Pular"]}  # Direita é da mosca; Pular é seu (botão A)
        relogio = [0.0]
        with mock.patch.object(orquestrador, "Gravador", GravadorFalso), \
             mock.patch.object(orquestrador.time, "monotonic", lambda: relogio[0]):
            suas = Orquestrador._vigiar_correcao(o)
        self.assertTrue(o.correcao.ativa)
        self.assertEqual(suas["Pular"], 1.0)
        self.assertEqual(suas["Direita"], 0.0)

    def test_so_a_mosca_pelo_plugin_nao_assume(self):
        o = self.orq()
        o._estado_jogo = {"acoes": ["Direita"]}  # o jogo vê a tecla da mosca
        self.assertIsNone(Orquestrador._vigiar_correcao(o))
        self.assertFalse(o.correcao.ativa)

    def test_mosca_desligada_nao_assume(self):
        o = self.orq()
        o.jogo.controlando = False
        o.jogo.usuario = {"Pular"}
        with mock.patch.object(orquestrador, "Gravador", GravadorFalso):
            self.assertIsNone(Orquestrador._vigiar_correcao(o))
        self.assertFalse(o.correcao.ativa)


if __name__ == "__main__":
    unittest.main()
