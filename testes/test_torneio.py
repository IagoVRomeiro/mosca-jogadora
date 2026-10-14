"""Torneio campeã x desafiante: quem vence, quem perde e quando não decidir."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from mosca.aprendizado import Torneio

QUADRO_S = 1 / 30


class TesteTorneio(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.campea = self.pasta / "campea.npz"
        self.desafiante = self.pasta / "desafiante.npz"
        self.campea.write_bytes(b"campea")
        self.desafiante.write_bytes(b"desafiante")

    def novo(self):
        return Torneio(self.pasta / "torneio.json", self.campea, self.desafiante)

    def disputar(self, t, por_minuto, limite_min=40):
        """Joga até o veredito. `por_minuto(papel, rodada)` dá a recompensa/min."""
        rodadas = {p: 0 for p in Torneio.PAPEIS}
        for _ in range(int(limite_min * 60 / QUADRO_S)):
            papel = t.quem_joga()
            # + um "evento" desprezível por quadro: no jogo sempre acontece algo (uma
            # rodada sem nenhum evento é jogo parado e não conta)
            trocou = t.contar(papel, QUADRO_S, por_minuto(papel, rodadas[papel]) / 60 * QUADRO_S + 1e-9)
            if trocou:
                rodadas[papel] += 1
            resultado = t.veredito()
            if resultado:
                minutos = {p: t.estado["placar"][p]["segundos"] / 60 for p in Torneio.PAPEIS}
                t.encerrar(resultado)
                return resultado, minutos
        return None, None

    def test_vence_quando_claramente_melhor(self):
        t = self.novo()
        resultado, minutos = self.disputar(t, lambda papel, _: -1.0 if papel == "desafiante" else -3.0)
        self.assertEqual(resultado, "venceu")
        self.assertEqual(self.campea.read_bytes(), b"desafiante")  # virou a campeã
        self.assertFalse(self.desafiante.exists())
        self.assertAlmostEqual(minutos["desafiante"], 4, delta=0.2)

    def test_perde_quando_pior(self):
        t = self.novo()
        resultado, _ = self.disputar(t, lambda papel, _: -3.0 if papel == "desafiante" else -1.0)
        self.assertEqual(resultado, "perdeu")
        self.assertEqual(self.campea.read_bytes(), b"campea")
        self.assertFalse(self.desafiante.exists())

    def test_empate_mantem_a_campea(self):
        t = self.novo()
        resultado, minutos = self.disputar(t, lambda papel, _: -2.0 if papel == "desafiante" else -2.1)
        self.assertEqual(resultado, "perdeu")  # sem diferença clara, a campeã fica
        self.assertAlmostEqual(minutos["desafiante"], Torneio.MAXIMO_S / 60, delta=0.2)
        self.assertEqual(self.campea.read_bytes(), b"campea")

    def test_nao_perde_por_azar(self):
        # começo ruim por azar (duas rodadas de -8) e depois bem melhor: com 4 min
        # a média ainda é negativa, mas a variação é grande demais para descartar
        def por_minuto(papel, rodada):
            if papel == "campea":
                return 0.0
            return -8.0 if rodada < 2 else 4.0
        _, minutos = self.disputar(self.novo(), por_minuto)
        self.assertGreater(minutos["desafiante"], 5)

    def test_na_frente_sem_certeza_ganha_mais_tempo(self):
        # um pouco melhor, mas com rodadas muito variáveis: aos 15 min ainda não
        # dá para ter certeza, então a disputa segue em vez de descartá-la
        def por_minuto(papel, rodada):
            ruido = (-12, 6, -2, 8, -10, 4)[rodada % 6]
            return ruido + (1.5 if papel == "desafiante" else 0.0)
        _, minutos = self.disputar(self.novo(), por_minuto, limite_min=80)
        self.assertGreater(minutos["desafiante"], Torneio.MAXIMO_S / 60 + 1)

    def test_rodada_sem_nada_nao_conta(self):
        t = self.novo()
        for _ in range(int(Torneio.RODADA_S / QUADRO_S) + 1):  # 1 min parado num menu
            t.contar("desafiante", QUADRO_S, 0.0)
        self.assertEqual(t.estado["rodadas"]["desafiante"], [])
        self.assertAlmostEqual(t.estado["placar"]["desafiante"]["segundos"], 0.0, places=3)

    def test_nao_vence_por_sorte(self):
        """Rodadas muito variáveis: a vantagem média não basta para vencer no mínimo."""
        sorte = np.random.default_rng(1).normal(0, 6, size=(2, 50))
        t = self.novo()
        rodadas = {p: 0 for p in Torneio.PAPEIS}
        primeiro_veredito = "nenhum"
        for _ in range(int(20 * 60 / QUADRO_S)):
            papel = t.quem_joga()
            media = -1.2 if papel == "desafiante" else -2.0  # desafiante 0,8/min melhor
            por_min = media + sorte[Torneio.PAPEIS.index(papel), rodadas[papel]]
            if t.contar(papel, QUADRO_S, por_min / 60 * QUADRO_S):
                rodadas[papel] += 1
            if min(len(t.estado["rodadas"][p]) for p in Torneio.PAPEIS) >= Torneio.MINIMO_RODADAS:
                primeiro_veredito = t.veredito()
                break
        self.assertNotEqual(primeiro_veredito, "venceu")
        self.assertGreater(2 * t.incerteza(), 0.8)

    def test_sem_campea_a_primeira_desafiante_assume(self):
        self.campea.unlink()
        t = self.novo()
        self.assertIsNotNone(t.nova_desafiante())
        self.assertEqual(self.campea.read_bytes(), b"desafiante")
        self.assertFalse(t.em_disputa)

    def test_placar_sobrevive_a_reabrir(self):
        t = self.novo()
        for _ in range(int(90 / QUADRO_S)):  # 1,5 min
            t.contar(t.quem_joga(), QUADRO_S, -0.01)
        t.fechar_rodada(t.quem_joga())
        reaberto = self.novo()
        self.assertEqual(reaberto.estado["placar"], t.estado["placar"])
        self.assertEqual(reaberto.estado["rodadas"], t.estado["rodadas"])

    def test_desafiante_nova_feita_fora_do_painel_zera_o_placar(self):
        import json
        (self.pasta / "desafiante.json").write_text(json.dumps({"treino_id": 8}))
        t = self.novo()
        for _ in range(int(90 / QUADRO_S)):
            t.contar(t.quem_joga(), QUADRO_S, -0.01)
        t.salvar()
        self.assertGreater(self.novo().estado["placar"]["campea"]["segundos"], 0)  # mesma: mantém
        (self.pasta / "desafiante.json").write_text(json.dumps({"treino_id": 9}))
        reaberto = self.novo()
        self.assertEqual(reaberto.estado["placar"]["campea"]["segundos"], 0)
        self.assertEqual(reaberto.estado["desafiante_id"], 9)

    def test_rodada_interrompida_curta_nao_conta(self):
        t = self.novo()
        for _ in range(int(10 / QUADRO_S)):  # 10 s e desligou
            t.contar("desafiante", QUADRO_S, 0.0)
        t.fechar_rodada("desafiante")
        self.assertEqual(t.estado["rodadas"]["desafiante"], [])


if __name__ == "__main__":
    unittest.main()
