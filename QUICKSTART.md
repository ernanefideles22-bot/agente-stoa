# ⚡ STOA Agent - Guia Rápido

## 🎯 1 Minuto para Começar

### Linux/macOS
```bash
# 1. Instalar
bash setup.sh

# 2. Configurar (editar .env com sua chave ANTHROPIC_API_KEY)
nano .env

# 3. Executar
bash run.sh
```

### Windows
```powershell
# 1. Criar ambiente
python -m venv venv
venv\Scripts\activate

# 2. Instalar
pip install -r stoa-agent-requirements.txt

# 3. Configurar
copy .env.example .env
# Edite e adicione sua chave

# 4. Executar
python main.py
```

### Docker (Mais Fácil)
```bash
# Editar .env com sua chave
nano .env

# Rodar
docker-compose up
```

## 📖 Arquivo Structure

```
stoa-agent/
├── main.py                          # ⭐ Backend principal
├── examples.py                      # Exemplos de uso
├── README.md                        # Documentação completa
├── setup.sh                         # Script de instalação
├── run.sh                           # Script para executar
├── .env.example                     # Variáveis de exemplo
├── stoa-agent-requirements.txt      # Dependências
├── Dockerfile                       # Para Docker
├── docker-compose.yml               # Docker Compose
└── .gitignore                       # Arquivos ignorados
```

## 🎤 Como Usar

### 1. Abra no navegador
```
http://localhost:8000
```

### 2. Use voz ou texto
- Clique em 🎤 para falar
- Ou digite seu comando
- Pressione Enter ou clique Enviar

### 3. Exemplos de comandos
```
"Crie um servidor FastAPI em Python"
"Como está o clima?"
"Planeje meu dia"
"Gere um website moderno"
"Explique WebSockets"
```

## 🔌 APIs Disponíveis

```bash
# Comando genérico
POST /api/command
{"text": "Crie um bot em Python"}

# Clima
GET /api/weather

# Hora
GET /api/time

# Código
POST /api/code-generate
{"prompt": "...", "language": "python"}

# Website
POST /api/website-generate
{"requirements": "..."}

# Agenda
POST /api/schedule
{"requirements": "..."}

# Health
GET /api/health

# WebSocket
WS /ws
```

## 📋 Checklist de Setup

- [ ] Python 3.9+ instalado
- [ ] Chave ANTHROPIC_API_KEY obtida (https://console.anthropic.com)
- [ ] Arquivo .env configurado
- [ ] Dependências instaladas (pip install -r requirements)
- [ ] Servidor iniciado (python main.py ou bash run.sh)
- [ ] Browser acessando http://localhost:8000
- [ ] Voz funcionando (permissão de microfone)

## 🚀 Próximos Passos

1. **Integrar com seu STOA**
   - Adicione endpoints para chamar seus módulos
   - Passe contexto do projeto para o agente

2. **Integrar com seu Trading Bot**
   - Comando: "Status do bot de trading"
   - Lê logs e estado do bot

3. **Adicionar persistência**
   - Histórico em banco de dados
   - Gravação de conversas

4. **Deployar**
   - Heroku: `git push heroku main`
   - VPS: Copie arquivos e rode systemd
   - Docker: `docker-compose up -d`

## ❓ Dúvidas Frequentes

**P: Voz não funciona**
R: Navegador moderno requerido (Chrome, Firefox). HTTPS em produção.

**P: Demora para responder**
R: Primeira resposta é mais lenta. Aumentar timeout ou usar Sonnet.

**P: API Key inválida**
R: Verifique em https://console.anthropic.com - formato deve ser sk-ant-*

**P: Port 8000 já em uso**
R: Mude PORT=9000 no .env ou: `sudo lsof -i :8000`

## 📊 Arquitetura

```
┌─────────────────────────────────────────┐
│         Frontend (Web Speech + WS)      │
│         http://localhost:8000           │
└────────────────┬────────────────────────┘
                 │
                 ▼
        ┌────────────────┐
        │  FastAPI/WS    │
        │  main.py       │
        └────────┬───────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
┌─────────┐  ┌──────┐  ┌──────────┐
│ Weather │  │ Code │  │ Planning │
│ Agent   │  │Agent │  │  Agent   │
└─────────┘  └──────┘  └──────────┘
    │            │           │
    └────────────┼───────────┘
                 ▼
        ┌────────────────┐
        │  Claude API    │
        │ (Processamento)│
        └────────────────┘
```

## 🎮 Comandos para Testar

Copie e cole no STOA Agent:

### Teste 1: Clima
```
Como está o clima agora em Chapada dos Guimarães?
```

### Teste 2: Código
```
Crie um script Python que monitora arquivos em tempo real com watchdog
```

### Teste 3: Website
```
Gere um landing page minimalista em branco e preto para um serviço de consultoria
```

### Teste 4: Planejamento
```
Monte um cronograma para hoje com: 2h desenvolvimento STOA, 1h análise de bot, 30min intervalo, 2h trading
```

### Teste 5: Educação
```
Explique passo a passo como funcionam Web Workers em JavaScript
```

## 📞 Suporte

- 📖 Docs: https://docs.claude.com
- 🐛 Issues: Crie uma issue no repositório
- 💬 Comunidade: Procure por "STOA Agent" online

---

**✨ Pronto para começar!**

Qualquer dúvida, revise o README.md completo.
