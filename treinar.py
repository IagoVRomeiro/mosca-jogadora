"""Treina a mosca com as partidas gravadas (suas e dela), pesando pela vantagem.

Uso:
    .venv-flygym/bin/python treinar.py

Lê tudo em gravacoes/ (gravado com o botão "⏺ Gravar" do painel), ensina a
rede olho -> interneurônios -> zonas de comando a prever, para cada tela, quais
teclas você estava apertando, e salva em modelo_mosca.npz. O painel carrega o
modelo ao abrir.

Imitação ponderada pela vantagem (AWR): cada quadro tem um retorno, a soma
descontada das recompensas seguintes (dano, morte, parada, presa, acerto, geo,
sala nova; um evento a ~3 s conta pela metade). Um estimador aprende o retorno
esperado para cada tipo de tela; o peso do quadro é "foi melhor ou pior que o
esperado ali". Assim, num trecho difícil a mosca ainda aprende o que fazer de
melhor ali, em vez de só "não estar ali". É o papel da dopamina: o sinal é a
surpresa (recompensa acima ou abaixo do esperado), não a recompensa em si.

O "olho" de cada sessão fica guardado em cache_olho/: só sessões novas ou
alteradas são recalculadas.
"""

import os

# Metade dos núcleos (antes do numpy carregar): o resto fica para o jogo e o
# painel, que costumam estar abertos enquanto o treino roda
THREADS = str(max(1, (os.cpu_count() or 2) // 2))
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_var] = THREADS

import argparse
import hashlib
import json
import shutil
import sys
import subprocess
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np

from mosca.config import ACOES, ARQUIVO_DESAFIANTE, ARQUIVO_MODELO, PASTA, PASTA_GRAVACOES, PASTA_GRAVACOES_MOSCA, QUADRO_MS, TOQUE_S
from mosca.conectoma import CAMADAS_CONECTOMA, RedeConectoma, carregar_conectoma
from mosca.estimulos import DetectorLoop, DetectorPresa, ExploradorSalas, LeitorHUD
from mosca.olho import (
    ATRASO_OLHO, FOVEA, GRADE_FOVEA, GRADE_OLHO, MEMORIA_S, OLHO, VERSAO_OLHO, VERSAO_RETRATO, entrada,
    espelhar, espelhar_memoria, memorias_da_sessao, retrato,
)
from registro import registrar_treino

INTERNEURONIOS = 64
EPOCAS = 40
EPOCAS_CONECTOMA = 20  # a rede do conectoma é maior: ~20 s por época
PACIENCIA = 3  # para depois de tantas épocas sem melhorar na validação
# Partindo de uma versão já treinada: ela só vira desafiante se a validação
# melhorar pelo menos isto em relação ao ponto de partida (senão "nada novo
# aprendido" e nenhuma disputa); e aprende com passo menor, para ajustar sem
# desmanchar o que já sabia
MELHORA_MINIMA = 0.002
TAXA_AJUSTE = 3e-4
PRIMEIRA_CAMADA = {"mlp": ("w1", "b1"), "conectoma": ("A", "a")}
I_ESQ, I_DIR = ACOES.index("Esquerda"), ACOES.index("Direita")
ULTIMA_CAMADA = {"mlp": ("w2", "b2"), "conectoma": ("R", "r")}  # uma coluna por ação
NADA_NOVO = 3  # código de saída: treinou e não aprendeu nada mensurável
# Especialista de uma arena (--especialista CENA): só os quadros dela
PASTA_ESPECIALISTAS = PASTA / "especialistas"
MINIMO_QUADROS_ESPECIALISTA = 1800  # 1 min de luta na arena, entre treino e validação
LOTE = 256
TAXA = 1e-3
VALIDACAO = 0.2  # o fim de cada sessão fica de fora do treino, para medir de verdade
MINIMO_QUADROS = 300
PESO_MAXIMO = 3  # peso máximo das teclas raras (ver treinar)
# Habilidades usadas em toques raros (~1% dos quadros): com o teto de 3x a rede
# aprende "na dúvida, não solta" e a magia quase nunca sai. Podem pesar mais
HABILIDADES_RARAS = {"Magia", "Magia Rápida", "Super Investida", "Ferrão dos Sonhos"}
PESO_MAXIMO_HABILIDADE = 15.0
# Exceções ao teto: a Magia a 15x passou do ponto (ela tocava a magia 11% do
# tempo nas arenas e gastava toda a alma), e o Foco a 3x curava pouco (1% do
# tempo contra os seus 6%; 0,01 cura por minuto contra 2,7). Até 21/10: 15 e 3
PESO_MAXIMO_POR_TECLA = {"Magia": 5.0, "Foco": 6.0}
DESCONTO = 0.993  # por quadro: um evento a ~3 s (100 quadros) conta pela metade
FORCA_VANTAGEM = 1.0  # peso = exp(FORCA x vantagem em desvios-padrão), limitado
PESO_QUADRO = (0.25, 4.0)  # mínimo e máximo do peso de um quadro
REGULARIZACAO_VALOR = 0.05  # do estimador de retorno (por quadro de treino)
SUBAMOSTRA = 2  # usa 1 a cada 2 quadros: vizinhos são quase iguais (menos decoreba)
RUIDO = 0.1  # ruído nas entradas (já normalizadas) durante o treino
PASTA_CACHE = PASTA / "cache_olho"
VERSAO_CACHE = 10  # mude se o que vai no cache mudar
ARQUIVO_SAIDA = ARQUIVO_DESAFIANTE  # todo treino gera uma desafiante (ver jogar.Torneio)
ARQUIVO_INFO_MODELO = ARQUIVO_SAIDA.with_suffix(".json")  # qual treino gerou o modelo
# Partidas da própria mosca: entram com menos peso que as suas (ela erra mais) e
# só as mais recentes, para o treino não crescer sem fim
PESO_MOSCA = 0.5
# Correção ao vivo (você assumiu quando a mosca errou): mostra o certo
# justamente onde ela erra, mas não tanto que uma correção ruim domine
PESO_CORRECAO = 1.5
# Quadros julgados pela tela (sem o plugin do jogo): a leitura perdia a maioria
# dos golpes e não via inimigo morto, então ensinam o contrário das novas. Ainda
# ensinam a se mover; nas recompensas, pesam menos
PESO_TELA = 0.5
# Metade de cada lote do treino vai espelhada (Esquerda <-> Direita): o jogo é de
# rolagem lateral, e assim cada minuto gravado vale quase por dois
ESPELHAR = 0.5
RECOMPENSA_SALA = LeitorHUD.RECOMPENSA["sala_nova"]
RECOMPENSA_PRESA = LeitorHUD.RECOMPENSA["presa"]
RECOMPENSA_MORTE = LeitorHUD.RECOMPENSA["morte"]
RECOMPENSA_LOOP = LeitorHUD.RECOMPENSA["loop"]
RECOMPENSA_DANO = LeitorHUD.RECOMPENSA["dano"]
# Gravações sem as marcas de dano/morte foram feitas com estes valores
DANO_ANTIGO, MORTE_ANTIGA = -1.0, -3.0
# Partidas recentes da mosca em cada treino: ~1,5 h (era ~33 min). Com o juiz de
# dentro do jogo as recompensas delas são exatas e valem mais; cada quadro ocupa
# ~4 KB no treino (1,5 h a mais ~ +0,4 GB, cabe com o jogo e o painel abertos)
MAXIMO_QUADROS_MOSCA = 162_000
# Telas das partidas da mosca mais antigas que isto são apagadas (as teclas e
# recompensas delas ficam no Supabase). As suas gravações nunca são apagadas.
GUARDAR_QUADROS_MOSCA = 2 * MAXIMO_QUADROS_MOSCA


def commit_do_codigo():
    """Commit do git do código, para rodar esta versão da mosca no futuro.
    "+mudancas" se jogar.py/treinar.py tinham edições ainda não commitadas."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PASTA, capture_output=True, text=True, check=True
        ).stdout.strip()
        sujo = subprocess.run(
            ["git", "status", "--porcelain", "jogar.py", "treinar.py", "mosca"], cwd=PASTA,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return commit + ("+mudancas" if sujo else "")
    except (OSError, subprocess.CalledProcessError):
        return None


# Salas do Salão dos Deuses que não são arenas de chefe
SALAO_SEM_CHEFE = {"GG_Atrium", "GG_Atrium_Roof", "GG_Workshop", "GG_Spa", "GG_Engine", "GG_Engine_Prime",
                   "GG_Engine_Root", "GG_Unlock", "GG_Boss_Door_Entrance", "GG_End_Sequence", "GG_Blue_Room",
                   "GG_Wyrm", "GG_Unn", "GG_Waterways", "GG_Pipeway", "GG_Door_5_Finale", "GG_Land_of_Storms",
                   "GG_Entrance_Cutscene"}


def cenas_e_mortes_sem_chefe(parte, n):
    """Sala e inimigos mortos por quadro de uma parte gravada pelo plugin que não
    contou chefes (plugin anterior ao 'chefes_derrotados': a coluna não existe ou
    veio toda zerada). Nas outras: vazio."""
    if "eventos" not in parte.files or "jogo_cena" not in parte.files:
        return [""] * n, np.zeros(n, np.int8)
    nomes = [str(x) for x in parte["eventos_nomes"]]
    if "inimigo_morto" not in nomes or ("chefe_derrotado" in nomes
                                        and parte["eventos"][:, nomes.index("chefe_derrotado")].any()):
        return [""] * n, np.zeros(n, np.int8)
    salas = [str(c) for c in parte["jogo_cenas"]]
    return ([salas[i] if i >= 0 else "" for i in parte["jogo_cena"]],
            parte["eventos"][:, nomes.index("inimigo_morto")].astype(np.int8))


def chefes_do_salao(r, cenas, mortes):
    """Chefe vencido nas gravações sem a contagem: em cada passagem por uma
    arena do Salão dos Deuses (GG_*), a última morte é a do chefe (os ajudantes
    que ele invoca, como as vingamoscas, morrem antes)."""
    valor = LeitorHUD.RECOMPENSA.get("chefe_derrotado", 0.0)
    i = 0
    while i < len(cenas):
        j = i
        while j < len(cenas) and cenas[j] == cenas[i]:
            j += 1
        if cenas[i].startswith("GG_") and cenas[i] not in SALAO_SEM_CHEFE:
            mortos = np.flatnonzero(mortes[i:j])
            if len(mortos):
                r[i + mortos[-1]] += valor
        i = j
    return r


MAGIA_QUADROS = 11  # K apertado menos que isto (~0,35 s) foi magia; mais, foco (cura)


def separar_magia(teclas):
    """O K faz duas coisas: tocado, magia; segurado, foco. Nas gravações ele vem
    todo como "Foco": os toques curtos passam para "Magia"."""
    f, m = ACOES.index("Foco"), ACOES.index("Magia")
    k = np.r_[0, (teclas[:, f] > 0.5).astype(int), 0]
    d = np.diff(k)
    for ini, fim in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if fim - ini < MAGIA_QUADROS:
            teclas[ini:fim, f], teclas[ini:fim, m] = 0, 1
    return teclas


def fases_de_toque(teclas):
    """Ataque, esquiva e magia são toques de poucos quadros: marca como "fase"
    os TOQUE_S seguintes a cada toque. A rede aprende QUANDO atacar (e o painel
    repete os toques), em vez de tentar acertar o quadro exato do toque."""
    teclas = teclas.copy()
    for acao, intervalo in TOQUE_S.items():
        j = ACOES.index(acao)
        janela = max(1, round(intervalo * 1000 / QUADRO_MS))
        soma = np.concatenate([[0], np.cumsum(teclas[:, j] > 0.5)])
        inicio = np.maximum(np.arange(len(teclas)) + 1 - janela, 0)
        teclas[:, j] = (soma[1:] - soma[inicio]) > 0
    return teclas


def retornos(recompensas):
    """Retorno de cada quadro: soma das recompensas seguintes, descontada."""
    futura = np.zeros(len(recompensas), dtype=np.float32)
    acumulada = 0.0
    for i in range(len(recompensas) - 1, -1, -1):
        acumulada = recompensas[i] + DESCONTO * acumulada
        futura[i] = acumulada
    return futura


def versao_do_codigo():
    """Impressão digital do código que treina e roda a mosca (muda a cada edição)."""
    h = hashlib.sha256()
    for arquivo in [PASTA / "jogar.py", PASTA / "treinar.py", *sorted((PASTA / "mosca").glob("*.py"))]:
        h.update(arquivo.read_bytes())
    return h.hexdigest()[:12]


def cenas_da_sessao(pasta):
    """A sala (cena do jogo) de cada quadro de uma gravação ("" sem o plugin). Lê
    só a coluna da sala, não as telas."""
    cenas = []
    for arquivo in sorted(Path(pasta).glob("parte_*.npz")):
        with np.load(arquivo) as parte:
            n = len(parte["teclas"])
            if "jogo_cena" not in parte.files:
                cenas += [""] * n
                continue
            nomes = [str(c) for c in parte["jogo_cenas"]]
            cenas += [nomes[i] if i >= 0 else "" for i in parte["jogo_cena"]]
    return np.array(cenas)


def pastas_da_arena(cena):
    """Todas as gravações (suas e dela, mesmo as antigas ainda guardadas) que
    passaram pela arena, com a sala de cada quadro."""
    todas = {p.name: p for p in sorted(PASTA_GRAVACOES.glob("*")) if p.is_dir()}
    todas |= {f"mosca_{p.name}": p for p in sorted(PASTA_GRAVACOES_MOSCA.glob("*")) if p.is_dir()}
    pastas, cenas = {}, {}
    for nome, pasta in sorted(todas.items(), key=lambda item: item[1].name):
        c = cenas_da_sessao(pasta)
        if (c == cena).any():
            pastas[nome], cenas[nome] = pasta, c
    return pastas, cenas


def so_a_arena(dados, nomes, cenas, cena):
    """Treino e validação só com os quadros da arena (a memória e o "antes" de cada
    quadro continuam vindo da gravação inteira)."""
    na_arena = np.concatenate([cenas[n] == cena for n in nomes])
    if len(na_arena) != len(dados.retratos):
        raise SystemExit("as salas não batem com os quadros da gravação (cache antigo?)")
    dados.treino = dados.treino[na_arena[dados.treino]]
    dados.valid = dados.valid[na_arena[dados.valid]]


def pastas_de_sessoes():
    """{nome no registro: pasta}: as suas gravações e as partidas mais recentes
    da mosca (nome "mosca_<data>"), até MAXIMO_QUADROS_MOSCA."""
    pastas = {p.name: p for p in sorted(PASTA_GRAVACOES.glob("*")) if p.is_dir()}
    quadros = 0
    for p in sorted((p for p in PASTA_GRAVACOES_MOSCA.glob("*") if p.is_dir()), reverse=True):
        if quadros >= MAXIMO_QUADROS_MOSCA:
            break
        for arquivo in p.glob("parte_*.npz"):
            with np.load(arquivo) as parte:
                quadros += len(parte["teclas"])
        pastas[f"mosca_{p.name}"] = p
    # em ordem cronológica (a memória de salas depende da ordem em que foram vistas)
    return dict(sorted(pastas.items(), key=lambda item: item[1].name))


def limpar_partidas_antigas_da_mosca():
    """Apaga as telas das partidas da mosca além de GUARDAR_QUADROS_MOSCA (as mais antigas)."""
    quadros, apagadas = 0, []
    for p in sorted((p for p in PASTA_GRAVACOES_MOSCA.glob("*") if p.is_dir()), reverse=True):
        if quadros >= GUARDAR_QUADROS_MOSCA:
            shutil.rmtree(p)
            apagadas.append(p.name)
            continue
        for arquivo in p.glob("parte_*.npz"):
            with np.load(arquivo) as parte:
                quadros += len(parte["teclas"])
    return apagadas


def _chave_da_sessao(pasta):
    """Muda se alguma parte da gravação, o olho ou as ações mudarem."""
    h = hashlib.sha256(f"{VERSAO_CACHE}|{VERSAO_RETRATO}|{','.join(ACOES)}".encode())
    for arquivo in sorted(pasta.glob("parte_*.npz")):
        info = arquivo.stat()
        h.update(f"{arquivo.name}|{info.st_size}|{info.st_mtime_ns}".encode())
    return h.hexdigest()


def processar_sessao(pasta):
    """O que o treino precisa de uma gravação, do cache se já foi calculado:
    retratos (olho), teclas (com as fases de toque), recompensa do HUD, punição
    por ficar presa, entradas de sala (para a memória de salas) e se as salas
    novas já vieram marcadas na gravação."""
    PASTA_CACHE.mkdir(exist_ok=True)
    cache = PASTA_CACHE / f"{pasta.parent.name}_{pasta.name}.npz"
    chave = _chave_da_sessao(pasta)
    if cache.exists():
        with np.load(cache) as dados:
            if str(dados["chave"]) == chave:
                return {k: dados[k] for k in dados.files}
    olhos, teclas, hud, presas, marcadas, pelo_jogo = [], [], [], [], [], []
    cenas_quadro, mortes_quadro = [], []  # para achar chefes em gravações sem a contagem deles
    entradas_idx, entradas_sig = [], []
    com_hud = True
    presa = DetectorPresa()  # recalculada nas gravações antigas, que não marcam
    loop = DetectorLoop()  # idem
    salas = ExploradorSalas(Path(os.devnull + ".npz"))  # só para achar as entradas
    i_esq, i_dir = ACOES.index("Esquerda"), ACOES.index("Direita")
    for arquivo in sorted(pasta.glob("parte_*.npz")):
        with np.load(arquivo) as parte:
            n = len(parte["teclas"])
            if "recompensas" in parte.files:
                r = parte["recompensas"].astype(np.float32)
                if "versao_hud" not in parte.files:
                    # Leitura antiga: mapa aberto e transições viravam "morte" falsa
                    # (-3). Não dá para separar das reais: tira a morte e fica o resto
                    r = np.where(r <= MORTE_ANTIGA + 0.1, r - MORTE_ANTIGA, r)
                hud.append(r)
            else:
                com_hud = False
                hud.append(np.zeros(n, np.float32))
            acoes = [str(a) for a in parte["acoes"]]
            colunas = [acoes.index(a) if a in acoes else None for a in ACOES]
            presas_marcadas = "presas" in parte.files
            loops_marcados = "loops" in parte.files
            if "eventos" in parte.files:
                reponderar(hud[-1], parte)  # gravação nova: exato, evento a evento
            else:
                if "recompensas" in parte.files:
                    piscadas = tirar_piscadas_da_vida(hud[-1], parte)
                    ajustar_dano_e_morte(hud[-1], parte, piscadas)
                # gravações marcadas já trazem a punição na recompensa, com o valor da
                # época (-0,3 antes de valor_presa/valor_loop existirem): acerta para o atual.
                # A presa sai toda e é recalculada abaixo com o detector atual (que não
                # pune mais a escalada de parede)
                if presas_marcadas:
                    gravado = float(parte["valor_presa"]) if "valor_presa" in parte.files else -0.3
                    hud[-1] -= gravado * parte["presas"]
                if loops_marcados:
                    gravado = float(parte["valor_loop"]) if "valor_loop" in parte.files else -0.3
                    hud[-1] += (RECOMPENSA_LOOP - gravado) * parte["loops"]
            marcadas.append(np.full(n, "salas_novas" in parte.files))
            pelo_jogo.append(quadros_com_plugin(parte) if "eventos" in parte.files else np.zeros(n, bool))
            cenas, mortes = cenas_e_mortes_sem_chefe(parte, n)
            cenas_quadro += cenas
            mortes_quadro.append(mortes)
            anterior = None
            # presa pela posição real (plugin) já está na recompensa; só sem ele pela tela
            presa_pela_tela = ~quadros_com_plugin(parte) if "eventos" in parte.files else np.ones(n, bool)
            for tela, apertadas, r_hud, pela_tela in zip(parte["telas"], parte["teclas"], hud[-1], presa_pela_tela):
                olhos.append(retrato(tela, anterior).astype(np.float16))
                t = [bool(apertadas[c]) if c is not None else False for c in colunas]
                teclas.append(t)
                ficou_presa = bool(presa.passo(tela, t[i_esq], t[i_dir], True))
                em_loop = bool(loop.passo(tela, r_hud > 0, True))
                presas.append((RECOMPENSA_PRESA if ficou_presa and pela_tela else 0.0)
                              + (RECOMPENSA_LOOP if em_loop and not loops_marcados else 0.0))
                assinatura = salas.entrada_de_sala(tela)
                if assinatura is not None:
                    entradas_idx.append(len(olhos) - 1)
                    entradas_sig.append(assinatura)
                anterior = tela
    dados = {
        "chave": np.array(chave),
        "retratos": np.stack(olhos) if olhos else np.zeros((0, 2016), np.float16),
        "teclas": fases_de_toque(separar_magia(np.array(teclas, dtype=np.float32).reshape(-1, len(ACOES)))),
        "hud": chefes_do_salao(np.concatenate(hud).astype(np.float32), cenas_quadro, np.concatenate(mortes_quadro))
        if hud else np.zeros(0, np.float32),
        "com_hud": np.array(com_hud and bool(hud)),
        "presa": np.array(presas, dtype=np.float32),
        "pelo_jogo": np.concatenate(pelo_jogo) if pelo_jogo else np.zeros(0, bool),
        "marcadas": np.concatenate(marcadas) if marcadas else np.zeros(0, bool),
        "entradas_idx": np.array(entradas_idx, dtype=np.int64),
        "entradas_sig": np.array(entradas_sig, dtype=np.float32).reshape(-1, 576),
    }
    temporario = cache.with_name(cache.stem + ".tmp.npz")
    np.savez(temporario, **dados)
    os.replace(temporario, cache)
    return dados


def quadros_com_plugin(parte):
    """Quadros em que o plugin do jogo estava ativo (presa veio da posição real)."""
    if "jogo_x" not in parte.files:
        return np.zeros(len(parte["teclas"]), bool)
    return ~np.isnan(parte["jogo_x"])


def reponderar(r, parte):
    """Gravação com a contagem de eventos por quadro e os pesos da época: tira
    de `r` o valor antigo de cada evento e põe o atual. A presa dos quadros sem
    plugin sai e não volta aqui: é recalculada pelo detector atual da tela."""
    nomes = [str(n) for n in parte["eventos_nomes"]]
    gravados = parte["valores"].astype(np.float32)
    atuais = np.array([LeitorHUD.RECOMPENSA.get(n, 0.0) for n in nomes], np.float32)
    contagens = parte["eventos"].astype(np.float32)
    r += contagens @ (atuais - gravados)
    if "presa" in nomes:
        i = nomes.index("presa")
        r -= contagens[:, i] * atuais[i] * ~quadros_com_plugin(parte)


PISCADA_QUADROS = 30  # vida que muda e volta em menos de 1 s não foi dano nem cura
RECOMPENSA_CURA_GRAVADA = 0.3  # a cura sempre valeu isto


def tirar_piscadas_da_vida(r, parte):
    """Leitura antiga do HUD (VERSAO_HUD < 3): com 1 máscara a última treme e a
    vida lida pulava 1 -> 2 -> 1, virando cura + dano falsos. Pela vida gravada
    quadro a quadro, desfaz em `r` cada mudança que voltou ao valor anterior em
    menos de PISCADA_QUADROS (curar de verdade leva mais que isso). Devolve os
    quadros desfeitos."""
    if "vidas" not in parte.files:
        return []
    v = parte["vidas"].astype(int)
    valor_dano = float(parte["valor_dano"]) if "valor_dano" in parte.files else DANO_ANTIGO
    mudancas = [i for i in range(1, len(v)) if v[i] != v[i - 1] and v[i] >= 0 and v[i - 1] >= 0]
    desfeitos = []
    for a, b in zip(mudancas, mudancas[1:]):
        if b - a < PISCADA_QUADROS and v[b] == v[a - 1] and a not in desfeitos:
            for i in (a, b):
                d = v[i] - v[i - 1]
                r[i] -= RECOMPENSA_CURA_GRAVADA * d if d > 0 else valor_dano * -d
            desfeitos += [a, b]
    return desfeitos


def ajustar_dano_e_morte(r, parte, piscadas=()):
    """Leva o dano e a morte de uma parte gravada para os pesos atuais (em `r`).
    Gravações novas marcam os quadros; nas antigas, o valor do quadro diz: só a
    morte (-3) passa de -2,5, e tirada ela, só o dano (-1) passa de -0,45 (os
    outros eventos: parada -0,2, positivos até +1; presa/loop marcados à parte)."""
    if "danos" in parte.files:
        danos, mortes = parte["danos"].copy(), parte["mortes"]
        danos[list(piscadas)] = False  # já desfeitos
        v_dano, v_morte = float(parte["valor_dano"]), float(parte["valor_morte"])
    else:
        base = r.copy()
        for marca, valor in (("presas", "valor_presa"), ("loops", "valor_loop")):
            if marca in parte.files:
                base -= (float(parte[valor]) if valor in parte.files else -0.3) * parte[marca]
        mortes = base <= -2.5
        danos = base - MORTE_ANTIGA * mortes <= -0.45
        v_dano, v_morte = DANO_ANTIGO, MORTE_ANTIGA
    r += (RECOMPENSA_DANO - v_dano) * danos + (RECOMPENSA_MORTE - v_morte) * mortes


def limpar_cache(pastas):
    """Apaga do cache as sessões que este treino não usou (apagadas ou antigas)."""
    usadas = {f"{p.parent.name}_{p.name}.npz" for p in pastas.values()}
    apagados = [c for c in PASTA_CACHE.glob("*.npz") if c.name not in usadas]
    for cache in apagados:
        cache.unlink()
    return len(apagados)


def carregar_sessoes(pastas):
    """Sessões em ordem cronológica, cada uma um dict com retratos, teclas e a
    recompensa por quadro (HUD + presa + salas novas pela memória de salas, que
    depende da ordem em que as salas foram vistas)."""
    memoria = ExploradorSalas(Path(os.devnull + ".npz"))  # só deste treino
    sessoes = []
    for nome, pasta in pastas.items():
        d = processar_sessao(pasta)
        if not len(d["retratos"]):
            continue
        sala = np.zeros(len(d["retratos"]), np.float32)
        anterior = None
        for idx, assinatura in zip(d["entradas_idx"], d["entradas_sig"]):
            intervalo = None if anterior is None else idx - anterior
            anterior = idx
            if memoria.lembrar(assinatura, intervalo) and not d["marcadas"][idx]:
                sala[idx] = RECOMPENSA_SALA  # gravações novas já trazem na recompensa
        sessoes.append({
            "nome": nome,
            "retratos": d["retratos"],
            "teclas": d["teclas"],
            "recompensa": d["hud"] + d["presa"] + sala,
            "da_mosca": nome.startswith("mosca_"),
            "peso": peso_da_sessao(nome) * np.where(d["pelo_jogo"], 1.0, PESO_TELA).astype(np.float32),
        })
    return sessoes


def peso_da_sessao(nome):
    if nome.startswith("mosca_"):
        return PESO_MOSCA
    return PESO_CORRECAO if nome.endswith("_correcao") else 1.0


def resumir_sessao(nome, pasta):
    """Linha da tabela public.sessoes (sem abrir as telas, que são pesadas)."""
    teclas, recompensas = [], []
    for arquivo in sorted(pasta.glob("parte_*.npz")):
        with np.load(arquivo) as parte:
            acoes = [str(a) for a in parte["acoes"]]
            teclas.append(parte["teclas"])
            if "recompensas" in parte.files:
                recompensas.append(parte["recompensas"])
    t = np.concatenate(teclas)
    try:
        gravada_em = datetime.strptime(pasta.name[:17], "%Y-%m-%d_%H%M%S").astimezone().isoformat()
    except ValueError:
        gravada_em = None
    linha = {
        "id": nome,
        "gravada_em": gravada_em,
        "quadros": len(t),
        "minutos": round(len(t) / 30 / 60, 2),
        "uso_teclas": {a: round(float(u), 4) for a, u in zip(acoes, t.mean(axis=0))},
        "tem_hud": bool(recompensas),
        "recompensa_total": None,
        "quadros_recompensa": None,
        "quadros_punicao": None,
    }
    if recompensas:
        r = np.concatenate(recompensas)
        linha.update(
            recompensa_total=round(float(r.sum()), 2),
            quadros_recompensa=int((r > 0).sum()),
            quadros_punicao=int((r < 0).sum()),
        )
    return linha


class Dados:
    """Todos os quadros juntos. A entrada da rede (retrato atual + brilho de
    ATRASO_OLHO quadros atrás + memória dos últimos segundos) é montada por
    lote, não de uma vez: inteira ela ocuparia alguns GB de memória."""

    def __init__(self, sessoes):
        self.retratos = np.concatenate([s["retratos"] for s in sessoes])
        # a memória recomeça em cada sessão, como no painel ao abrir
        self.memoria = np.concatenate([memorias_da_sessao(s["retratos"]) for s in sessoes]).astype(np.float16)
        self.teclas = np.concatenate([s["teclas"] for s in sessoes])
        self.retorno = np.concatenate([retornos(s["recompensa"]) for s in sessoes])
        self.fator = np.concatenate(
            [np.broadcast_to(np.asarray(s.get("peso", PESO_MOSCA if s["da_mosca"] else 1.0), np.float32),
                             (len(s["retratos"]),))
             for s in sessoes]
        )
        self.sessao = np.concatenate([np.full(len(s["retratos"]), i) for i, s in enumerate(sessoes)])
        passado, treino, valid, inicio = [], [], [], 0
        for s in sessoes:
            n = len(s["retratos"])
            idx = np.arange(inicio, inicio + n)
            # No começo da sessão não há passado ainda: usa o quadro mais antigo,
            # como o painel faz com a memória curta ainda enchendo
            passado.append(np.maximum(idx - ATRASO_OLHO, inicio))
            corte = int(n * (1 - VALIDACAO))  # o fim de cada sessão fica para validar
            treino.append(idx[:corte:SUBAMOSTRA])
            valid.append(idx[corte::SUBAMOSTRA])
            inicio += n
        self.passado = np.concatenate(passado)
        self.treino, self.valid = np.concatenate(treino), np.concatenate(valid)
        self.pesos = np.ones(len(self.retratos), np.float32)
        self.media = self.desvio = None

    def entrada(self, idx, espelho=None):
        """`espelho`: quais quadros do lote vão espelhados (no treino)."""
        atual = self.retratos[idx].astype(np.float32)
        passado = self.retratos[self.passado[idx]].astype(np.float32)
        memoria = self.memoria[idx].astype(np.float32)
        if espelho is not None and espelho.any():
            atual[espelho], passado[espelho] = espelhar(atual[espelho]), espelhar(passado[espelho])
            memoria[espelho] = espelhar_memoria(memoria[espelho])
        x = entrada(VERSAO_OLHO, atual, passado, memoria)
        return x if self.media is None else (x - self.media) / self.desvio

    def normalizar(self, lote=4096):
        """Média e desvio de cada entrada, calculados só com os quadros de treino."""
        soma = soma2 = 0.0
        for i in range(0, len(self.treino), lote):
            x = self.entrada(self.treino[i : i + lote]).astype(np.float64)
            soma, soma2 = soma + x.sum(0), soma2 + (x**2).sum(0)
        n = len(self.treino)
        media = soma / n
        self.desvio = (np.sqrt(np.maximum(soma2 / n - media**2, 0)) + 0.05).astype(np.float32)
        self.media = media.astype(np.float32)


def valor_esperado(dados, idx, lote=4096):
    """Retorno esperado de cada quadro de `idx`, por um estimador linear (ridge)
    sobre a periferia do olho, em duas metades: cada metade é estimada pelo
    estimador treinado na outra, para ele não decorar a resposta."""
    n_x = 2 * GRADE_OLHO[0] * GRADE_OLHO[1]  # periferia: brilho + movimento
    bloco = (idx // 900) % 2  # blocos de ~30 s alternados entre as duas metades
    valor = np.zeros(len(idx), np.float32)
    for metade in (0, 1):
        ajuste, aplica = idx[bloco == metade], idx[bloco != metade]
        if not len(ajuste) or not len(aplica):
            continue
        xtx = np.zeros((n_x + 1, n_x + 1))
        xty = np.zeros(n_x + 1)
        for i in range(0, len(ajuste), lote):
            parte = ajuste[i : i + lote]
            x = np.hstack([dados.entrada(parte)[:, :n_x], np.ones((len(parte), 1), np.float32)]).astype(np.float64)
            xtx += x.T @ x
            xty += x.T @ dados.retorno[parte]
        xtx[np.arange(n_x), np.arange(n_x)] += REGULARIZACAO_VALOR * len(ajuste)
        beta = np.linalg.solve(xtx, xty)
        for i in range(0, len(aplica), lote):
            parte = aplica[i : i + lote]
            x = np.hstack([dados.entrada(parte)[:, :n_x], np.ones((len(parte), 1), np.float32)])
            valor[np.searchsorted(idx, parte)] = x @ beta
    return valor


def pesar_pela_vantagem(dados):
    """Peso de cada quadro de treino: exp(FORCA x vantagem), com a vantagem =
    retorno - esperado, em desvios-padrão; as partidas da mosca valem PESO_MOSCA."""
    idx = np.sort(dados.treino)
    vantagem = dados.retorno[idx] - valor_esperado(dados, idx)
    vantagem /= vantagem.std() + 1e-6
    pesos = np.clip(np.exp(FORCA_VANTAGEM * vantagem), *PESO_QUADRO)
    pesos /= pesos.mean()
    dados.pesos[idx] = pesos * dados.fator[idx]
    return vantagem


class RedeMLP:
    """A rede inventada: olho -> INTERNEURONIOS interneurônios -> teclas.
    Mesma interface da RedeConectoma (frente, gradientes, limitar, para_salvar)."""

    def __init__(self, p):
        self.p = p

    @classmethod
    def iniciar(cls, n_ent, n_sai, rng):
        return cls({
            "w1": rng.normal(0, np.sqrt(2 / n_ent), (n_ent, INTERNEURONIOS)).astype(np.float32),
            "b1": np.zeros(INTERNEURONIOS, np.float32),
            "w2": rng.normal(0, np.sqrt(1 / INTERNEURONIOS), (INTERNEURONIOS, n_sai)).astype(np.float32),
            "b2": np.zeros(n_sai, np.float32),
        })

    def frente(self, x):
        h = np.maximum(0, x @ self.p["w1"] + self.p["b1"])
        prob = 1 / (1 + np.exp(-np.clip(h @ self.p["w2"] + self.p["b2"], -30, 30)))
        return {"x": x, "h": h, "prob": prob}

    def prever(self, x):
        return self.frente(x)["prob"]

    def gradientes(self, f, dz):
        dh = (dz @ self.p["w2"].T) * (f["h"] > 0)
        return {"w2": f["h"].T @ dz, "b2": dz.sum(0), "w1": f["x"].T @ dh, "b1": dh.sum(0)}

    regularizar = {}

    def limitar(self):
        pass

    def para_salvar(self):
        return dict(self.p)


def arquitetura_da_campea():
    """O treino automático segue a arquitetura da campeã (muda se outra vencer)."""
    if not ARQUIVO_MODELO.exists():
        return "mlp"
    with np.load(ARQUIVO_MODELO) as modelo:
        return str(modelo["arquitetura"]) if "arquitetura" in modelo.files else "mlp"


def criar_rede(arquitetura, n_ent, n_sai, rng):
    if arquitetura == "conectoma":
        return RedeConectoma.iniciar(n_ent, n_sai, carregar_conectoma(), rng)
    return RedeMLP.iniciar(n_ent, n_sai, rng)


def prever(rede, dados, idx, lote=4096):
    return np.concatenate([rede.prever(dados.entrada(idx[i : i + lote])) for i in range(0, len(idx), lote)])


def perda(rede, dados, idx, peso_pos, ponderar=False):
    prob = np.clip(prever(rede, dados, idx), 1e-6, 1 - 1e-6)
    y = dados.teclas[idx]
    por_quadro = -(peso_pos * y * np.log(prob) + (1 - y) * np.log(1 - prob)).mean(axis=1)
    return float(np.average(por_quadro, weights=dados.pesos[idx] if ponderar else None))


CANDIDATOS_SUPABASE = 3  # versões recentes do mesmo cérebro testadas como ponto de partida


def candidatos_de_partida(arquitetura):
    """Versões já treinadas deste cérebro que podem servir de ponto de partida:
    a campeã e a desafiante (se forem dele) e as CANDIDATOS_SUPABASE mais recentes
    dele no Supabase. Lista de (pesos, treino_id)."""
    candidatos, vistos = [], set()
    for arquivo in (ARQUIVO_MODELO, ARQUIVO_DESAFIANTE):
        if arquivo.exists():
            with np.load(arquivo) as m:
                if (str(m["arquitetura"]) if "arquitetura" in m.files else "mlp") != arquitetura:
                    continue
                info = arquivo.with_suffix(".json")
                tid = json.loads(info.read_text()).get("treino_id") if info.exists() else None
                candidatos.append(({k: m[k] for k in m.files}, tid))
                vistos.add(tid)
    try:
        from registro import Supabase, baixar_treino

        banco = Supabase.do_env()
        if banco is not None:
            achados = 0
            for t in banco._pedir("GET", "/rest/v1/treinos?select=id,config&order=id.desc&limit=100"):
                if achados >= CANDIDATOS_SUPABASE:
                    break
                if (t.get("config") or {}).get("especialista"):  # de uma arena só: não serve de base geral
                    continue
                if (t.get("config") or {}).get("arquitetura", "mlp") != arquitetura or t["id"] in vistos:
                    continue
                arquivo, _ = baixar_treino(t["id"], PASTA / "modelos_base")
                with np.load(arquivo) as m:
                    candidatos.append(({k: m[k] for k in m.files}, t["id"]))
                achados += 1
    except Exception as e:  # sem internet: fica com os locais
        print(f"⚠ sem candidatas do Supabase ({e})")
    return candidatos


def candidatos_de_especialista(cena, arquitetura):
    """O especialista atual da arena (se for deste cérebro), como ponto de partida."""
    arquivo = PASTA_ESPECIALISTAS / f"{cena}.npz"
    if not arquivo.exists():
        return []
    with np.load(arquivo) as m:
        if (str(m["arquitetura"]) if "arquitetura" in m.files else "mlp") != arquitetura:
            return []
        info = arquivo.with_suffix(".json")
        tid = json.loads(info.read_text()).get("treino_id") if info.exists() else None
        return [({k: m[k] for k in m.files}, tid)]


def escolher_partida(dados, arquitetura, candidatos):
    """A candidata com a melhor validação nos dados de agora: o progresso de uma
    desafiante que empatou não se perde, mesmo sem ela ter vencido."""
    peso_pos = pesos_positivos(dados)
    n_ent, n_sai = dados.entrada(dados.treino[:1]).shape[1], dados.teclas.shape[1]
    melhor, melhor_perda = (None, None), np.inf
    for pesos, tid in candidatos:
        rede = criar_rede(arquitetura, n_ent, n_sai, np.random.default_rng(0))
        if not partir_de(rede, pesos, arquitetura, dados):
            continue
        pv = perda(rede, dados, dados.valid, peso_pos)
        print(f"  candidata #{tid}: validação {pv:.4f}")
        if pv < melhor_perda:
            melhor, melhor_perda = (pesos, tid), pv
    return melhor


def partir_de(rede, base, arquitetura, dados):
    """Copia os pesos de `base` para `rede`, que pode ter mais entradas (olho
    mais novo: as entradas novas entram com peso zero) e outra normalização (a
    primeira camada é ajustada para a rede responder igual à base no começo).
    Devolve False se as formas não batem (outro tamanho de rede): do zero."""
    w, b = PRIMEIRA_CAMADA[arquitetura]
    p = rede.p
    base = dict(base)
    if arquitetura == "conectoma":
        # o modelo salvo guarda o peso efetivo (fiação real x ganho do grupo de
        # destino); o treino ajusta o ganho: recupera dividindo pela fiação real
        for k in CAMADAS_CONECTOMA:
            if f"s_{k}" in base or k not in base or base[k].shape != rede.m[k].shape:
                continue
            with np.errstate(divide="ignore", invalid="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # grupo sem ligação real: fica o ganho inicial
                razao = np.where(rede.m[k] != 0, base[k] / rede.m[k], np.nan)
                ganho = np.log(np.nanmean(razao, axis=0))
            base[f"s_{k}"] = np.where(np.isfinite(ganho), ganho, p[f"s_{k}"]).astype(np.float32)
    # Saídas casadas pelo nome da ação: uma ação que saiu (ex.: Mapa) some, uma
    # nova fica como a rede nova a iniciou
    ws, bs = ULTIMA_CAMADA[arquitetura]
    if "acoes" in base and ws in base and bs in base:
        nomes = [str(a) for a in base["acoes"]]
        saida_w, saida_b = p[ws].copy(), p[bs].copy()
        for i, acao in enumerate(ACOES):
            if acao in nomes:
                saida_w[:, i], saida_b[i] = base[ws][:, nomes.index(acao)], base[bs][nomes.index(acao)]
        base[ws], base[bs] = saida_w, saida_b
    if any(k not in base or (k != w and base[k].shape != p[k].shape) for k in p):
        return False
    wb = base[w].astype(np.float32)
    n_b = wb.shape[0]
    if n_b > p[w].shape[0] or wb.shape[1] != p[w].shape[1]:
        return False
    # x_base = (x - m_b)/d_b; x_nova = (x - m)/d  =>  x_base = (x_nova*d + m - m_b)/d_b
    media_b, desvio_b = base["media"].astype(np.float32), base["desvio"].astype(np.float32)
    media, desvio = dados.media[:n_b], dados.desvio[:n_b]
    novo_w = np.zeros_like(p[w])
    novo_w[:n_b] = wb * (desvio / desvio_b)[:, None]
    p[w] = novo_w
    p[b] = (base[b].astype(np.float32) + ((media - media_b) / desvio_b) @ wb).astype(np.float32)
    for k in p:
        if k not in (w, b):
            p[k] = base[k].astype(np.float32).copy()
    return True


def pesos_positivos(dados):
    """Teclas raras pesam mais, senão a rede só aprende "nunca aperta"; mas pouco
    mais (até PESO_MAXIMO), senão ela aperta à toa teclas que não dá para prever."""
    frac = dados.teclas[dados.treino].mean(axis=0)
    teto = np.array([PESO_MAXIMO_POR_TECLA.get(a, PESO_MAXIMO_HABILIDADE if a in HABILIDADES_RARAS else PESO_MAXIMO)
                     for a in ACOES], np.float32)
    return np.clip((1 - frac) / np.maximum(frac, 1e-3), 1, teto).astype(np.float32)


def treinar(dados, arquitetura="mlp", base=None):
    """Cada quadro de treino pesa pela recompensa futura (dados.pesos). A
    validação não usa peso: mede o quanto ela imita você, para comparar treinos.
    Com `base` (pesos de uma versão já treinada), parte dela.
    Devolve a rede da melhor época (pela validação), a perda dela e se aprendeu
    algo (sempre True do zero; partindo da base, só se melhorou MELHORA_MINIMA)."""
    rng = np.random.default_rng(0)
    n_ent, n_sai = dados.entrada(dados.treino[:1]).shape[1], dados.teclas.shape[1]
    rede = criar_rede(arquitetura, n_ent, n_sai, rng)
    partiu = base is not None and partir_de(rede, base, arquitetura, dados)
    if base is not None and not partiu:
        print("  a versão de partida tem outro formato: treinando do zero")
    taxa = TAXA_AJUSTE if partiu else TAXA
    epocas = EPOCAS_CONECTOMA if arquitetura == "conectoma" else EPOCAS
    peso_pos = pesos_positivos(dados)
    p = rede.p
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v = {k: np.zeros_like(v) for k, v in p.items()}
    melhor, melhor_p, melhor_epoca, passo = np.inf, None, 0, 0
    if partiu:
        partida = perda(rede, dados, dados.valid, peso_pos)
        print(f"  ponto de partida: validação {partida:.4f}")
        melhor, melhor_p, melhor_epoca = partida, {k: a.copy() for k, a in p.items()}, -1
    for epoca in range(epocas):
        ordem = rng.permutation(dados.treino)
        for i in range(0, len(ordem), LOTE):
            idx = ordem[i : i + LOTE]
            espelho = rng.random(len(idx)) < ESPELHAR
            x, y, w = dados.entrada(idx, espelho), dados.teclas[idx].copy(), dados.pesos[idx, None]
            y[np.ix_(espelho, [I_ESQ, I_DIR])] = y[np.ix_(espelho, [I_DIR, I_ESQ])]
            x = x + rng.normal(0, RUIDO, x.shape).astype(np.float32)  # menos decoreba
            f = rede.frente(x)
            # gradiente da entropia cruzada com peso nos positivos e no quadro
            dz = w * (f["prob"] * (peso_pos * y + 1 - y) - peso_pos * y) / (len(x) * n_sai)
            grad = rede.gradientes(f, dz)
            passo += 1
            for k in p:  # Adam
                m[k] = 0.9 * m[k] + 0.1 * grad[k]
                v[k] = 0.999 * v[k] + 0.001 * grad[k] ** 2
                mh, vh = m[k] / (1 - 0.9**passo), v[k] / (1 - 0.999**passo)
                passo_k = mh / (np.sqrt(vh) + 1e-8) + rede.regularizar.get(k, 0) * p[k]  # L2 (AdamW)
                p[k] -= (taxa * passo_k).astype(np.float32)
            rede.limitar()
        pv = perda(rede, dados, dados.valid, peso_pos)
        amostra = rng.choice(dados.treino, min(5000, len(dados.treino)), replace=False)
        pt = perda(rede, dados, amostra, peso_pos, ponderar=True)
        print(f"  época {epoca + 1:2d}/{epocas}: perda treino {pt:.4f} · validação {pv:.4f}")
        if pv < melhor:
            melhor, melhor_p, melhor_epoca = pv, {k: a.copy() for k, a in p.items()}, epoca
        elif epoca - melhor_epoca >= PACIENCIA:
            print(f"  parando: {PACIENCIA} épocas sem melhorar (fica a época {melhor_epoca + 1})")
            break
    rede.p.update(melhor_p)
    aprendeu = not partiu or melhor < partida - MELHORA_MINIMA
    return rede, melhor, aprendeu


def relatorio(rede, dados):
    """Compara a mosca com um "chute" que sempre faz a coisa mais comum."""
    prev = prever(rede, dados, dados.valid) > 0.5
    real = dados.teclas[dados.valid] > 0.5
    metricas = {}
    print(f"\n  {'tecla':<20}{'uso':>7}{'acerto mosca':>14}{'acerto chute':>14}{'pega quando você aperta':>26}")
    for j, nome in enumerate(ACOES):
        uso = real[:, j].mean()
        acerto = (prev[:, j] == real[:, j]).mean()
        chute = max(uso, 1 - uso)
        pega = (prev[:, j] & real[:, j]).sum() / max(real[:, j].sum(), 1)
        print(f"  {nome:<20}{uso:>7.0%}{acerto:>14.0%}{chute:>14.0%}{pega:>26.0%}")
        metricas[nome] = {
            k: round(float(v), 4) for k, v in (("uso", uso), ("acerto", acerto), ("chute", chute), ("pega", pega))
        }
    print("\n  'pega quando você aperta' é a fração das vezes em que você apertou a tecla")
    print("  e a mosca também apertaria. Teclas com uso ~0% não têm exemplos suficientes.")
    return metricas


def main():
    os.nice(15)  # o jogo vem primeiro: o treino só usa a CPU que sobrar
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--arquitetura", choices=["mlp", "conectoma"], default=None,
        help="cérebro a treinar (padrão: o mesmo da campeã atual)",
    )
    parser.add_argument(
        "--do-zero", action="store_true",
        help="não parte da melhor versão já treinada deste cérebro",
    )
    parser.add_argument(
        "--ensaio", action="store_true",
        help="treina e mostra o resultado, sem salvar nem registrar (não cria desafiante)",
    )
    parser.add_argument(
        "--especialista", metavar="CENA",
        help="especialista de uma arena (ex.: GG_Gruz_Mother): só os quadros dela; vira candidato",
    )
    args = parser.parse_args()
    arquitetura = args.arquitetura or arquitetura_da_campea()
    especialista = args.especialista
    print(f"cérebro: {arquitetura}" + (f" · especialista de {especialista}" if especialista else ""))
    inicio = time.time()
    if especialista:
        pastas, cenas_por_sessao = pastas_da_arena(especialista)
    else:
        pastas = pastas_de_sessoes()
    sessoes = carregar_sessoes(pastas)
    print(f"olho de {len(sessoes)} sessões pronto em {time.time() - inicio:.0f} s (cache em {PASTA_CACHE.name}/)")
    total = sum(len(s["retratos"]) for s in sessoes)
    quadros_mosca = sum(len(s["retratos"]) for s in sessoes if s["da_mosca"])
    quadros_correcao = sum(len(s["retratos"]) for s in sessoes if s["nome"].endswith("_correcao"))
    if total < MINIMO_QUADROS:
        print(
            f"Só {total} quadros gravados (mínimo {MINIMO_QUADROS}). Grave mais partidas com "
            "o botão '⏺ Gravar' do painel."
        )
        return
    nomes_sessoes = [s["nome"] for s in sessoes]
    dados = Dados(sessoes)
    del sessoes  # os retratos já estão em `dados`; libera a memória
    if especialista:
        so_a_arena(dados, nomes_sessoes, cenas_por_sessao, especialista)
        if len(dados.treino) + len(dados.valid) < MINIMO_QUADROS_ESPECIALISTA // SUBAMOSTRA:
            print(f"Pouca luta em {especialista} (mínimo {MINIMO_QUADROS_ESPECIALISTA} quadros).")
            return
    dados.normalizar()
    pesar_pela_vantagem(dados)
    for i, nome in enumerate(nomes_sessoes):
        idx = np.sort(dados.treino)
        dentro = dados.sessao[idx] == i
        w = dados.pesos[idx][dentro] / dados.fator[idx][dentro]
        origem = (f" · partida da mosca (peso {PESO_MOSCA})" if nome.startswith("mosca_")
                  else f" · correção ao vivo (peso {PESO_CORRECAO})" if nome.endswith("_correcao") else "")
        n = int((dados.sessao == i).sum())
        print(f"sessão {nome}: {n:,} quadros ({n / 30 / 60:.1f} min){origem} · ".replace(",", ".")
              + f"{(w > 1.3).mean():.0%} melhores que o esperado, {(w < 0.7).mean():.0%} piores")
    print(
        f"\ntreinando com {len(dados.treino):,} quadros, validando com {len(dados.valid):,} "
        f"(olho versão {VERSAO_OLHO}: {dados.entrada(dados.treino[:1]).shape[1]:,} entradas)".replace(",", ".")
    )
    base, base_id = None, None
    if not args.do_zero:
        print("escolhendo o ponto de partida (a melhor nos dados de agora):")
        candidatos = candidatos_de_partida(arquitetura)
        if especialista:  # o especialista atual da arena e a campeã geral
            candidatos = [c for c in candidatos_de_especialista(especialista, arquitetura)] + candidatos[:1]
        base, base_id = escolher_partida(dados, arquitetura, candidatos)
    if base is not None:
        print(f"partindo da versão #{base_id} (o que ela sabe não se perde)")
    rede, perda_validacao, aprendeu = treinar(dados, arquitetura, base)
    if not aprendeu:
        print(f"\nnada novo aprendido: a validação não melhorou {MELHORA_MINIMA} sobre a #{base_id}. "
              "Nenhuma desafiante criada; o próximo treino terá mais dados.")
        sys.exit(NADA_NOVO)
    metricas = relatorio(rede, dados)
    if args.ensaio:
        print(f"\nensaio: validação {perda_validacao:.4f} (nada salvo)")
        return

    # Salva num temporário e troca de uma vez: o painel nunca lê um modelo pela metade
    saida = PASTA_ESPECIALISTAS / f"{especialista}.candidato.npz" if especialista else ARQUIVO_SAIDA
    saida.parent.mkdir(exist_ok=True)
    temporario = saida.with_name(saida.stem + ".tmp.npz")
    extras = {}
    if arquitetura == "conectoma":  # nomes dos grupos: o painel acende os neurônios reais
        conectoma = carregar_conectoma()
        extras = {f"grupos_{k}": conectoma[f"grupos_{k}"] for k in ("visual", "central", "descendente")}
    np.savez_compressed(
        temporario, **rede.para_salvar(), **extras, media=dados.media, desvio=dados.desvio,
        acoes=np.array(ACOES), n_quadros=total, versao_olho=VERSAO_OLHO, arquitetura=arquitetura,
        metodo=("conectoma · " if arquitetura == "conectoma" else "") + "imitação + vantagem",
    )

    nomes = nomes_sessoes
    treino = {
        "quadros": total,
        "minutos": round(total / 30 / 60, 2),
        "quadros_validacao": len(dados.valid),
        "perda_validacao": round(float(perda_validacao), 5),
        "epocas": EPOCAS_CONECTOMA if arquitetura == "conectoma" else EPOCAS,
        # no conectoma, os "interneurônios" são os grupos centrais
        "interneuronios": INTERNEURONIOS if arquitetura == "mlp" else int(rede.p["bc"].shape[0]),
        "sessoes": nomes,
        "metricas": metricas,
        "config": {
            "taxa": TAXA, "lote": LOTE, "validacao": VALIDACAO, "peso_maximo": PESO_MAXIMO,
            "olho": list(OLHO), "grade_olho": list(GRADE_OLHO), "versao_olho": VERSAO_OLHO,
            "fovea": [FOVEA[0].start, FOVEA[0].stop, FOVEA[1].start, FOVEA[1].stop],
            "grade_fovea": list(GRADE_FOVEA), "atraso_olho": ATRASO_OLHO, "memoria_s": list(MEMORIA_S),
            "aprendizado": "imitação ponderada pela vantagem (AWR)",
            "desconto": DESCONTO, "forca_vantagem": FORCA_VANTAGEM,
            "peso_quadro": list(PESO_QUADRO), "subamostra": SUBAMOSTRA, "ruido": RUIDO,
            "git_commit": commit_do_codigo(),
            "papel": "desafiante", "quadros_mosca": quadros_mosca, "peso_mosca": PESO_MOSCA,
            "quadros_correcao": quadros_correcao,
            "peso_correcao": PESO_CORRECAO, "peso_tela": PESO_TELA, "espelhar": ESPELHAR,
            "toque_s": TOQUE_S, "arquitetura": arquitetura,
            "partiu_de": base_id,
            "especialista": especialista,
            "quadros_arena": int(len(dados.treino) + len(dados.valid)) * SUBAMOSTRA if especialista else None,
        },
        "codigo_versao": versao_do_codigo(),
    }
    # Registra antes de pôr no lugar: se o treino for interrompido aqui (painel
    # fechado), não sobra uma desafiante sem número e fora do Supabase
    mensagem, treino_id = registrar_treino(
        [resumir_sessao(n, pastas[n]) for n in nomes], treino, temporario, pastas
    )
    print(mensagem)
    # O painel lê o .json para dizer, nas partidas, qual treino estava jogando
    saida.with_suffix(".json").write_text(json.dumps({"treino_id": treino_id, "n_quadros": total,
                                                      "especialista": especialista}))
    os.replace(temporario, saida)
    if especialista:
        print(f"especialista salvo em {saida.relative_to(PASTA)} ({time.time() - inicio:.0f} s): "
              "ele joga as próximas lutas da arena e assume se vencer pelo menos tanto quanto antes.")
        return
    print(f"modelo salvo em {ARQUIVO_SAIDA.name} ({time.time() - inicio:.0f} s).")
    apagadas = limpar_partidas_antigas_da_mosca()
    if apagadas:
        print(f"apaguei as telas de {len(apagadas)} partidas antigas da mosca (as teclas e recompensas estão no Supabase)")
    if limpar_cache(pastas):
        print("limpei do cache_olho/ as sessões que não são mais usadas")
    print(
        "Nova desafiante. Ela só substitui a campeã se jogar melhor: ligue o "
        "'Controlar jogo' no painel para as duas disputarem."
    )


if __name__ == "__main__":
    main()
