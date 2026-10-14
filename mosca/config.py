"""Configuração: ações do jogo e suas teclas, tempos e caminhos dos arquivos."""

import collections
from pathlib import Path


# Todos os controles de jogo do Hollow Knight, com as teclas configuradas no jogo, mais
# o mapa rápido. Inventário e Esc ficam de fora: são menus que pausam o jogo.
#   tecla: keysym do X11 · rotulo: o que aparece no painel · curto: nome no botão
#   pata: pata que aperta a tecla · posicao: (linha, coluna) da tecla no teclado 3D
Acao = collections.namedtuple("Acao", "tecla rotulo curto pata posicao")


ACOES_JOGO = {
    "Esquerda": Acao("a", "A", "Esquerda", "lf", (1, 1)),
    "Direita": Acao("d", "D", "Direita", "rf", (1, -1)),
    "Cima": Acao("w", "W", "Cima", "lf", (2, 1)),
    "Baixo": Acao("s", "S", "Baixo", "rf", (2, -1)),
    "Pular": Acao("space", "Space", "Pulo", "lm", (0, 1)),
    "Atacar": Acao("h", "H", "Ataque", "rm", (0, -1)),
    "Esquiva": Acao("j", "J", "Esquiva", "lh", (-1, 1)),
    "Foco": Acao("k", "K", "Foco/Magia", "lm", (0, 2)),
    "Super Investida": Acao("l", "L", "S. Investida", "lh", (-1, 2)),
    "Ferrão dos Sonhos": Acao("n", "N", "Ferrão", "rh", (-1, -1)),
    "Magia Rápida": Acao("m", "M", "Magia Ráp.", "rm", (0, -2)),
    # Mapa rápido: segurado, mostra o mapa da área (com a Bússola Errante, onde o
    # Cavaleiro está). A mosca também olha o mapa sozinha de tempos em tempos.
    "Mapa": Acao("Tab", "Tab", "Mapa", "rh", (-1, -2)),
}


ACOES = list(ACOES_JOGO)


ROTULO_TECLA = {nome: a.rotulo for nome, a in ACOES_JOGO.items()}


OPOSTAS = [("Esquerda", "Direita"), ("Cima", "Baixo")]  # nunca apertadas juntas


# No Hollow Knight cada golpe precisa de um novo aperto: segurar a tecla dá um
# golpe só. Enquanto a mosca quer uma destas, a tecla é tocada a cada N segundos.
TOQUE_S = {"Atacar": 0.3, "Esquiva": 0.6, "Magia Rápida": 0.6}


DURACAO_TOQUE_S = 0.07


# O Foco só cura segurado por ~1 s: uma vez apertado, fica pelo menos isto
SEGURAR_MINIMO_S = {"Foco": 1.5, "Mapa": 1.5}


# E no máximo isto: com o mapa aberto a mosca vê o mapa e, como nas suas
# gravações o Tab está sempre apertado com o mapa na tela, continuaria segurando
# para sempre. Passou do máximo, solta e a tecla descansa por DESCANSO_S.
SEGURAR_MAXIMO_S = {"Mapa": 3.0}
DESCANSO_S = 10.0


QUADRO_MS = 33  # ~30 quadros por segundo


PASSOS_FISICA_POR_QUADRO = 50  # passos de física entre um quadro renderizado e outro


DURACAO_PULSO_S = 1.0


PASTA = Path(__file__).resolve().parent.parent  # raiz do projeto


PASTA_GRAVACOES = PASTA / "gravacoes"  # você jogando


PASTA_GRAVACOES_MOSCA = PASTA / "gravacoes_mosca"  # a mosca jogando sozinha


ARQUIVO_MODELO = PASTA / "modelo_mosca.npz"  # a campeã: a versão que joga


ARQUIVO_DESAFIANTE = PASTA / "modelo_desafiante.npz"  # treinada, ainda disputando


ARQUIVO_TORNEIO = PASTA / "torneio.json"  # placar da disputa (sobrevive a reabrir)
