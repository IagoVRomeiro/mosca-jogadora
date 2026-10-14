"""Juiz de dentro do jogo: estados do plugin (mod/MoscaEventos) viram eventos."""

import json
import socket
import tempfile
import time
import unittest
from pathlib import Path

from mosca.juiz import JuizDoJogo, eventos_entre


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

    def test_eventos_pela_rede(self):
        self.mandar()
        self.assertEqual(self.mandar(vida=4, golpes=1), ["dano", "acerto"])

    def test_no_menu_nao_esta_ativo(self):
        self.mandar(cena="Menu_Title")
        self.assertFalse(self.juiz.ativo)


if __name__ == "__main__":
    unittest.main()
