"""O olho da mosca: o que ela extrai de cada tela do jogo (versões 1, 2 e 3)."""

import numpy as np


OLHO = (90, 160)  # resolução da tela guardada na gravação e usada pelo olho


GRADE_OLHO = (18, 32)  # o olho junta a tela em blocos de 5 x 5 pixels


def reduzir(imagem, tamanho=OLHO):
    """Redimensiona (vizinho mais próximo) para `tamanho` = (altura, largura)."""
    h, w = imagem.shape[:2]
    linhas = np.linspace(0, h - 1, tamanho[0]).astype(int)
    colunas = np.linspace(0, w - 1, tamanho[1]).astype(int)
    return imagem[linhas][:, colunas]


def cinza(tela):
    """Tela RGB -> tons de cinza uint8 (o olho da mosca não usa cor)."""
    if tela.ndim == 2:
        return tela
    return (tela.astype(np.uint16).sum(axis=2) // 3).astype(np.uint8)


def ver(reduzida, anterior=None):
    """O que o olho da mosca entrega ao cérebro: brilho + movimento por bloco.

    `reduzida` é uma tela já em OLHO, colorida ou em cinza. Devolve um vetor
    float32 de 2 x 18 x 32.
    """
    reduzida, anterior = cinza(reduzida), None if anterior is None else cinza(anterior)
    cinza_ = reduzida.astype(np.float32) / 255
    gl, gc = GRADE_OLHO
    blocos = cinza_.reshape(gl, cinza_.shape[0] // gl, gc, cinza_.shape[1] // gc)
    brilho = blocos.mean(axis=(1, 3))
    if anterior is None:
        movimento = np.zeros_like(brilho)
    else:
        ant = anterior.astype(np.float32) / 255
        mov = np.abs(cinza_ - ant).reshape(blocos.shape).mean(axis=(1, 3))
        movimento = np.clip(mov * 6, 0, 1)
    return np.concatenate([brilho.ravel(), movimento.ravel()]).astype(np.float32)


FOVEA = (slice(30, 84), slice(32, 128))  # região do Cavaleiro em OLHO (90 x 160)


GRADE_FOVEA = (18, 24)  # blocos de 3 x 4 pixels


ATRASO_OLHO = 5  # quadros (~170 ms)


VERSAO_OLHO = 3  # a que o treinar.py usa agora; modelos antigos guardam a sua
# Os retratos (o que vai para o cache do treino) não mudaram da versão 2 para a
# 3: a memória é calculada a partir deles
VERSAO_RETRATO = 2


_N_PERIFERIA = 2 * GRADE_OLHO[0] * GRADE_OLHO[1]


_N_FOVEA = GRADE_FOVEA[0] * GRADE_FOVEA[1]


# Posições do brilho (periferia e fóvea) dentro de um retrato
BRILHO_RETRATO = np.r_[0 : _N_PERIFERIA // 2, _N_PERIFERIA : _N_PERIFERIA + _N_FOVEA]


def retrato(reduzida, anterior=None):
    """Tudo o que o olho extrai de um quadro: periferia (`ver`) + fóvea (brilho e
    movimento). As entradas de qualquer versão do olho saem daqui."""
    periferia = ver(reduzida, anterior)
    atual = cinza(reduzida)[FOVEA].astype(np.float32) / 255
    gl, gc = GRADE_FOVEA
    forma = (gl, atual.shape[0] // gl, gc, atual.shape[1] // gc)
    brilho = atual.reshape(forma).mean(axis=(1, 3))
    if anterior is None:
        movimento = np.zeros_like(brilho)
    else:
        ant = cinza(anterior)[FOVEA].astype(np.float32) / 255
        movimento = np.clip(np.abs(atual - ant).reshape(forma).mean(axis=(1, 3)) * 6, 0, 1)
    return np.concatenate([periferia, brilho.ravel(), movimento.ravel()]).astype(np.float32)


# --- memória (versão 3): o que ela viu nos últimos segundos ---
#
# Integradores lentos, como neurônios que somam a entrada e esquecem devagar:
# para cada constante de tempo em MEMORIA_S, uma média que esquece com
# exp(-dt/tau) do brilho da periferia (em blocos maiores, GRADE_MEMORIA) e do
# movimento médio. Comparando a cena de agora com a lembrada, a rede pode
# perceber que não está saindo do lugar (parada, presa, andando em círculos).
# De propósito sem as teclas que ela apertou: lembrar das próprias ações faz a
# imitação aprender só a repetir o que acabou de fazer.

MEMORIA_S = (1.0, 4.0)
GRADE_MEMORIA = (9, 16)
QUADRO_S = 0.033  # mesmo passo das gravações e do painel (QUADRO_MS)
_N_MEM_BRILHO = GRADE_MEMORIA[0] * GRADE_MEMORIA[1]
N_MEMORIA = len(MEMORIA_S) * (_N_MEM_BRILHO + 1)  # estado guardado


def _lembrado(atual):
    """O que entra na memória de um retrato: brilho da periferia em blocos
    grandes + movimento médio (aceita um quadro ou um lote)."""
    gl, gc = GRADE_OLHO
    ml, mc = GRADE_MEMORIA
    brilho = atual[..., : gl * gc].reshape(*atual.shape[:-1], ml, gl // ml, mc, gc // mc).mean(axis=(-3, -1))
    movimento = atual[..., gl * gc : 2 * gl * gc].mean(axis=-1, keepdims=True)
    return np.concatenate([brilho.reshape(*atual.shape[:-1], -1), movimento], axis=-1)


def _esquece(tau):
    return float(np.exp(-QUADRO_S / tau))


def lembrar(memoria, atual):
    """Um quadro a mais na memória (no painel). `memoria` None: a primeira."""
    x = _lembrado(atual).astype(np.float32)
    if memoria is None:
        return np.tile(x, len(MEMORIA_S))
    n = len(x)
    novo = memoria.copy()
    for k, tau in enumerate(MEMORIA_S):
        f = _esquece(tau)
        novo[k * n : (k + 1) * n] = f * memoria[k * n : (k + 1) * n] + (1 - f) * x
    return novo


def memorias_da_sessao(retratos):
    """A memória de cada quadro de uma sessão inteira (no treino), igual à que o
    painel teria quadro a quadro com `lembrar`."""
    from scipy.signal import lfilter

    x = _lembrado(retratos.astype(np.float32))
    partes = []
    for tau in MEMORIA_S:
        f = _esquece(tau)
        # y[t] = f * y[t-1] + (1 - f) * x[t], começando com y[0] = x[0]
        y, _ = lfilter([1 - f], [1, -f], x, axis=0, zi=(f * x[:1]))
        partes.append(y)
    return np.concatenate(partes, axis=-1).astype(np.float32)


def entrada(versao, atual, passado, memoria=None):
    """Entrada da rede a partir de retratos (aceita um quadro ou um lote).

    versão 1: só a periferia do quadro atual (olho dos treinos #1 a #4).
    versão 2: retrato atual + brilho de ATRASO_OLHO quadros atrás.
    versão 3: versão 2 + memória dos últimos segundos + o quanto a cena de agora
              difere da lembrada (uma medida por constante de tempo).
    """
    if versao == 1:
        return atual[..., :_N_PERIFERIA]
    v2 = np.concatenate([atual, passado[..., BRILHO_RETRATO]], axis=-1)
    if versao == 2:
        return v2
    agora = _lembrado(atual)
    n = agora.shape[-1]
    diferencas = [
        np.abs(agora[..., :-1] - memoria[..., k * n : (k + 1) * n - 1]).mean(axis=-1, keepdims=True)
        for k in range(len(MEMORIA_S))
    ]
    return np.concatenate([v2, memoria, *diferencas], axis=-1)


def tamanho_entrada(versao):
    vazio = np.zeros(_N_PERIFERIA + 2 * _N_FOVEA, dtype=np.float32)
    return entrada(versao, vazio, vazio, np.zeros(N_MEMORIA, np.float32)).shape[-1]
