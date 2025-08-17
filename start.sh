#!/bin/bash
set -e

# Entrar na pasta do script
cd "$(dirname "$0")"

# Ativar ambiente virtual se existir
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Instalar dependências
pip install -r requirements.txt

# Rodar Flask
python3 painel_unificado.py
