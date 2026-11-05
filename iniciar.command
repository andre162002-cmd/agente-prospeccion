#!/bin/bash
# Doble clic en Mac para iniciar el agente
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "No encuentro Python. Instalalo desde https://www.python.org/downloads/"; read -p "Enter para salir"; exit 1
fi
[ -x .venv/bin/python ] || { echo "Preparando el programa por primera vez..."; python3 -m venv .venv; }
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt || { read -p "Error instalando. Enter para salir"; exit 1; }
if [ ! -f .env ]; then cp .env.example .env; echo "Pega tu clave de Google en el archivo que se abre, guarda y cierralo."; open -e -W .env; fi
echo "El agente se abrira en el navegador. No cierres esta ventana mientras lo uses."
(sleep 5; open http://127.0.0.1:8000) &
.venv/bin/python -m prospector servidor
