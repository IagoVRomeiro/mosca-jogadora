"""Explorador de salas: passagens de sala, salas repetidas e a memória entre sessões."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from mosca.estimulos import ExploradorSalas, LeitorHUD


def sala(semente):
    """Uma "sala": padrão fixo de claro e escuro (em OLHO, 90 x 160)."""
    rng = np.random.default_rng(semente)
    blocos = rng.integers(20, 200, (18, 32))
    return np.repeat(np.repeat(blocos, 5, 0), 5, 1).astype(np.uint8)


ESCURA = np.zeros((90, 160), np.uint8)


def passar(explorador, sequencia):
    eventos = []
    for tela, quadros in sequencia:
        for _ in range(quadros):
            eventos += explorador.passo(tela)
    return eventos


class TesteExploracao(unittest.TestCase):
    def setUp(self):
        self.arquivo = Path(tempfile.mkdtemp()) / "salas.npz"

    def test_entrar_numa_sala_nova(self):
        e = ExploradorSalas(self.arquivo)
        self.assertEqual(passar(e, [(sala(1), 30), (ESCURA, 24), (sala(2), 40)]), ["sala_nova"])
        self.assertEqual(e.salas, 1)

    def test_voltar_para_sala_conhecida_nao_conta(self):
        e = ExploradorSalas(self.arquivo)
        passar(e, [(sala(1), 30), (ESCURA, 24), (sala(2), 260)])
        self.assertEqual(passar(e, [(ESCURA, 24), (sala(3), 260), (ESCURA, 24), (sala(2), 260)]), ["sala_nova"])
        self.assertEqual(e.salas, 2)

    def test_entrar_e_sair_rapido_nao_da_recompensa(self):
        """Porta giratória: salas trocando a cada ~2 s não valem recompensa."""
        e = ExploradorSalas(self.arquivo)
        passar(e, [(sala(1), 30), (ESCURA, 24), (sala(2), 260)])  # chegou devagar
        eventos = passar(e, [(ESCURA, 24), (sala(3), 40), (ESCURA, 24), (sala(4), 40),
                             (ESCURA, 24), (sala(5), 40)])
        self.assertEqual(eventos, ["sala_nova"])  # só a 3, que veio 8 s depois da 2
        self.assertEqual(e.salas, 4)  # mas ela lembra das salas 4 e 5

    def test_escuro_longo_nao_e_passagem_de_sala(self):
        e = ExploradorSalas(self.arquivo)  # morte ou banco: escuro bem mais longo
        self.assertEqual(passar(e, [(sala(1), 30), (ESCURA, 120), (sala(2), 40)]), [])

    def test_sem_escurecer_nao_e_sala_nova(self):
        e = ExploradorSalas(self.arquivo)
        self.assertEqual(passar(e, [(sala(1), 30), (sala(2), 30), (sala(3), 30)]), [])

    def test_memoria_vale_entre_sessoes(self):
        e = ExploradorSalas(self.arquivo)
        passar(e, [(sala(1), 30), (ESCURA, 24), (sala(2), 40)])
        e.salvar()
        de_novo = ExploradorSalas(self.arquivo)
        self.assertEqual(de_novo.salas, 1)
        self.assertEqual(passar(de_novo, [(ESCURA, 24), (sala(2), 40)]), [])

    def test_recompensa(self):
        self.assertGreater(LeitorHUD.RECOMPENSA["sala_nova"], 0)


if __name__ == "__main__":
    unittest.main()
