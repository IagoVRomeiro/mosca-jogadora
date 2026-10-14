"""Configuração: ações do jogo e suas teclas, tempos e caminhos dos arquivos."""

import collections
from pathlib import Path


# Todos os controles de jogo do Hollow Knight, com as teclas configuradas no jogo.
# Mapa (Tab), inventário e Esc ficam de fora: a mosca não usa o que vê neles e
# eles a fazem parar de jogar.
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
    # A mesma tecla K faz duas coisas no jogo: segurada cura (Foco), tocada solta
    # a magia. Para a mosca são duas ações, que nunca vão juntas (OPOSTAS)
    "Foco": Acao("k", "K", "Foco", "lm", (0, 2)),
    "Magia": Acao("k", "K", "Magia", "lm", (0, 2)),
    "Super Investida": Acao("l", "L", "S. Investida", "lh", (-1, 2)),
    "Ferrão dos Sonhos": Acao("n", "N", "Ferrão", "rh", (-1, -1)),
    "Magia Rápida": Acao("m", "M", "Magia Ráp.", "rm", (0, -2)),
}


ACOES = list(ACOES_JOGO)


ROTULO_TECLA = {nome: a.rotulo for nome, a in ACOES_JOGO.items()}


OPOSTAS = [("Esquerda", "Direita"), ("Cima", "Baixo"), ("Foco", "Magia")]  # nunca apertadas juntas


# No Hollow Knight cada golpe precisa de um novo aperto: segurar a tecla dá um
# golpe só. Enquanto a mosca quer uma destas, a tecla é tocada a cada N segundos.
TOQUE_S = {"Atacar": 0.3, "Esquiva": 0.6, "Magia": 0.6, "Magia Rápida": 0.6}


DURACAO_TOQUE_S = 0.07


# O Foco só cura segurado por ~1 s: uma vez apertado, fica pelo menos isto
SEGURAR_MINIMO_S = {"Foco": 1.5}


# E no máximo isto: segurar o pulo mais que isso não pula mais alto, e para pular
# de novo agarrada na parede (Garra de Louva-a-deus) é preciso soltar e apertar.
# Passou do máximo, solta por SOLTO_S e aperta de novo se ela ainda quiser.
# Medido nas suas gravações: 95% dos pulos duram até 0,5 s, 99% até 0,63 s.
SEGURAR_MAXIMO_S = {"Pular": 0.6}
SOLTO_S = 0.1


QUADRO_MS = 33  # ~30 quadros por segundo


PASSOS_FISICA_POR_QUADRO = 50  # passos de física entre um quadro renderizado e outro


DURACAO_PULSO_S = 1.0


PASTA = Path(__file__).resolve().parent.parent  # raiz do projeto


PASTA_GRAVACOES = PASTA / "gravacoes"  # você jogando


PASTA_GRAVACOES_MOSCA = PASTA / "gravacoes_mosca"  # a mosca jogando sozinha


ARQUIVO_MODELO = PASTA / "modelo_mosca.npz"  # a campeã: a versão que joga


ARQUIVO_DESAFIANTE = PASTA / "modelo_desafiante.npz"  # treinada, ainda disputando


ARQUIVO_TORNEIO = PASTA / "torneio.json"  # placar da disputa (sobrevive a reabrir)
