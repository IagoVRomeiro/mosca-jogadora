"""Estatísticas por chefe: cada luta, sua ou dela, tirada das gravações.

Uma luta é uma passagem por uma arena de chefe do Salão dos Deuses (estátua ou
panteão): quadros seguidos na mesma sala de luta. De cada uma sai a duração, o
dano tomado, os golpes, quanto da vida do chefe ela tirou, as curas, as magias e
se venceu: chefe derrotado e nenhuma derrota ("morte") até FOLGA_QUADROS depois.

As gravações dela são apagadas depois de algumas horas (treinar.py), então o
resumo de cada gravação fica guardado para sempre em estatisticas_lutas.json,
mesmo depois que a gravação some. Gravação que ainda está crescendo é relida.

Limite: antes de 20/10 15:05 o plugin não contava derrota no Salão; nessas
gravações, numa luta de vários chefes (Sisters of Battle, Nailmasters…), matar
um deles e perder ainda conta como vitória.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .config import PASTA, PASTA_GRAVACOES, PASTA_GRAVACOES_MOSCA

ARQUIVO = PASTA / "estatisticas_lutas.json"
VERSAO = 1  # muda se o jeito de cortar as lutas mudar (relê tudo o que ainda existe)
FOLGA_QUADROS = 150  # ~5 s depois de sair da arena: a derrota chega na volta
QUADROS_S = 30
# Salas do Salão dos Deuses que não são lutas (passagens, bancos, portas)
SALAS_SEM_LUTA = ("GG_Workshop", "GG_Atrium", "GG_Spa", "GG_Engine", "GG_End_Sequence", "GG_Unn",
                  "GG_Blue_Room", "GG_Boss_Door", "GG_Unlock", "GG_Lurker", "GG_Pipeway", "GG_Waterways")
EVENTOS = ("dano", "acerto", "dano_chefe", "cura", "magia", "perigo", "chefe_derrotado", "morte")


def e_luta(cena):
    return bool(cena) and cena.startswith("GG_") and not cena.startswith(SALAS_SEM_LUTA)


def nome_da_luta(cena):
    return cena.removeprefix("GG_").replace("_", " ")


def _chave(pasta):
    partes = sorted(pasta.glob("parte_*.npz"))
    return f"{len(partes)}|{sum(p.stat().st_size for p in partes)}"


def lutas_da_gravacao(pasta, quem):
    """As lutas de uma gravação: [{"sala", "quem", "inicio", "segundos", "venceu",
    "completa", eventos...}]. Lê só as colunas pequenas (sala e eventos), não as telas."""
    cenas, contagens, nomes_ok = [], [], True
    for arquivo in sorted(Path(pasta).glob("parte_*.npz")):
        with np.load(arquivo) as parte:
            n = len(parte["teclas"])
            if "jogo_cena" not in parte.files or "eventos" not in parte.files:
                cenas += [""] * n
                contagens.append(np.zeros((n, len(EVENTOS)), np.int16))
                continue
            salas = [str(c) for c in parte["jogo_cenas"]]
            cenas += [salas[i] if i >= 0 else "" for i in parte["jogo_cena"]]
            nomes = [str(x) for x in parte["eventos_nomes"]]
            ev = parte["eventos"]
            contagens.append(np.stack([ev[:, nomes.index(e)] if e in nomes else np.zeros(n, ev.dtype)
                                       for e in EVENTOS], axis=1).astype(np.int16))
            nomes_ok &= "morte" in nomes
    if not cenas:
        return []
    ev = np.concatenate(contagens)
    inicio = datetime.strptime(Path(pasta).name[:17], "%Y-%m-%d_%H%M%S")
    lutas, i, n = [], 0, len(cenas)
    while i < n:
        if not e_luta(cenas[i]):
            i += 1
            continue
        j = i
        while j < n and cenas[j] == cenas[i]:
            j += 1
        soma = ev[i:j].sum(axis=0)
        # a derrota chega logo depois de sair da arena, mas só até a próxima luta começar
        k = j
        while k < n and k < j + FOLGA_QUADROS and not e_luta(cenas[k]):
            k += 1
        depois = ev[j:k].sum(axis=0)
        luta = {e: int(v) for e, v in zip(EVENTOS, soma)}
        derrota = luta["morte"] + int(depois[EVENTOS.index("morte")])
        lutas.append({
            **luta,
            "sala": cenas[i], "quem": quem,
            "inicio": (inicio + timedelta(seconds=i / QUADROS_S)).isoformat(timespec="seconds"),
            "segundos": round((j - i) / QUADROS_S, 1),
            "venceu": bool(luta["chefe_derrotado"] > 0 and derrota == 0),
            # cortada pelo fim da gravação: não dá para saber como terminou
            "completa": j < n,
        })
        i = j
    return lutas


def carregar(arquivo=ARQUIVO):
    """Todas as lutas (suas e dela), da mais antiga para a mais nova. Atualiza o
    resumo guardado com as gravações novas ou que cresceram."""
    arquivo = Path(arquivo)
    try:
        guardado = json.loads(arquivo.read_text())
    except (OSError, ValueError):
        guardado = {}
    if guardado.get("versao") != VERSAO:
        guardado = {"versao": VERSAO, "gravacoes": guardado.get("gravacoes", {}) if guardado else {}}
        for g in guardado["gravacoes"].values():
            g["chave"] = None  # relê o que ainda existe com o jeito novo
    mudou = False
    for raiz, quem in ((PASTA_GRAVACOES, "voce"), (PASTA_GRAVACOES_MOSCA, "mosca")):
        for pasta in sorted(p for p in Path(raiz).glob("*") if p.is_dir()):
            nome = f"{quem}_{pasta.name}"
            chave = _chave(pasta)
            if guardado["gravacoes"].get(nome, {}).get("chave") == chave:
                continue
            try:
                lutas = lutas_da_gravacao(pasta, "correcao" if pasta.name.endswith("_correcao") else quem)
            except (OSError, ValueError, KeyError):
                continue  # parte sendo escrita agora: fica para a próxima
            guardado["gravacoes"][nome] = {"chave": chave, "lutas": lutas}
            mudou = True
    if mudou:
        temporario = arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(guardado, ensure_ascii=False))
        temporario.replace(arquivo)
    todas = [luta for g in guardado["gravacoes"].values() for luta in g["lutas"]]
    return sorted(todas, key=lambda luta: luta["inicio"])


def resumo(lutas):
    """Por minuto e por luta, de um conjunto de lutas completas."""
    completas = [x for x in lutas if x["completa"]]
    minutos = sum(x["segundos"] for x in completas) / 60
    if not completas or minutos <= 0:
        return None
    por_min = {e: sum(x[e] for x in completas) / minutos for e in ("acerto", "dano", "cura", "magia", "perigo")}
    return {
        "lutas": len(completas),
        "vitorias": sum(x["venceu"] for x in completas),
        "minutos": minutos,
        "segundos_por_luta": minutos * 60 / len(completas),
        "melhor_chefe": max(min(x["dano_chefe"], 100) for x in completas),
        **por_min,
    }
