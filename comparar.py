"""Compara as versões da mosca pelo que ela fez jogando sozinha.

Uso:
    .venv-flygym/bin/python comparar.py          # tabela + evolução versão a versão
    .venv-flygym/bin/python comparar.py 3 8      # melhoria do treino #3 para o #8

Lê as partidas (public.partidas_mosca) no Supabase e soma por treino. As taxas
são por minuto de jogo, pesadas pelo tempo de cada partida.

Melhoria % = (Y - X) / |X| x 100, com o sinal ajustado para positivo ser sempre
melhor (mortes, danos e paradas melhoram caindo). Ex.: recompensa/min de -4 para
-2 = +50%. O "±" é a incerteza (2 erros padrão, pela variação entre partidas):
se a melhoria for menor que ela, pode ser sorte.
"""

import sys
from collections import defaultdict

import numpy as np

from registro import Supabase

MINIMO_MINUTOS = 2  # menos que isso por treino ainda é pouco para comparar
METRICAS = [  # (campo, nome, maior é melhor?)
    ("recompensa_total", "recompensa/min", True),
    ("mortes", "mortes/min", False),
    ("danos", "danos/min", False),
    ("acertos", "acertos/min", True),
    ("geo", "geo/min", True),
    ("paradas", "paradas/min", False),
]


def melhoria_percentual(antes, depois, maior_melhor=True):
    """% de melhoria de `antes` para `depois` (positivo = melhor). None se antes == 0."""
    if antes == 0:
        return None
    variacao = (depois - antes) / abs(antes) * 100
    return variacao if maior_melhor else -variacao


def texto_melhoria(pct, incerteza=None):
    """`incerteza`: ± em pontos percentuais; None = não deu para medir."""
    if pct is None:
        return "— (antes era 0)"
    texto = f"{pct:+.0f}%"
    if incerteza is None:
        return texto + " (incerteza desconhecida: precisa de 2+ partidas de cada)"
    texto += f" (±{incerteza:.0f}%)"
    if abs(pct) <= incerteza:
        texto += " pode ser sorte"
    return texto


class Versao:
    """Partidas de um treino: taxas por minuto e a variação entre partidas."""

    def __init__(self, treino_id, nome):
        self.treino_id, self.nome = treino_id, nome
        self.partidas = []

    @property
    def minutos(self):
        return sum(p["segundos"] for p in self.partidas) / 60

    def por_minuto(self, campo):
        return sum(p.get(campo) or 0 for p in self.partidas) / self.minutos

    def erro_padrao(self, campo):
        """Erro padrão da taxa, pela variação entre partidas (pesadas pelo tempo)."""
        if len(self.partidas) < 2:
            return float("inf")
        taxas = np.array([(p.get(campo) or 0) / p["segundos"] * 60 for p in self.partidas])
        pesos = np.array([p["segundos"] for p in self.partidas], dtype=float)
        media = np.average(taxas, weights=pesos)
        variancia = np.average((taxas - media) ** 2, weights=pesos) * len(taxas) / (len(taxas) - 1)
        n_efetivo = pesos.sum() ** 2 / (pesos**2).sum()
        return float(np.sqrt(variancia / n_efetivo))


def comparar_duas(x, y, campo, maior_melhor):
    """(valor em x, valor em y, % de melhoria, ± incerteza em %)."""
    antes, depois = x.por_minuto(campo), y.por_minuto(campo)
    pct = melhoria_percentual(antes, depois, maior_melhor)
    erro = np.sqrt(x.erro_padrao(campo) ** 2 + y.erro_padrao(campo) ** 2)
    incerteza = 2 * erro / abs(antes) * 100 if antes and np.isfinite(erro) else None
    return antes, depois, pct, incerteza


def carregar():
    banco = Supabase.do_env()
    if banco is None:
        sys.exit("Supabase não configurado (.env).")
    partidas = banco._pedir("GET", "/rest/v1/partidas_mosca?select=*&order=inicio")
    treinos = {t["id"]: t for t in banco._pedir("GET", "/rest/v1/treinos?select=id,config")}
    versoes = {}
    for p in partidas:
        tid = p["treino_id"]
        if tid not in versoes:
            if tid is None:
                nome = "sem treino"
            else:
                metodo = (treinos.get(tid, {}).get("config") or {}).get("aprendizado", "imitação")
                nome = f"#{tid} {metodo}"[:33]
            versoes[tid] = Versao(tid, nome)
        versoes[tid].partidas.append(p)
    return versoes


def tabela(versoes):
    print(f"{'versão':<34}{'partidas':>9}{'min':>7}" + "".join(f"{nome:>16}" for _, nome, _ in METRICAS))
    for tid in sorted(versoes, key=lambda t: (t is None, t)):
        v = versoes[tid]
        aviso = " (pouco tempo)" if v.minutos < MINIMO_MINUTOS else ""
        valores = "".join(
            f"{v.por_minuto(c):>+16.2f}" if c == "recompensa_total" else f"{v.por_minuto(c):>16.2f}"
            for c, _, _ in METRICAS
        )
        print(f"{v.nome:<34}{len(v.partidas):>9}{v.minutos:>7.1f}{valores}{aviso}")


def evolucao(versoes):
    """Melhoria da recompensa/min de cada versão para a seguinte, e da primeira para a última."""
    validas = [versoes[t] for t in sorted(t for t in versoes if t is not None)
               if versoes[t].minutos >= MINIMO_MINUTOS]
    if len(validas) < 2:
        print(f"\nPara medir melhoria, preciso de 2+ versões com {MINIMO_MINUTOS}+ min de jogo cada.")
        return
    print("\nEvolução da recompensa por minuto (positivo = melhorou):")
    for x, y in zip(validas, validas[1:]):
        antes, depois, pct, inc = comparar_duas(x, y, "recompensa_total", True)
        print(f"  #{x.treino_id} → #{y.treino_id}: {antes:+.2f} → {depois:+.2f} = {texto_melhoria(pct, inc)}")
    x, y = validas[0], validas[-1]
    antes, depois, pct, inc = comparar_duas(x, y, "recompensa_total", True)
    print(f"\n  Desde a primeira medida (#{x.treino_id}) até a última (#{y.treino_id}): "
          f"{texto_melhoria(pct, inc)}")


def detalhe(versoes, a, b):
    for tid in (a, b):
        if tid not in versoes:
            sys.exit(f"O treino #{tid} ainda não tem partidas da mosca registradas.")
    x, y = versoes[a], versoes[b]
    print(f"Do treino #{a} ({x.minutos:.1f} min de jogo) para o #{b} ({y.minutos:.1f} min):\n")
    print(f"  {'medida':<16}{'#' + str(a):>10}{'#' + str(b):>10}   melhoria")
    for campo, nome, maior_melhor in METRICAS:
        antes, depois, pct, inc = comparar_duas(x, y, campo, maior_melhor)
        print(f"  {nome:<16}{antes:>10.2f}{depois:>10.2f}   {texto_melhoria(pct, inc)}")
    print("\n  Positivo = melhor. Mortes, danos e paradas melhoram caindo.")
    if min(x.minutos, y.minutos) < MINIMO_MINUTOS:
        print(f"  ⚠ pouco tempo de jogo (menos de {MINIMO_MINUTOS} min): trate como palpite.")


def main():
    versoes = carregar()
    if not versoes:
        print('Nenhuma partida ainda. Ligue "🎮 Controlar jogo" no painel e deixe a mosca jogar.')
        return
    if len(sys.argv) == 3:
        detalhe(versoes, int(sys.argv[1]), int(sys.argv[2]))
        return
    tabela(versoes)
    evolucao(versoes)


if __name__ == "__main__":
    main()
