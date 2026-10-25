#!/usr/bin/env bash
# Liga/desliga pelo teclado, com o painel aberto (o mesmo atalho para parar):
#   ./atalho_mosca.sh gravar      (Ctrl+Alt+G)
#   ./atalho_mosca.sh controlar   (Ctrl+Alt+C)

case "$1" in
    gravar) SINAL=USR1 ;;
    controlar) SINAL=USR2 ;;
    *) echo "uso: $0 gravar|controlar" >&2; exit 2 ;;
esac

PAINEL=$(pgrep -f 'python jogar\.py( |$)')  # pgrep: o caminho da pasta pode ter espaço
if [ -z "$PAINEL" ]; then
    notify-send -a "Mosca Knight" "Mosca Knight" "O painel não está aberto: abra com Ctrl+Alt+M" 2> /dev/null
    exit 1
fi
kill -s "$SINAL" $PAINEL
