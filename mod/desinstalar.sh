#!/usr/bin/env bash
# Tira o BepInEx e o plugin da pasta do jogo (o jogo volta ao original). Apague
# também a opção de inicialização na Steam.
JOGO="$HOME/.local/share/Steam/steamapps/common/Hollow Knight"
rm -rf "$JOGO/BepInEx" "$JOGO/winhttp.dll" "$JOGO/doorstop_config.ini" "$JOGO/.doorstop_version"
echo "BepInEx removido. Apague a opção de inicialização na Steam."
