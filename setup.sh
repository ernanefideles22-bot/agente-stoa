#!/bin/bash

# ===============================================
# STOA Agent - Setup Script
# ===============================================

set -e

echo "🚀 STOA Agent - Setup Inicial"
echo "=============================="
echo ""

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Função para imprimir com cor
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Verifica Python
print_info "Verificando Python..."
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 não encontrado. Por favor, instale Python 3.9+"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
print_success "Python $PYTHON_VERSION encontrado"

# Cria venv
print_info "Criando virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_success "Virtual environment criado"
else
    print_warning "Virtual environment já existe"
fi

# Ativa venv
print_info "Ativando virtual environment..."
source venv/bin/activate
print_success "Virtual environment ativado"

# Upgrade pip
print_info "Atualizando pip..."
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
print_success "pip atualizado"

# Instala dependências
print_info "Instalando dependências..."
if [ -f "stoa-agent-requirements.txt" ]; then
    pip install -r stoa-agent-requirements.txt
    print_success "Dependências instaladas"
else
    print_error "stoa-agent-requirements.txt não encontrado"
    exit 1
fi

# Configura .env
print_info "Configurando variáveis de ambiente..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    print_warning ".env criado. CONFIGURE SUA CHAVE ANTHROPIC_API_KEY!"
    print_info "Edite .env e adicione:"
    echo "  ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE"
    echo ""
    exit 0
else
    print_success ".env já existe"
fi

# Verifica ANTHROPIC_API_KEY
if ! grep -q "ANTHROPIC_API_KEY=sk-ant" .env; then
    print_error ".env não contém ANTHROPIC_API_KEY válida"
    print_info "Edite o arquivo .env e adicione sua chave"
    exit 1
fi

print_success "Configuração verificada"
echo ""
print_success "Setup concluído com sucesso! ✨"
echo ""
print_info "Para iniciar o STOA Agent, execute:"
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
print_info "Ou execute:"
echo "  bash run.sh"
echo ""
print_info "O servidor estará disponível em: http://localhost:8000"
