#!/usr/bin/env bash
# Instala o plugin de eventos da mosca no Hollow Knight (o BepInEx já está na
# pasta do jogo). Depois, na Steam: Hollow Knight > Propriedades > Geral >
# Opções de inicialização:  WINEDLLOVERRIDES="winhttp=n,b" %command%
set -e
JOGO="$HOME/.local/share/Steam/steamapps/common/Hollow Knight"
PLUGIN="$(dirname "$0")/MoscaEventos/bin/Release/net472/MoscaEventos.dll"
[ -f "$JOGO/winhttp.dll" ] || { echo "BepInEx não está na pasta do jogo"; exit 1; }
mkdir -p "$JOGO/BepInEx/plugins"
cp "$PLUGIN" "$JOGO/BepInEx/plugins/"
echo "Plugin instalado."
# o lembrete só se a opção de inicialização ainda não estiver na Steam
if ! grep -qs 'winhttp=n,b' "$HOME"/.local/share/Steam/userdata/*/config/localconfig.vdf; then
    echo "Falta a opção de inicialização na Steam:"
    echo '  WINEDLLOVERRIDES="winhttp=n,b" %command%'
fi
