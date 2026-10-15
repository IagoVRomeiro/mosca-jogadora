#!/usr/bin/env bash
# Treinar a mosca neste computador (sem o jogo): na primeira vez cria o ambiente
# Python; depois baixa as gravações novas do PC do jogo e treina (notebook.py).
# Uso: ./notebook.sh [opções do treinar.py, ex.: --arquitetura conectoma]
set -e
cd "$(dirname "$0")"
if [ ! -x .venv-flygym/bin/python ]; then
    echo "Criando o ambiente Python (só na primeira vez)…"
    python3 -m venv .venv-flygym || { echo "Falta o venv: sudo apt install python3-venv"; exit 1; }
    .venv-flygym/bin/pip install -q "numpy>=2.0.2,<3"
fi
exec .venv-flygym/bin/python notebook.py treinar "$@"
