#!/usr/bin/env bash
# Abre tudo da mosca jogadora: o Hollow Knight (pela Steam), o painel e o painel de
# evolução. Não liga o "Controlar jogo": o jogo abre no menu, e a mosca apertando
# teclas ali poderia escolher opções do menu. Carregue o save e ligue no painel.
#
# Uso: ./iniciar_mosca.sh   (ou o atalho/ícone "Mosca jogadora")

PASTA="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$PASTA/.venv-flygym/bin/python"
LOG="$PASTA/iniciar_mosca.log"
cd "$PASTA" || exit 1

avisar() {  # notificação na tela (e no log)
    echo "$(date '+%H:%M:%S') $1" >> "$LOG"
    command -v notify-send > /dev/null && notify-send -a "Mosca jogadora" "Mosca jogadora" "$1"
}

janela_do_jogo() { xwininfo -root -tree 2> /dev/null | grep -q '"Hollow Knight"'; }

# 1. O jogo (se ainda não estiver aberto)
if ! janela_do_jogo; then
    avisar "Abrindo o Hollow Knight…"
    steam -applaunch 367520 > /dev/null 2>&1 &
    for _ in $(seq 1 90); do  # espera até 3 minutos (a Steam pode precisar abrir antes)
        janela_do_jogo && break
        sleep 2
    done
    if ! janela_do_jogo; then
        avisar "O Hollow Knight não abriu em 3 minutos. Abra o jogo e rode de novo."
        exit 1
    fi
    sleep 5  # dá tempo da janela do jogo terminar de abrir
fi

# 2. O painel da mosca (se ainda não estiver aberto)
if ! pgrep -f "python jogar.py" > /dev/null; then
    avisar "Abrindo o painel da mosca…"
    setsid "$PYTHON" jogar.py --janela >> "$LOG" 2>&1 < /dev/null &
fi

# 3. O painel de evolução (se ainda não estiver aberto)
if ! pgrep -f "python evolucao.py" > /dev/null; then
    setsid "$PYTHON" evolucao.py >> "$LOG" 2>&1 < /dev/null &
fi

avisar "Pronto. Carregue o save e aperte Ctrl+Alt+C (mosca joga) ou Ctrl+Alt+G (você grava)."
