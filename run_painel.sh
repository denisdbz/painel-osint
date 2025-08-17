#!/bin/bash
set -e
cd "$(dirname "$0")"

# Ativar ambiente virtual se existir
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Instalar dependências
pip install -r requirements.txt

# Rodar painel Flask em background
python3 painel_unificado.py &

# Guardar PID do Flask pra poder matar depois, se quiser
FLASK_PID=$!

# Aguardar alguns segundos pro Flask iniciar
sleep 5

# Rodar Ngrok expondo a porta 5050
ngrok http 5050
