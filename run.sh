#!/bin/bash

# ===============================================
# STOA Agent - Run Script
# ===============================================

echo "🚀 Iniciando STOA Agent..."
echo ""

# Cores
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m'

# Verifica venv
if [ ! -d "venv" ]; then
    echo "Virtual environment não encontrado. Execute: bash setup.sh"
    exit 1
fi

# Ativa venv
source venv/bin/activate

# Verifica .env
if [ ! -f ".env" ]; then
    echo "Arquivo .env não encontrado. Execute: bash setup.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} Virtual environment ativado"
echo -e "${GREEN}✓${NC} Configuração carregada"
echo ""
echo -e "${BLUE}ℹ${NC} Iniciando servidor..."
echo ""

# Inicia o servidor
python main.py

# Se chegar aqui, o servidor foi interrompido
echo ""
echo "🛑 Servidor interrompido"
