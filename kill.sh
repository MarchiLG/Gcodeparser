#!/usr/bin/env bash
# Encerra o servidor GCodePen (qualquer porta).
if pkill -f "venv/bin/python -m [g]codepen"; then
  echo "GCodePen encerrado."
else
  echo "Nenhum GCodePen em execução."
fi
