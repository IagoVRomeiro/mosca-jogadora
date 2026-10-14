"""Juiz de dentro do jogo: estados do plugin (mod/MoscaEventos) viram eventos."""

import json
import socket
import tempfile
import time
import unittest
from pathlib import Path

from mosca.juiz import DetectoresPelaPosicao, JuizDoJogo, eventos_entre


def estado(**mudancas):
    e = {"cena": "Crossroads_01", "x": 10.0, "y": 5.0, "vx": 0.0, "vy": 0.0, "vida": 5, "vida_max": 5,
         "vida_azul": 0, "geo": 100, "alma": 0, "golpes": 0, "inimigos_mortos": 0, "morta": False,
         "no_chao": True, "na_parede": False, "curando": False}
    e.update(mudancas)
    return e


LONGE = 99.0  # segundos desde o último Foco


class TesteEventos(unittest.TestCase):
    def test_dano_conta_cada_mascara(self):
        self.assertEqual(eventos_entre(estado(), estado(vida=3), LONGE), ["dano", "dano"])

    def test_dano_na_vida_azul_tambem(self):
        self.assertEqual(eventos_entre(estado(vida_azul=2), estado(vida_azul=1), LONGE), ["dano"])

    def test_cura_so_com_foco(self):
        self.assertEqual(eventos_entre(estado(vida=3), estado(vida=4), 0.5), ["cura"])
        self.assertEqual(eventos_entre(estado(vida=3), estado(vida=5), LONGE), [])  # banco

    def test_morte_e_renascer(self):
        self.assertEqual(eventos_entre(estado(vida=1), estado(vida=0, morta=True), LONGE), ["morte"])
        self.assertEqual(eventos_entre(estado(vida=0, morta=True), estado(vida=5, geo=0), LONGE), [])

    def test_geo_so_quando_sobe(self):
        self.assertEqual(eventos_entre(estado(), estado(geo=106), LONGE), ["geo"])
        self.assertEqual(eventos_entre(estado(), estado(geo=94), LONGE), [])  # gastou

    def test_golpes_e_inimigos(self):
        self.assertEqual(eventos_entre(estado(), estado(golpes=2, inimigos_mortos=1), LONGE),
                         ["acerto", "acerto", "inimigo_morto"])

    def test_cura_com_pouca_vida_vale_mais(self):
        self.assertEqual(eventos_entre(estado(vida=1), estado(vida=2), 0.5), ["cura", "cura_critica"])
        self.assertEqual(eventos_entre(estado(vida=4), estado(vida=5), 0.5), ["cura"])

    def test_cair_em_espinhos(self):
        self.assertEqual(eventos_entre(estado(), estado(vida=4, perigo=True), LONGE), ["dano", "perigo"])
        self.assertEqual(eventos_entre(estado(perigo=True), estado(perigo=True), LONGE), [])  # uma vez só

    def test_carregar_o_save_nao_gera_eventos(self):
        menu = estado(cena="Menu_Title", geo=0, vida=5)
        self.assertEqual(eventos_entre(menu, estado(geo=900, vida=3), LONGE), [])


class TesteRede(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.juiz = JuizDoJogo(self.pasta / "cenas.json", porta=0)
        self.porta = self.juiz.sock.getsockname()[1]
        self.envio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def tearDown(self):
        self.juiz.fechar()
        self.envio.close()

    def mandar(self, **mudancas):
        self.envio.sendto(json.dumps(estado(**mudancas)).encode(), ("127.0.0.1", self.porta))
        time.sleep(0.01)
        return self.juiz.passo()

    def test_sala_nova_uma_vez_so(self):
        self.assertEqual(self.mandar(), [])  # a primeira cena é o começo
        self.assertTrue(self.juiz.ativo)
        self.assertEqual(self.mandar(cena="Crossroads_02"), ["cena_nova"])
        self.assertEqual(self.mandar(cena="Crossroads_01"), [])  # voltou: já conhecia
        self.assertEqual(self.mandar(cena="Crossroads_02"), [])
        de_novo = JuizDoJogo(self.pasta / "cenas.json", porta=0)  # a memória fica salva
        self.assertEqual(de_novo.cenas, {"Crossroads_01", "Crossroads_02"})
        de_novo.fechar()

    def test_carregar_o_save_nao_e_sala_nova(self):
        self.mandar(cena="Menu_Title")
        self.assertEqual(self.mandar(cena="Fungus2_13"), [])
        self.assertIn("Fungus2_13", self.juiz.cenas)  # mas fica conhecida

    def test_renascer_no_banco_nao_e_sala_nova(self):
        self.mandar(cena="Fungus2_13")
        self.assertEqual(self.mandar(cena="Fungus2_13", vida=0, morta=True), ["morte"])
        self.assertEqual(self.mandar(cena="Fungus2_23", vida=5), [])  # renasceu no banco
        self.assertEqual(self.mandar(cena="Fungus2_24"), ["cena_nova"])  # andando, vale

    def test_banco_novo_uma_vez_e_carregar_nao_conta(self):
        self.mandar(cena="Menu_Title")
        self.assertEqual(self.mandar(banco="Town|Bench"), [])  # carregou o save neste banco
        self.assertEqual(self.mandar(banco="Crossroads_47|RestBench"), ["banco_novo"])
        self.assertEqual(self.mandar(banco="Town|Bench"), [])  # já conhecia
        self.assertEqual(self.mandar(banco="Crossroads_47|RestBench"), [])
        de_novo = JuizDoJogo(self.pasta / "cenas.json", porta=0)
        self.assertEqual(de_novo.bancos, {"Town|Bench", "Crossroads_47|RestBench"})
        de_novo.fechar()

    def test_eventos_pela_rede(self):
        self.mandar()
        self.assertEqual(self.mandar(vida=4, golpes=1), ["dano", "acerto"])

    def test_no_menu_nao_esta_ativo(self):
        self.mandar(cena="Menu_Title")
        self.assertFalse(self.juiz.ativo)


class TestePosicao(unittest.TestCase):
    def setUp(self):
        self.d = DetectoresPelaPosicao(Path(tempfile.mkdtemp()) / "lugares.json")

    def rodar(self, segundos, x=lambda i: 10.0, y=lambda i: 5.0, vx=0.0, direita=False, bom=lambda i: False,
              **outros):
        eventos = []
        for i in range(int(segundos * 30)):
            e = estado(x=x(i), y=y(i), vx=vx, **outros)
            eventos += self.d.passo(e, False, direita, bom(i))
        return eventos

    def test_parada_depois_de_3_s(self):
        eventos = self.rodar(4)
        self.assertEqual(eventos.count("parada"), 1)

    def test_curando_nao_e_parada(self):
        self.assertNotIn("parada", self.rodar(5, curando=True))

    def test_presa_contra_a_parede(self):
        eventos = self.rodar(7, direita=True, vx=0.0, x=lambda i: 10.0 + 0.01 * (i % 2))
        self.assertIn("presa", eventos)
        self.assertEqual(self.d.lado, "Direita")
        self.assertTrue(self.d.encostada)  # o aviso veio antes

    def test_escalando_nao_e_presa(self):
        eventos = self.rodar(7, direita=True, vx=0.0, y=lambda i: 5.0 + i * 0.05)  # sobe 10 unidades
        self.assertNotIn("presa", eventos)

    def test_andando_nao_e_presa_nem_loop(self):
        eventos = self.rodar(16, direita=True, vx=8.0, x=lambda i: 10.0 + i * 0.27)
        self.assertNotIn("presa", eventos)
        self.assertNotIn("loop", eventos)
        self.assertGreater(eventos.count("lugar_novo"), 5)  # ~130 unidades: vários pedaços novos

    def test_indo_e_voltando_e_loop(self):
        import math
        eventos = self.rodar(16, vx=8.0, x=lambda i: 10.0 + 6 * math.sin(i / 20))
        self.assertIn("loop", eventos)

    def test_lutando_indo_e_voltando_nao_e_loop(self):
        import math
        eventos = self.rodar(16, vx=8.0, x=lambda i: 10.0 + 6 * math.sin(i / 20), bom=lambda i: i % 90 == 0)
        self.assertNotIn("loop", eventos)

    def test_lugar_novo_uma_vez_e_fica_salvo(self):
        self.assertEqual(self.rodar(1).count("lugar_novo"), 1)
        self.assertEqual(self.rodar(1).count("lugar_novo"), 0)
        de_novo = DetectoresPelaPosicao(self.d.arquivo_lugares)
        self.assertEqual(len(de_novo.lugares), 1)


if __name__ == "__main__":
    unittest.main()
