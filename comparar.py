"""Compara as versões da mosca pelo que ela fez jogando sozinha.

Uso:
    .venv-flygym/bin/python comparar.py

Lê as partidas (public.partidas_mosca) no Supabase e soma por treino. As taxas
são por minuto de jogo, pesadas pelo tempo de cada partida, para partidas
curtas não contarem tanto quanto as longas.
"""

from collections import defaultdict

from registro import Supabase

MINIMO_MINUTOS = 2  # menos que isso por treino ainda é pouco para comparar


def main():
    banco = Supabase.do_env()
    if banco is None:
        print("Supabase não configurado (.env).")
        return
    partidas = banco._pedir("GET", "/rest/v1/partidas_mosca?select=*&order=inicio")
    if not partidas:
        print('Nenhuma partida ainda. Ligue "🎮 Controlar jogo" no painel e deixe a mosca jogar.')
        return
    treinos = {
        t["id"]: t for t in banco._pedir("GET", "/rest/v1/treinos?select=id,quadros,config")
    }

    soma = defaultdict(lambda: defaultdict(float))
    for p in partidas:
        s = soma[p["treino_id"]]
        s["partidas"] += 1
        s["minutos"] += p["segundos"] / 60
        for campo in ("recompensa_total", "mortes", "danos", "acertos", "geo", "paradas"):
            s[campo] += p.get(campo) or 0

    print(f"{'versão':<34}{'partidas':>9}{'min':>6}{'recomp/min':>12}{'mortes/min':>12}"
          f"{'danos/min':>11}{'acertos/min':>13}{'geo/min':>9}{'paradas/min':>13}")
    melhor = None
    for treino_id in sorted(soma, key=lambda t: (t is None, t)):
        s = soma[treino_id]
        if treino_id is None:
            nome = "sem treino (regras fixas)"
        else:
            metodo = (treinos.get(treino_id, {}).get("config") or {}).get("aprendizado", "imitação")
            nome = f"#{treino_id} {metodo}"[:33]
        m = s["minutos"]
        por_min = {c: s[c] / m for c in ("recompensa_total", "mortes", "danos", "acertos", "geo", "paradas")}
        aviso = " (pouco tempo)" if m < MINIMO_MINUTOS else ""
        print(f"{nome:<34}{int(s['partidas']):>9}{m:>6.1f}{por_min['recompensa_total']:>+12.2f}{por_min['mortes']:>12.2f}"
              f"{por_min['danos']:>11.2f}{por_min['acertos']:>13.2f}{por_min['geo']:>9.2f}"
              f"{por_min['paradas']:>13.2f}{aviso}")
        if m >= MINIMO_MINUTOS and (melhor is None or por_min["recompensa_total"] > melhor[1]):
            melhor = (nome, por_min["recompensa_total"])

    print()
    if melhor:
        print(f"Melhor até agora (com {MINIMO_MINUTOS}+ min de jogo): {melhor[0]} "
              f"({melhor[1]:+.2f} de recompensa por minuto).")
    else:
        print(f"Ainda nenhuma versão com {MINIMO_MINUTOS}+ min de jogo para comparar.")
    print("Recompensa por minuto: maior é melhor. Compare versões jogando no mesmo lugar do jogo.")


if __name__ == "__main__":
    main()
