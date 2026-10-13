"""O olho da mosca: o que ela extrai de cada tela do jogo (versões 1 e 2)."""

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


VERSAO_OLHO = 2  # a que o treinar.py usa agora; modelos antigos guardam a sua


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


def entrada(versao, atual, passado):
    """Entrada da rede a partir de retratos (aceita um quadro ou um lote).

    versão 1: só a periferia do quadro atual (olho dos treinos #1 a #4).
    versão 2: retrato atual + brilho de ATRASO_OLHO quadros atrás.
    """
    if versao == 1:
        return atual[..., :_N_PERIFERIA]
    return np.concatenate([atual, passado[..., BRILHO_RETRATO]], axis=-1)


def tamanho_entrada(versao):
    vazio = np.zeros(_N_PERIFERIA + 2 * _N_FOVEA, dtype=np.float32)
    return entrada(versao, vazio, vazio).shape[-1]
