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

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from mosca.config import ACOES, ARQUIVO_DESAFIANTE, ARQUIVO_MODELO, PASTA, PASTA_GRAVACOES, PASTA_GRAVACOES_MOSCA, QUADRO_MS, TOQUE_S
from mosca.conectoma import RedeConectoma, carregar_conectoma
from mosca.estimulos import DetectorLoop, DetectorPresa, ExploradorSalas, LeitorHUD
from mosca.olho import ATRASO_OLHO, FOVEA, GRADE_FOVEA, GRADE_OLHO, OLHO, VERSAO_OLHO, entrada, retrato
from registro import registrar_treino

INTERNEURONIOS = 64
EPOCAS = 40
EPOCAS_CONECTOMA = 20  # a rede do conectoma é maior: ~20 s por época
PACIENCIA = 3  # para depois de tantas épocas sem melhorar na validação
LOTE = 256
TAXA = 1e-3
VALIDACAO = 0.2  # o fim de cada sessão fica de fora do treino, para medir de verdade
MINIMO_QUADROS = 300
PESO_MAXIMO = 3  # peso máximo das teclas raras (ver treinar)
DESCONTO = 0.993  # por quadro: um evento a ~3 s (100 quadros) conta pela metade
FORCA_VANTAGEM = 1.0  # peso = exp(FORCA x vantagem em desvios-padrão), limitado
PESO_QUADRO = (0.25, 4.0)  # mínimo e máximo do peso de um quadro
REGULARIZACAO_VALOR = 0.05  # do estimador de retorno (por quadro de treino)
SUBAMOSTRA = 2  # usa 1 a cada 2 quadros: vizinhos são quase iguais (menos decoreba)
RUIDO = 0.1  # ruído nas entradas (já normalizadas) durante o treino
PASTA_CACHE = PASTA / "cache_olho"
VERSAO_CACHE = 3  # mude se o que vai no cache mudar
ARQUIVO_SAIDA = ARQUIVO_DESAFIANTE  # todo treino gera uma desafiante (ver jogar.Torneio)
ARQUIVO_INFO_MODELO = ARQUIVO_SAIDA.with_suffix(".json")  # qual treino gerou o modelo
# Partidas da própria mosca: entram com menos peso que as suas (ela erra mais) e
# só as mais recentes, para o treino não crescer sem fim
PESO_MOSCA = 0.5
RECOMPENSA_SALA = LeitorHUD.RECOMPENSA["sala_nova"]
RECOMPENSA_PRESA = LeitorHUD.RECOMPENSA["presa"]
RECOMPENSA_MORTE = LeitorHUD.RECOMPENSA["morte"]
RECOMPENSA_LOOP = LeitorHUD.RECOMPENSA["loop"]
MAXIMO_QUADROS_MOSCA = 60_000  # ~33 min
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
    h = hashlib.sha256(f"{VERSAO_CACHE}|{VERSAO_OLHO}|{','.join(ACOES)}".encode())
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
    olhos, teclas, hud, presas, marcadas = [], [], [], [], []
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
                    r = np.where(r <= RECOMPENSA_MORTE + 0.1, r - RECOMPENSA_MORTE, r)
                hud.append(r)
            else:
                com_hud = False
                hud.append(np.zeros(n, np.float32))
            acoes = [str(a) for a in parte["acoes"]]
            colunas = [acoes.index(a) if a in acoes else None for a in ACOES]
            presas_marcadas = "presas" in parte.files
            loops_marcados = "loops" in parte.files
            marcadas.append(np.full(n, "salas_novas" in parte.files))
            anterior = None
            for tela, apertadas, r_hud in zip(parte["telas"], parte["teclas"], hud[-1]):
                olhos.append(retrato(tela, anterior).astype(np.float16))
                t = [bool(apertadas[c]) if c is not None else False for c in colunas]
                teclas.append(t)
                ficou_presa = bool(presa.passo(tela, t[i_esq], t[i_dir], True))
                em_loop = bool(loop.passo(tela, r_hud > 0, True))
                presas.append((RECOMPENSA_PRESA if ficou_presa and not presas_marcadas else 0.0)
                              + (RECOMPENSA_LOOP if em_loop and not loops_marcados else 0.0))
                assinatura = salas.entrada_de_sala(tela)
                if assinatura is not None:
                    entradas_idx.append(len(olhos) - 1)
                    entradas_sig.append(assinatura)
                anterior = tela
    dados = {
        "chave": np.array(chave),
        "retratos": np.stack(olhos) if olhos else np.zeros((0, 2016), np.float16),
        "teclas": fases_de_toque(np.array(teclas, dtype=np.float32).reshape(-1, len(ACOES))),
        "hud": np.concatenate(hud).astype(np.float32) if hud else np.zeros(0, np.float32),
        "com_hud": np.array(com_hud and bool(hud)),
        "presa": np.array(presas, dtype=np.float32),
        "marcadas": np.concatenate(marcadas) if marcadas else np.zeros(0, bool),
        "entradas_idx": np.array(entradas_idx, dtype=np.int64),
        "entradas_sig": np.array(entradas_sig, dtype=np.float32).reshape(-1, 576),
    }
    temporario = cache.with_name(cache.stem + ".tmp.npz")
    np.savez(temporario, **dados)
    os.replace(temporario, cache)
    return dados


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
        })
    return sessoes


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
    ATRASO_OLHO quadros atrás) é montada por lote, não de uma vez: inteira ela
    ocuparia alguns GB de memória."""

    def __init__(self, sessoes):
        self.retratos = np.concatenate([s["retratos"] for s in sessoes])
        self.teclas = np.concatenate([s["teclas"] for s in sessoes])
        self.retorno = np.concatenate([retornos(s["recompensa"]) for s in sessoes])
        self.fator = np.concatenate(
            [np.full(len(s["retratos"]), PESO_MOSCA if s["da_mosca"] else 1.0, np.float32) for s in sessoes]
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

    def entrada(self, idx):
        x = entrada(VERSAO_OLHO, self.retratos[idx].astype(np.float32),
                    self.retratos[self.passado[idx]].astype(np.float32))
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


def treinar(dados, arquitetura="mlp"):
    """Cada quadro de treino pesa pela recompensa futura (dados.pesos). A
    validação não usa peso: mede o quanto ela imita você, para comparar treinos.
    Devolve a rede da melhor época (pela validação) e a perda dela."""
    rng = np.random.default_rng(0)
    n_ent, n_sai = dados.entrada(dados.treino[:1]).shape[1], dados.teclas.shape[1]
    rede = criar_rede(arquitetura, n_ent, n_sai, rng)
    epocas = EPOCAS_CONECTOMA if arquitetura == "conectoma" else EPOCAS
    # Teclas raras pesam mais, senão a rede só aprende "nunca aperta"; mas pouco
    # mais (até 3x), senão ela aperta à toa teclas que não dá para prever
    frac = dados.teclas[dados.treino].mean(axis=0)
    peso_pos = np.clip((1 - frac) / np.maximum(frac, 1e-3), 1, PESO_MAXIMO).astype(np.float32)
    p = rede.p
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v = {k: np.zeros_like(v) for k, v in p.items()}
    melhor, melhor_p, melhor_epoca, passo = np.inf, None, 0, 0
    for epoca in range(epocas):
        ordem = rng.permutation(dados.treino)
        for i in range(0, len(ordem), LOTE):
            idx = ordem[i : i + LOTE]
            x, y, w = dados.entrada(idx), dados.teclas[idx], dados.pesos[idx, None]
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
                p[k] -= (TAXA * passo_k).astype(np.float32)
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
    return rede, melhor


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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--arquitetura", choices=["mlp", "conectoma"], default=None,
        help="cérebro a treinar (padrão: o mesmo da campeã atual)",
    )
    arquitetura = parser.parse_args().arquitetura or arquitetura_da_campea()
    print(f"cérebro: {arquitetura}")
    inicio = time.time()
    pastas = pastas_de_sessoes()
    sessoes = carregar_sessoes(pastas)
    print(f"olho de {len(sessoes)} sessões pronto em {time.time() - inicio:.0f} s (cache em {PASTA_CACHE.name}/)")
    total = sum(len(s["retratos"]) for s in sessoes)
    quadros_mosca = sum(len(s["retratos"]) for s in sessoes if s["da_mosca"])
    if total < MINIMO_QUADROS:
        print(
            f"Só {total} quadros gravados (mínimo {MINIMO_QUADROS}). Grave mais partidas com "
            "o botão '⏺ Gravar' do painel."
        )
        return
    nomes_sessoes = [s["nome"] for s in sessoes]
    dados = Dados(sessoes)
    del sessoes  # os retratos já estão em `dados`; libera a memória
    dados.normalizar()
    pesar_pela_vantagem(dados)
    for i, nome in enumerate(nomes_sessoes):
        idx = np.sort(dados.treino)
        dentro = dados.sessao[idx] == i
        w = dados.pesos[idx][dentro] / dados.fator[idx][dentro]
        origem = f" · partida da mosca (peso {PESO_MOSCA})" if nome.startswith("mosca_") else ""
        n = int((dados.sessao == i).sum())
        print(f"sessão {nome}: {n:,} quadros ({n / 30 / 60:.1f} min){origem} · ".replace(",", ".")
              + f"{(w > 1.3).mean():.0%} melhores que o esperado, {(w < 0.7).mean():.0%} piores")
    print(
        f"\ntreinando com {len(dados.treino):,} quadros, validando com {len(dados.valid):,} "
        f"(olho versão {VERSAO_OLHO}: {dados.entrada(dados.treino[:1]).shape[1]:,} entradas)".replace(",", ".")
    )
    rede, perda_validacao = treinar(dados, arquitetura)
    metricas = relatorio(rede, dados)

    # Salva num temporário e troca de uma vez: o painel nunca lê um modelo pela metade
    temporario = ARQUIVO_SAIDA.with_name(ARQUIVO_SAIDA.stem + ".tmp.npz")
    extras = {}
    if arquitetura == "conectoma":  # nomes dos grupos: o painel acende os neurônios reais
        conectoma = carregar_conectoma()
        extras = {f"grupos_{k}": conectoma[f"grupos_{k}"] for k in ("visual", "central", "descendente")}
    np.savez_compressed(
        temporario, **rede.para_salvar(), **extras, media=dados.media, desvio=dados.desvio,
        acoes=np.array(ACOES), n_quadros=total, versao_olho=VERSAO_OLHO, arquitetura=arquitetura,
        metodo=("conectoma · " if arquitetura == "conectoma" else "") + "imitação + vantagem",
    )
    os.replace(temporario, ARQUIVO_SAIDA)
    print(f"\nmodelo salvo em {ARQUIVO_SAIDA.name} ({time.time() - inicio:.0f} s).")

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
            "grade_fovea": list(GRADE_FOVEA), "atraso_olho": ATRASO_OLHO,
            "aprendizado": "imitação ponderada pela vantagem (AWR)",
            "desconto": DESCONTO, "forca_vantagem": FORCA_VANTAGEM,
            "peso_quadro": list(PESO_QUADRO), "subamostra": SUBAMOSTRA, "ruido": RUIDO,
            "git_commit": commit_do_codigo(),
            "papel": "desafiante", "quadros_mosca": quadros_mosca, "peso_mosca": PESO_MOSCA,
            "toque_s": TOQUE_S, "arquitetura": arquitetura,
        },
        "codigo_versao": versao_do_codigo(),
    }
    mensagem, treino_id = registrar_treino(
        [resumir_sessao(n, pastas[n]) for n in nomes], treino, ARQUIVO_SAIDA, pastas
    )
    print(mensagem)
    # O painel lê isto para dizer, nas partidas, qual treino estava jogando
    ARQUIVO_INFO_MODELO.write_text(json.dumps({"treino_id": treino_id, "n_quadros": total}))
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
