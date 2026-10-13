#!/usr/bin/env bash
# Wrapper do GCodePen: ./run.sh serve --port 8000  |  ./run.sh text "Olá" -o saida.gcode
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if [ ! -x .venv/bin/python ]; then
  echo "Criando .venv e instalando dependências…" >&2
  python3 -m venv --system-site-packages .venv
  .venv/bin/pip install -q -r requirements.txt
fi

exec .venv/bin/python -m gcodepen "$@"
