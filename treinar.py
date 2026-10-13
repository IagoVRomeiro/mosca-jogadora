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
import subprocess
import time
from datetime import datetime

import numpy as np

from jogar import ACOES, ARQUIVO_MODELO, GRADE_OLHO, OLHO, PASTA, PASTA_GRAVACOES, ver
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
ARQUIVO_INFO_MODELO = ARQUIVO_MODELO.with_suffix(".json")  # qual treino gerou o modelo


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


def carregar_sessoes():
    """Lista de (nome, olho, teclas, pesos) por sessão, na ordem em que foram gravadas."""
    sessoes = []
    for pasta in sorted(p for p in PASTA_GRAVACOES.glob("*") if p.is_dir()):
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
                    olhos.append(ver(tela, anterior))
                    teclas.append([apertadas[c] if c is not None else False for c in colunas])
                    anterior = tela
        if olhos:
            if com_hud and recompensas:
                pesos = pesos_por_recompensa(np.concatenate(recompensas))
            else:
                pesos = np.ones(len(olhos), dtype=np.float32)
            sessoes.append(
                (pasta.name, np.stack(olhos), np.array(teclas, dtype=np.float32), pesos.astype(np.float32))
            )
    return sessoes


def resumir_sessao(pasta):
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
        gravada_em = datetime.strptime(pasta.name, "%Y-%m-%d_%H%M%S").astimezone().isoformat()
    except ValueError:
        gravada_em = None
    linha = {
        "id": pasta.name,
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


def separar(sessoes):
    treino, valid = [], []
    for _, x, y, w in sessoes:
        corte = int(len(x) * (1 - VALIDACAO))
        treino.append((x[:corte], y[:corte], w[:corte]))
        valid.append((x[corte:], y[corte:]))
    juntar = lambda partes: tuple(np.concatenate(p) for p in zip(*partes))
    return juntar(treino), juntar(valid)


def frente(p, x):
    h = np.maximum(0, x @ p["w1"] + p["b1"])
    return h, 1 / (1 + np.exp(-np.clip(h @ p["w2"] + p["b2"], -30, 30)))


def perda(p, x, y, peso_pos, w=None):
    _, prob = frente(p, x)
    prob = np.clip(prob, 1e-6, 1 - 1e-6)
    por_quadro = -(peso_pos * y * np.log(prob) + (1 - y) * np.log(1 - prob)).mean(axis=1)
    return float(np.average(por_quadro, weights=w))


def treinar(xt, yt, wt, xv, yv):
    """`wt`: peso de cada quadro de treino (recompensa futura). A validação não
    usa peso: mede o quanto ela imita você, para comparar com treinos antigos."""
    rng = np.random.default_rng(0)
    n_ent, n_sai = xt.shape[1], yt.shape[1]
    p = {
        "w1": rng.normal(0, np.sqrt(2 / n_ent), (n_ent, INTERNEURONIOS)).astype(np.float32),
        "b1": np.zeros(INTERNEURONIOS, np.float32),
        "w2": rng.normal(0, np.sqrt(1 / INTERNEURONIOS), (INTERNEURONIOS, n_sai)).astype(np.float32),
        "b2": np.zeros(n_sai, np.float32),
    }
    # Teclas raras pesam mais, senão a rede só aprende "nunca aperta"; mas pouco
    # mais (até 3x), senão ela aperta à toa teclas que não dá para prever
    frac = yt.mean(axis=0)
    peso_pos = np.clip((1 - frac) / np.maximum(frac, 1e-3), 1, PESO_MAXIMO).astype(np.float32)
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v = {k: np.zeros_like(v) for k, v in p.items()}
    melhor, melhor_p, passo = np.inf, None, 0
    for epoca in range(EPOCAS):
        ordem = rng.permutation(len(xt))
        for i in range(0, len(xt), LOTE):
            idx = ordem[i : i + LOTE]
            x, y, w = xt[idx], yt[idx], wt[idx, None]
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
        pv = perda(p, xv, yv, peso_pos)
        print(f"  época {epoca + 1:2d}/{EPOCAS}: perda treino {perda(p, xt, yt, peso_pos, wt):.4f} · validação {pv:.4f}")
        if pv < melhor:
            melhor, melhor_p = pv, {k: a.copy() for k, a in p.items()}
    return melhor_p, melhor


def relatorio(p, xv, yv):
    """Compara a mosca com um "chute" que sempre faz a coisa mais comum."""
    _, prob = frente(p, xv)
    prev = prob > 0.5
    real = yv > 0.5
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
    sessoes = carregar_sessoes()
    total = sum(len(x) for _, x, _, _ in sessoes)
    if total < MINIMO_QUADROS:
        print(
            f"Só {total} quadros gravados (mínimo {MINIMO_QUADROS}). Grave mais partidas com "
            "o botão '⏺ Gravar' do painel."
        )
        return
    for nome, x, _, w in sessoes:
        if np.allclose(w, 1):
            efeito = "sem dados de recompensa (peso 1)"
        else:
            efeito = (
                f"pesos de {w.min():.2f} a {w.max():.2f}; "
                f"{(w < 0.7).mean():.0%} dos quadros imitados com menos força (vieram antes de dano/parada), "
                f"{(w > 1.3).mean():.0%} com mais (antes de acerto/geo)"
            )
        print(f"sessão {nome}: {len(x):,} quadros ({len(x) / 30 / 60:.1f} min) · {efeito}".replace(",", "."))

    (xt, yt, wt), (xv, yv) = separar(sessoes)
    media = xt.mean(axis=0)
    desvio = xt.std(axis=0) + 0.05
    xt, xv = (xt - media) / desvio, (xv - media) / desvio
    print(f"\ntreinando com {len(xt):,} quadros, validando com {len(xv):,}".replace(",", "."))
    p, perda_validacao = treinar(xt, yt, wt, xv, yv)
    metricas = relatorio(p, xv, yv)

    # Salva num temporário e troca de uma vez: o painel nunca lê um modelo pela metade
    temporario = ARQUIVO_MODELO.with_name("modelo_mosca.tmp.npz")
    np.savez(
        temporario, **p, media=media, desvio=desvio, acoes=np.array(ACOES),
        n_quadros=total, metodo="imitação + recompensa",
    )
    os.replace(temporario, ARQUIVO_MODELO)
    print(f"\nmodelo salvo em {ARQUIVO_MODELO.name} ({time.time() - inicio:.0f} s).")

    nomes = [nome for nome, _, _, _ in sessoes]
    treino = {
        "quadros": total,
        "minutos": round(total / 30 / 60, 2),
        "quadros_validacao": len(xv),
        "perda_validacao": round(float(perda_validacao), 5),
        "epocas": EPOCAS,
        "interneuronios": INTERNEURONIOS,
        "sessoes": nomes,
        "metricas": metricas,
        "config": {
            "taxa": TAXA, "lote": LOTE, "validacao": VALIDACAO, "peso_maximo": PESO_MAXIMO,
            "olho": list(OLHO), "grade_olho": list(GRADE_OLHO),
            "aprendizado": "imitação ponderada pela recompensa",
            "desconto": DESCONTO, "forca_recompensa": FORCA_RECOMPENSA,
            "peso_quadro": list(PESO_QUADRO),
            "git_commit": commit_do_codigo(),
        },
        "codigo_versao": versao_do_codigo(),
    }
    mensagem, treino_id = registrar_treino(
        [resumir_sessao(PASTA_GRAVACOES / n) for n in nomes], treino, ARQUIVO_MODELO, PASTA_GRAVACOES
    )
    print(mensagem)
    # O painel lê isto para dizer, nas partidas, qual treino estava jogando
    ARQUIVO_INFO_MODELO.write_text(json.dumps({"treino_id": treino_id, "n_quadros": total}))
    print("O painel troca o cérebro sozinho quando o treino termina por lá; rodando à mão, reabra o painel.")


if __name__ == "__main__":
    main()
