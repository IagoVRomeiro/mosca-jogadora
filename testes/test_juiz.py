"""Juiz de dentro do jogo: estados do plugin (mod/MoscaEventos) viram eventos."""

import json
import socket
import tempfile
import time
import unittest
from pathlib import Path

from mosca.juiz import DetectoresPelaPosicao, JuizDoJogo, MemoriaDePerigos, eventos_entre


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

    def test_chefe_derrotado(self):
        self.assertEqual(eventos_entre(estado(), estado(inimigos_mortos=1, chefes_derrotados=1), LONGE),
                         ["inimigo_morto", "chefe_derrotado"])
        self.assertEqual(eventos_entre(estado(), estado(inimigos_mortos=1), LONGE), ["inimigo_morto"])

    def test_dano_no_chefe_a_cada_1_porcento(self):
        self.assertEqual(eventos_entre(estado(dano_chefe=5), estado(dano_chefe=31), LONGE), ["dano_chefe"] * 3)
        self.assertEqual(eventos_entre(estado(dano_chefe=31), estado(dano_chefe=39), LONGE), [])  # resto: 0,8%
        self.assertEqual(eventos_entre(estado(dano_chefe=39), estado(dano_chefe=40), LONGE), ["dano_chefe"])

    def test_sombra_recuperada(self):
        self.assertEqual(eventos_entre(estado(sombra=True, geo=0), estado(sombra=False, geo=300), LONGE),
                         ["geo", "sombra_recuperada"])
        # morrer de novo cria outra sombra; plugin antigo (sem o campo) não conta
        self.assertEqual(eventos_entre(estado(sombra=True), estado(sombra=True, vida=0, morta=True), LONGE), ["morte"])
        self.assertEqual(eventos_entre(estado(sombra=True), estado(), LONGE), [])

    def test_magia_pela_alma_gasta_de_uma_vez(self):
        self.assertEqual(eventos_entre(estado(alma=66), estado(alma=33), LONGE), ["magia"])
        self.assertEqual(eventos_entre(estado(alma=66, curando=True), estado(alma=33, curando=True), LONGE), [])
        self.assertEqual(eventos_entre(estado(alma=66), estado(alma=64), LONGE), [])  # aos poucos não
        self.assertEqual(eventos_entre(estado(alma=66, vida=2), estado(alma=33, vida=2), LONGE),
                         ["magia", "magia_com_vida_baixa"])

    def test_perder_no_salao_dos_deuses_e_morte(self):
        self.assertEqual(eventos_entre(estado(derrotas=2), estado(derrotas=3), LONGE), ["morte"])
        self.assertEqual(eventos_entre(estado(derrotas=3), estado(derrotas=3), LONGE), [])

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

    def test_inimigo_renascido_vale_pouco(self):
        self.mandar(mortos=[])
        self.assertEqual(self.mandar(inimigos_mortos=1, mortos=[[1, "Crawler 1"]]), ["inimigo_morto"])
        self.assertEqual(self.mandar(inimigos_mortos=2, mortos=[[1, "Crawler 1"], [2, "Climber 2"]]), ["inimigo_morto"])
        # saiu e voltou: o mesmo Crawler renasceu e morreu de novo
        self.assertEqual(self.mandar(inimigos_mortos=3, mortos=[[1, "Crawler 1"], [2, "Climber 2"], [3, "Crawler 1"]]),
                         ["inimigo_repetido"])
        # mesmo nome em outra sala é outro inimigo; vale entre sessões
        self.assertEqual(self.mandar(cena="Fungus2_13", inimigos_mortos=4, mortos=[[3, "Crawler 1"], [4, "Crawler 1"]]),
                         ["inimigo_morto", "cena_nova"])
        de_novo = JuizDoJogo(self.pasta / "cenas.json", porta=0)
        self.assertIn("Crossroads_01|Crawler 1", de_novo.inimigos)
        de_novo.fechar()

    def test_magia_sem_alvo_depois_de_um_tempo(self):
        import mosca.juiz as juiz
        juiz.MAGIA_ALVO_S, antigo = 0.05, juiz.MAGIA_ALVO_S
        try:
            self.mandar(alma=66)
            self.assertEqual(self.mandar(alma=33), ["magia"])
            time.sleep(0.06)
            self.assertEqual(self.mandar(alma=33), ["magia_sem_alvo"])
            self.mandar(alma=66, golpes=0)
            self.assertEqual(self.mandar(alma=33, golpes=0), ["magia"])
            self.assertEqual(self.mandar(alma=36, golpes=1), ["acerto"])  # acertou
            time.sleep(0.06)
            self.assertEqual(self.mandar(alma=36, golpes=1), [])
        finally:
            juiz.MAGIA_ALVO_S = antigo

    def test_lutas_do_salao_chegam_uma_vez(self):
        self.mandar(lutas=[[3, "GG_Statue_Gruz", "GG_Gruz_Mother", 1]])  # referência
        self.assertEqual(self.juiz.pegar_lutas(), [])
        self.mandar(lutas=[[3, "GG_Statue_Gruz", "GG_Gruz_Mother", 1], [4, "GG_Statue_Gruz", "GG_Gruz_Mother", 0]])
        self.mandar(lutas=[[3, "GG_Statue_Gruz", "GG_Gruz_Mother", 1], [4, "GG_Statue_Gruz", "GG_Gruz_Mother", 0]])
        self.assertEqual(self.juiz.pegar_lutas(), [("GG_Statue_Gruz", "GG_Gruz_Mother", False)])
        # panteão: sem estátua, com a sala de cada chefe
        self.mandar(lutas=[[5, "", "GG_Vengefly", 1], [6, "", "GG_Gruz_Mother", 0]])
        self.assertEqual(self.juiz.pegar_lutas(), [("", "GG_Vengefly", True), ("", "GG_Gruz_Mother", False)])

    def test_lutas_do_plugin_anterior_sem_a_sala(self):
        self.mandar(lutas=[[1, "GG_Statue_Gruz", 1]])
        self.mandar(lutas=[[1, "GG_Statue_Gruz", 1], [2, "GG_Statue_Gruz", 0]])
        self.assertEqual(self.juiz.pegar_lutas(), [("GG_Statue_Gruz", "", False)])

    def test_jogo_reaberto_recomeca_a_contagem_de_abates(self):
        self.mandar(inimigos_mortos=50, mortos=[[50, "Crawler 1"]])
        self.assertEqual(self.mandar(inimigos_mortos=1, mortos=[[1, "Climber 2"]]), [])  # contadores voltaram: só referência
        self.assertEqual(self.mandar(inimigos_mortos=2, mortos=[[1, "Climber 2"], [2, "Climber 2"]]), ["inimigo_morto"])

    def vai_e_volta(self, salas, **no_meio):
        eventos = []
        for i, sala in enumerate(salas):
            eventos += self.mandar(cena=sala, **(no_meio if i == 2 else {}))
        return eventos

    def test_indo_e_voltando_pela_mesma_passagem(self):
        self.juiz.cenas.update({"A", "B"})  # salas já conhecidas
        eventos = self.vai_e_volta(["A", "B", "A", "B", "A"])
        self.assertEqual(eventos.count("vai_e_volta"), 1)
        eventos = self.vai_e_volta(["B", "A"])  # mais um vai e volta: de novo
        self.assertEqual(eventos.count("vai_e_volta"), 1)

    def test_passando_por_varias_salas_nao_e_vai_e_volta(self):
        self.juiz.cenas.update({"A", "B", "C", "D"})
        self.assertNotIn("vai_e_volta", self.vai_e_volta(["A", "B", "C", "D", "C"]))

    def test_ganhando_algo_no_meio_nao_e_vai_e_volta(self):
        self.juiz.cenas.update({"A", "B"})
        self.mandar(cena="A")
        eventos = self.vai_e_volta(["B", "A", "B", "A"], inimigos_mortos=1)  # matou um inimigo no caminho
        self.assertNotIn("vai_e_volta", eventos)

    def test_renascer_nao_conta_como_passagem(self):
        self.juiz.cenas.update({"A", "B"})
        self.vai_e_volta(["A", "B", "A"])
        self.mandar(cena="A", vida=0, morta=True)
        self.assertNotIn("vai_e_volta", self.mandar(cena="B", vida=5))  # renasceu do outro lado

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
              jogo=lambda i: (), **outros):
        eventos = []
        for i in range(int(segundos * 30)):
            e = estado(x=x(i), y=y(i), vx=vx, **outros)
            eventos += self.d.passo(e, False, direita, bom(i), jogo(i))
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

    def test_sem_novidade_depois_de_1_min_e_a_cada_15_s(self):
        eventos = self.rodar(59)
        self.assertNotIn("sem_novidade", eventos)
        self.assertEqual(self.rodar(32).count("sem_novidade"), 3)  # 60 s, 75 s e 90 s

    def test_lutando_ou_no_salao_dos_deuses_nao_e_sem_novidade(self):
        self.assertNotIn("sem_novidade", self.rodar(90, jogo=lambda i: ("acerto",) if i % 150 == 0 else ()))
        self.assertNotIn("sem_novidade", self.rodar(90, cena="GG_Workshop"))

    def test_sala_conhecida_nao_e_novidade_mas_sala_nova_e(self):
        self.rodar(40)
        self.rodar(1, cena="Crossroads_02")  # outra sala: o pedaço dela é novo
        self.assertNotIn("sem_novidade", self.rodar(55, cena="Crossroads_02"))
        self.rodar(1)  # de volta à conhecida: nada novo, e o tempo não volta a zero
        self.assertIn("sem_novidade", self.rodar(5))

    def test_na_arena_ir_e_voltar_nao_e_loop(self):
        import math
        eventos = self.rodar(16, vx=8.0, x=lambda i: 10.0 + 6 * math.sin(i / 20), cena="GG_Mantis_Lords_V")
        self.assertNotIn("loop", eventos)

    def test_lugar_novo_uma_vez_e_fica_salvo(self):
        self.assertEqual(self.rodar(1).count("lugar_novo"), 1)
        self.assertEqual(self.rodar(1).count("lugar_novo"), 0)
        de_novo = DetectoresPelaPosicao(self.d.arquivo_lugares)
        self.assertEqual(len(de_novo.lugares), 1)


class TestePerigos(unittest.TestCase):
    def setUp(self):
        self.m = MemoriaDePerigos(Path(tempfile.mkdtemp()) / "perigos.json")

    def cair(self, x0=30.0, x1=40.0, y=7.4, lado=1, cena="GG_Mantis_Lords_V"):
        """Anda no chão de x0 até x1 e cai além da borda."""
        for i in range(30):
            self.m.passo(estado(cena=cena, x=x0 + (x1 - x0) * i / 29, y=y, no_chao=True), [])
        self.m.passo(estado(cena=cena, x=x1 + lado * 2, y=y - 0.5, no_chao=False), ["perigo"])

    def test_lembra_a_borda_e_veta_so_o_lado_dela(self):
        self.cair()
        perto = estado(cena="GG_Mantis_Lords_V", x=38.8, y=7.4)
        self.assertEqual(self.m.vetar(perto), {"Direita", "Esquiva"})
        self.assertEqual(self.m.vetar(estado(cena="GG_Mantis_Lords_V", x=30.0, y=7.4)), set())  # longe
        self.assertEqual(self.m.vetar(estado(cena="GG_Mantis_Lords_V", x=38.8, y=15.0)), set())  # outra altura
        self.assertEqual(self.m.vetar(estado(cena="Crossroads_01", x=38.8, y=7.4)), set())  # outra sala

    def test_a_mesma_borda_vira_uma_so_e_fica_salva(self):
        self.cair()
        self.cair(x1=40.4)
        self.assertEqual(len(self.m.bordas), 1)
        self.assertEqual(self.m.bordas[0][1], 40.0)  # fica a mais cautelosa
        self.cair(x0=30.0, x1=21.0, lado=-1)  # a borda do outro lado
        de_novo = MemoriaDePerigos(self.m.arquivo)
        self.assertEqual(len(de_novo.bordas), 2)
        self.assertEqual(de_novo.vetar(estado(cena="GG_Mantis_Lords_V", x=22.0, y=7.4)), {"Esquerda", "Esquiva"})

    def test_cair_de_cima_nao_marca_borda(self):
        for _ in range(30):
            self.m.passo(estado(cena="GG_Mantis_Lords_V", x=30.0, y=7.4, no_chao=True), [])
        self.m.passo(estado(cena="GG_Mantis_Lords_V", x=30.1, y=6.9, no_chao=False), ["perigo"])
        self.assertEqual(self.m.bordas, [])


if __name__ == "__main__":
    unittest.main()
