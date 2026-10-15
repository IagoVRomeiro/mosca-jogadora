"""Envio de teclas ao jogo: toques repetidos, Foco segurado, opostas e trava de foco.

Não usa o X11: a CapturaJanela é montada sem conectar e as teclas são anotadas.
"""

import unittest

from mosca.config import ACOES, ACOES_JOGO
from mosca.jogo import CapturaJanela

QUADRO_S = 1 / 30


def captura_falsa(foco_no_jogo=True):
    c = CapturaJanela.__new__(CapturaJanela)
    c.apertadas, c._ativas, c._desde, c._apertou_em = set(), set(), {}, {}
    c._soltou_em, c._fisicas, c._solto_ate = {}, set(), {}
    c._codigos = {a: ACOES_JOGO[a].tecla for a in ACOES}  # Foco e Magia: as duas no "k"
    c.controlando, c.aviso, c.aviso_controle = True, None, None
    c.janela = type("Janela", (), {"id": 42})()
    c.janelas_proprias = set()
    c.enviadas = []
    c._foco = lambda: 42 if foco_no_jogo else 7
    c.focar = lambda: c.enviadas.append("focar")
    c.display = type("Display", (), {"flush": lambda self: None})()
    c._mandar_ao_plugin = lambda acoes: None  # nada de UDP de verdade nos testes

    def tecla(acao, apertar):
        c.enviadas.append((acao, apertar))

    c._tecla = tecla
    return c


def simular(c, acao, vontades):
    """Desenho da tecla quadro a quadro (█ apertada) e número de apertos."""
    desenho, apertos = "", 0
    for i, vontade in enumerate(vontades):
        agora = i * QUADRO_S
        apertar = c._decidir(acao, vontade, agora)
        if apertar and acao not in c.apertadas:
            apertos += 1
            c._apertou_em[acao] = agora
        (c.apertadas.add if apertar else c.apertadas.discard)(acao)
        desenho += "█" if apertar else "·"
    return desenho, apertos


class TesteTeclas(unittest.TestCase):
    def test_ataque_vira_toques_repetidos(self):
        _, golpes = simular(captura_falsa(), "Atacar", [0.9] * 45)  # 1,5 s querendo atacar
        self.assertEqual(golpes, 5)

    def test_foco_fica_segurado_o_minimo(self):
        desenho, _ = simular(captura_falsa(), "Foco", [0.9] * 6 + [0.2] * 54)  # quis só 0,2 s
        self.assertAlmostEqual(desenho.count("█") * QUADRO_S, 1.5, delta=0.05)

    def test_pulo_longo_vira_pulos_repetidos(self):
        """Querendo pular por 2 s (agarrada na parede): solta e aperta de novo,
        nunca segurando mais que 0,6 s, para conseguir pular de novo na parede."""
        desenho, apertos = simular(captura_falsa(), "Pular", [0.9] * 60)
        self.assertEqual(apertos, 3)
        maior = max(len(t) for t in desenho.split("·") if t)
        self.assertLessEqual(maior * QUADRO_S, 0.6 + QUADRO_S)

    def test_pulo_normal_nao_muda(self):
        desenho, apertos = simular(captura_falsa(), "Pular", [0.9] * 7 + [0.2] * 20)  # 0,23 s
        self.assertEqual((desenho.count("█"), apertos), (7, 1))

    def test_andar_segura_enquanto_quer(self):
        desenho, apertos = simular(captura_falsa(), "Esquerda", [0.9] * 10 + [0.2] * 10)
        self.assertEqual(desenho, "█" * 10 + "·" * 10)
        self.assertEqual(apertos, 1)

    def test_histerese_nao_pisca(self):
        # vontade oscilando entre 0,4 e 0,6: aperta uma vez e não solta (solta só < 0,35)
        _, apertos = simular(captura_falsa(), "Direita", [0.6, 0.4] * 15)
        self.assertEqual(apertos, 1)

    def test_opostas_fica_a_mais_forte(self):
        c = captura_falsa()
        acoes = {a: 0.0 for a in ACOES}
        acoes.update(Esquerda=0.9, Direita=0.7, Cima=0.6, Baixo=0.8)
        c.passo(acoes)
        self.assertEqual(c.apertadas, {"Esquerda", "Baixo"})

    def test_com_foco_em_outro_programa_nao_aperta_nada(self):
        c = captura_falsa(foco_no_jogo=False)
        acoes = {a: 0.0 for a in ACOES}
        acoes["Direita"] = 1.0
        c.passo(acoes)
        self.assertEqual(c.apertadas, set())
        self.assertNotIn(("Direita", True), c.enviadas)
        self.assertIsNotNone(c.aviso_controle)

    def test_pelo_plugin_joga_sem_foco_e_sem_xtest(self):
        c = captura_falsa(foco_no_jogo=False)
        c.pelo_plugin, mandadas = True, []
        c._mandar_ao_plugin = lambda acoes: mandadas.append(set(acoes))
        acoes = {a: 0.0 for a in ACOES}
        acoes["Direita"] = acoes["Foco"] = 1.0
        c.passo(acoes)
        self.assertEqual(mandadas[-1], {"Direita", "Foco"})
        self.assertEqual(c.enviadas, [])  # nenhuma tecla de verdade, nem pedido de foco
        self.assertIsNone(c.aviso_controle)
        c.soltar_tudo()
        self.assertEqual(mandadas[-1], set())

    def test_trocar_para_o_plugin_solta_as_teclas_de_verdade(self):
        c = captura_falsa()
        c._mandar_ao_plugin = lambda acoes: None
        acoes = {a: 0.0 for a in ACOES}
        acoes["Direita"] = 1.0
        c.passo(acoes)
        self.assertEqual(c._fisicas, {"d"})
        c.pelo_plugin = True
        c.passo(acoes)
        self.assertEqual(c._fisicas, set())
        self.assertIn(("Direita", False), c.enviadas)

    def test_com_foco_no_painel_devolve_o_foco_ao_jogo(self):
        c = captura_falsa(foco_no_jogo=False)
        c.janelas_proprias = {7}
        acoes = {a: 0.0 for a in ACOES}
        acoes["Direita"] = 1.0
        c.passo(acoes)
        self.assertIn("focar", c.enviadas)
        self.assertEqual(c.apertadas, set())  # só aperta depois que o jogo estiver em foco

    def test_foco_e_magia_dividem_o_k(self):
        """Trocar de Foco para Magia no mesmo quadro não solta o K no meio."""
        c = captura_falsa()
        acoes = {a: 0.0 for a in ACOES}
        acoes["Foco"] = 1.0
        c.passo(acoes)
        self.assertEqual(c._fisicas, {"k"})
        self.assertEqual(c.enviadas.count(("Foco", True)), 1)
        self.assertEqual(c.da_mosca() & {"Foco", "Magia"}, {"Foco", "Magia"})  # o jogo só vê o K

    def test_nunca_foco_e_magia_juntos(self):
        c = captura_falsa()
        acoes = {a: 0.0 for a in ACOES}
        acoes.update(Foco=0.9, Magia=0.8)
        c.passo(acoes)
        self.assertNotIn("Magia", c.apertadas)

    def test_desligar_solta_tudo(self):
        c = captura_falsa()
        acoes = {a: 0.0 for a in ACOES}
        acoes["Direita"] = 1.0
        c.passo(acoes)
        c.controlando = False
        c.passo(acoes)
        self.assertEqual(c.apertadas, set())
        self.assertEqual(c._fisicas, set())


if __name__ == "__main__":
    unittest.main()
