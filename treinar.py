"""Treina a mosca para imitar as suas partidas gravadas, pesando pela recompensa.

Uso:
    .venv-flygym/bin/python treinar.py

Lê tudo em gravacoes/ (gravado com o botão "⏺ Gravar" do painel), ensina a
rede olho -> interneurônios -> zonas de comando a prever, para cada tela, quais
teclas você estava apertando, e salva em modelo_mosca.npz. O painel carrega o
modelo ao abrir.

Imitação ponderada pela recompensa: cada quadro pesa conforme o que aconteceu
nos ~2 s seguintes (dano, parada, acerto, geo, lidos do HUD na gravação). O que
levou a coisas boas é imitado com mais força; o que levou a dano ou a ficar
parado, com menos. É o papel da dopamina: reforçar o que veio antes da
recompensa. Sessões gravadas antes do leitor de HUD entram com peso 1.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime

import numpy as np

from jogar import (
    ACOES, ARQUIVO_DESAFIANTE, QUADRO_MS, TOQUE_S, ATRASO_OLHO, FOVEA, GRADE_FOVEA, GRADE_OLHO, OLHO, PASTA,
    PASTA_GRAVACOES, PASTA_GRAVACOES_MOSCA, VERSAO_OLHO, entrada, retrato,
)
from registro import registrar_treino

INTERNEURONIOS = 64
EPOCAS = 40
LOTE = 256
TAXA = 1e-3
VALIDACAO = 0.2  # o fim de cada sessão fica de fora do treino, para medir de verdade
MINIMO_QUADROS = 300
PESO_MAXIMO = 3  # peso máximo das teclas raras (ver treinar)
DESCONTO = 0.98  # por quadro: um evento a ~1 s (30 quadros) conta pela metade
FORCA_RECOMPENSA = 1.5  # peso = exp(FORCA x recompensa futura), limitado abaixo
PESO_QUADRO = (0.25, 4.0)  # mínimo e máximo do peso de um quadro
ARQUIVO_SAIDA = ARQUIVO_DESAFIANTE  # todo treino gera uma desafiante (ver jogar.Torneio)
ARQUIVO_INFO_MODELO = ARQUIVO_SAIDA.with_suffix(".json")  # qual treino gerou o modelo
# Partidas da própria mosca: entram com menos peso que as suas (ela erra mais) e
# só as mais recentes, para o treino não crescer sem fim
PESO_MOSCA = 0.5
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
            ["git", "status", "--porcelain", "jogar.py", "treinar.py"], cwd=PASTA,
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


def pesos_por_recompensa(recompensas):
    """Peso de cada quadro pela recompensa descontada dos quadros seguintes."""
    futura = np.zeros(len(recompensas), dtype=np.float32)
    acumulada = 0.0
    for i in range(len(recompensas) - 1, -1, -1):
        acumulada = recompensas[i] + DESCONTO * acumulada
        futura[i] = acumulada
    pesos = np.clip(np.exp(FORCA_RECOMPENSA * futura), *PESO_QUADRO)
    return pesos / pesos.mean()  # a sessão continua pesando o mesmo no total


def versao_do_codigo():
    """Impressão digital do código que treina e roda a mosca (muda a cada edição)."""
    h = hashlib.sha256()
    for nome in ("jogar.py", "treinar.py"):
        h.update((PASTA / nome).read_bytes())
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
    return pastas


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


def carregar_sessoes(pastas):
    """Lista de (nome, retratos, teclas, pesos) por sessão, na ordem em que foram
    gravadas. O retrato é tudo o que o olho extrai de um quadro (ver jogar.retrato)."""
    sessoes = []
    for nome, pasta in pastas.items():
        olhos, teclas, recompensas = [], [], []
        com_hud = True
        for arquivo in sorted(pasta.glob("parte_*.npz")):
            with np.load(arquivo) as parte:
                if "recompensas" in parte.files:
                    recompensas.append(parte["recompensas"])
                else:
                    com_hud = False
                acoes = [str(a) for a in parte["acoes"]]
                colunas = [acoes.index(a) if a in acoes else None for a in ACOES]
                anterior = None
                for tela, apertadas in zip(parte["telas"], parte["teclas"]):
                    olhos.append(retrato(tela, anterior))
                    teclas.append([apertadas[c] if c is not None else False for c in colunas])
                    anterior = tela
        if olhos:
            if com_hud and recompensas:
                pesos = pesos_por_recompensa(np.concatenate(recompensas))
            else:
                pesos = np.ones(len(olhos), dtype=np.float32)
            if nome.startswith("mosca_"):
                pesos = pesos * PESO_MOSCA
            teclas = fases_de_toque(np.array(teclas, dtype=np.float32))
            sessoes.append((nome, np.stack(olhos), teclas, pesos.astype(np.float32)))
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
        self.retratos = np.concatenate([r for _, r, _, _ in sessoes])
        self.teclas = np.concatenate([y for _, _, y, _ in sessoes])
        self.pesos = np.concatenate([w for _, _, _, w in sessoes])
        passado, treino, valid, inicio = [], [], [], 0
        for _, r, _, _ in sessoes:
            n = len(r)
            idx = np.arange(inicio, inicio + n)
            # No começo da sessão não há passado ainda: usa o quadro mais antigo,
            # como o painel faz com a memória curta ainda enchendo
            passado.append(np.maximum(idx - ATRASO_OLHO, inicio))
            corte = int(n * (1 - VALIDACAO))  # o fim de cada sessão fica para validar
            treino.append(idx[:corte])
            valid.append(idx[corte:])
            inicio += n
        self.passado = np.concatenate(passado)
        self.treino, self.valid = np.concatenate(treino), np.concatenate(valid)
        self.media = self.desvio = None

    def entrada(self, idx):
        x = entrada(VERSAO_OLHO, self.retratos[idx], self.retratos[self.passado[idx]])
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


def frente(p, x):
    h = np.maximum(0, x @ p["w1"] + p["b1"])
    return h, 1 / (1 + np.exp(-np.clip(h @ p["w2"] + p["b2"], -30, 30)))


def prever(p, dados, idx, lote=4096):
    return np.concatenate([frente(p, dados.entrada(idx[i : i + lote]))[1] for i in range(0, len(idx), lote)])


def perda(p, dados, idx, peso_pos, ponderar=False):
    prob = np.clip(prever(p, dados, idx), 1e-6, 1 - 1e-6)
    y = dados.teclas[idx]
    por_quadro = -(peso_pos * y * np.log(prob) + (1 - y) * np.log(1 - prob)).mean(axis=1)
    return float(np.average(por_quadro, weights=dados.pesos[idx] if ponderar else None))


def treinar(dados):
    """Cada quadro de treino pesa pela recompensa futura (dados.pesos). A
    validação não usa peso: mede o quanto ela imita você, para comparar treinos."""
    rng = np.random.default_rng(0)
    n_ent, n_sai = dados.entrada(dados.treino[:1]).shape[1], dados.teclas.shape[1]
    p = {
        "w1": rng.normal(0, np.sqrt(2 / n_ent), (n_ent, INTERNEURONIOS)).astype(np.float32),
        "b1": np.zeros(INTERNEURONIOS, np.float32),
        "w2": rng.normal(0, np.sqrt(1 / INTERNEURONIOS), (INTERNEURONIOS, n_sai)).astype(np.float32),
        "b2": np.zeros(n_sai, np.float32),
    }
    # Teclas raras pesam mais, senão a rede só aprende "nunca aperta"; mas pouco
    # mais (até 3x), senão ela aperta à toa teclas que não dá para prever
    frac = dados.teclas[dados.treino].mean(axis=0)
    peso_pos = np.clip((1 - frac) / np.maximum(frac, 1e-3), 1, PESO_MAXIMO).astype(np.float32)
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v = {k: np.zeros_like(v) for k, v in p.items()}
    melhor, melhor_p, passo = np.inf, None, 0
    for epoca in range(EPOCAS):
        ordem = rng.permutation(dados.treino)
        for i in range(0, len(ordem), LOTE):
            idx = ordem[i : i + LOTE]
            x, y, w = dados.entrada(idx), dados.teclas[idx], dados.pesos[idx, None]
            h, prob = frente(p, x)
            # gradiente da entropia cruzada com peso nos positivos e no quadro
            dz2 = w * (prob * (peso_pos * y + 1 - y) - peso_pos * y) / (len(x) * n_sai)
            dh = (dz2 @ p["w2"].T) * (h > 0)
            grad = {"w2": h.T @ dz2, "b2": dz2.sum(0), "w1": x.T @ dh, "b1": dh.sum(0)}
            passo += 1
            for k in p:  # Adam
                m[k] = 0.9 * m[k] + 0.1 * grad[k]
                v[k] = 0.999 * v[k] + 0.001 * grad[k] ** 2
                mh, vh = m[k] / (1 - 0.9**passo), v[k] / (1 - 0.999**passo)
                p[k] -= (TAXA * mh / (np.sqrt(vh) + 1e-8)).astype(np.float32)
        pv = perda(p, dados, dados.valid, peso_pos)
        amostra = rng.choice(dados.treino, min(5000, len(dados.treino)), replace=False)
        pt = perda(p, dados, amostra, peso_pos, ponderar=True)
        print(f"  época {epoca + 1:2d}/{EPOCAS}: perda treino {pt:.4f} · validação {pv:.4f}")
        if pv < melhor:
            melhor, melhor_p = pv, {k: a.copy() for k, a in p.items()}
    return melhor_p, melhor


def relatorio(p, dados):
    """Compara a mosca com um "chute" que sempre faz a coisa mais comum."""
    prev = prever(p, dados, dados.valid) > 0.5
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
    inicio = time.time()
    pastas = pastas_de_sessoes()
    sessoes = carregar_sessoes(pastas)
    total = sum(len(x) for _, x, _, _ in sessoes)
    quadros_mosca = sum(len(x) for n, x, _, _ in sessoes if n.startswith("mosca_"))
    if total < MINIMO_QUADROS:
        print(
            f"Só {total} quadros gravados (mínimo {MINIMO_QUADROS}). Grave mais partidas com "
            "o botão '⏺ Gravar' do painel."
        )
        return
    nomes_sessoes = [nome for nome, _, _, _ in sessoes]
    for nome, x, _, w in sessoes:
        da_mosca = nome.startswith("mosca_")
        if da_mosca:
            w = w / PESO_MOSCA  # o peso fixo da mosca não é sobre recompensa
        if np.allclose(w, 1):
            efeito = "sem dados de recompensa (peso 1)"
        else:
            efeito = (
                f"pesos de {w.min():.2f} a {w.max():.2f}; "
                f"{(w < 0.7).mean():.0%} dos quadros imitados com menos força (vieram antes de dano/parada), "
                f"{(w > 1.3).mean():.0%} com mais (antes de acerto/geo)"
            )
        origem = f" · partida da mosca (peso {PESO_MOSCA})" if da_mosca else ""
        print(f"sessão {nome}: {len(x):,} quadros ({len(x) / 30 / 60:.1f} min){origem} · {efeito}".replace(",", "."))

    dados = Dados(sessoes)
    del sessoes  # os retratos já estão em `dados`; libera a memória
    dados.normalizar()
    print(
        f"\ntreinando com {len(dados.treino):,} quadros, validando com {len(dados.valid):,} "
        f"(olho versão {VERSAO_OLHO}: {dados.entrada(dados.treino[:1]).shape[1]:,} entradas)".replace(",", ".")
    )
    p, perda_validacao = treinar(dados)
    metricas = relatorio(p, dados)

    # Salva num temporário e troca de uma vez: o painel nunca lê um modelo pela metade
    temporario = ARQUIVO_SAIDA.with_name(ARQUIVO_SAIDA.stem + ".tmp.npz")
    np.savez(
        temporario, **p, media=dados.media, desvio=dados.desvio, acoes=np.array(ACOES),
        n_quadros=total, metodo="imitação + recompensa", versao_olho=VERSAO_OLHO,
    )
    os.replace(temporario, ARQUIVO_SAIDA)
    print(f"\nmodelo salvo em {ARQUIVO_SAIDA.name} ({time.time() - inicio:.0f} s).")

    nomes = nomes_sessoes
    treino = {
        "quadros": total,
        "minutos": round(total / 30 / 60, 2),
        "quadros_validacao": len(dados.valid),
        "perda_validacao": round(float(perda_validacao), 5),
        "epocas": EPOCAS,
        "interneuronios": INTERNEURONIOS,
        "sessoes": nomes,
        "metricas": metricas,
        "config": {
            "taxa": TAXA, "lote": LOTE, "validacao": VALIDACAO, "peso_maximo": PESO_MAXIMO,
            "olho": list(OLHO), "grade_olho": list(GRADE_OLHO), "versao_olho": VERSAO_OLHO,
            "fovea": [FOVEA[0].start, FOVEA[0].stop, FOVEA[1].start, FOVEA[1].stop],
            "grade_fovea": list(GRADE_FOVEA), "atraso_olho": ATRASO_OLHO,
            "aprendizado": "imitação ponderada pela recompensa",
            "desconto": DESCONTO, "forca_recompensa": FORCA_RECOMPENSA,
            "peso_quadro": list(PESO_QUADRO),
            "git_commit": commit_do_codigo(),
            "papel": "desafiante", "quadros_mosca": quadros_mosca, "peso_mosca": PESO_MOSCA,
            "toque_s": TOQUE_S,
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
    print(
        "Nova desafiante. Ela só substitui a campeã se jogar melhor: ligue o "
        "'Controlar jogo' no painel para as duas disputarem."
    )


if __name__ == "__main__":
    main()
