# STOA Agent

Sistema multimodal com reconhecimento de voz, múltiplos agentes e integração com APIs. Backend FastAPI com frontend PWA.

## Arquitetura

### Componentes Principais

- **Backend**: FastAPI (Python)
- **Frontend**: PWA (Progressive Web App)
- **Banco**: SQLite com persistência de estado
- **Comunicação**: REST API + WebSocket
- **IA**: OpenAI GPT-4 (conversacional, código, voz)

### Fluxos Críticos

1. **Preview/Apply/Cancel**: Mutação obrigatória passa por preview
2. **Device Control**: Ações sensíveis requerem confirmação
3. **State Management**: Estados persistidos com locks

### Módulos

#### Núcleo
- `main.py`: Cérebro central (STOAQuantumBrain) - orquestração e roteamento
- `executive_orchestrator.py`: Decisão de intent/risco para preview/apply/cancel

#### Planejamento e Execução (Separados)
- `planner_symbol.py`: Classes `Planner` e `Executor` - lógica especializada
  - `Planner`: Criação e gestão de previews
  - `Executor`: Execução de comandos básicos (ler, validar, listar)
- `planner_main.py`: Endpoints REST para planejamento (`/api/planner/*`, `/api/executor/*`)
- `dev_planner.py`: Lógica de planejamento de mudanças
- `dev_executor.py`: Execução de operações de desenvolvimento

#### Controle de Dispositivos
- `device_control_*`: Controle de dispositivos com confirmação obrigatória
- `device_routes.py`: Endpoints de device control

#### Operações e Monitoramento
- `ops_routes.py`: Monitoramento operacional e métricas
- `operation_log.py`: Log estruturado de operações
- `state_store.py`: Persistência com mecanismo de lock para concorrência

#### Desenvolvimento
- `dev_*`: Ferramentas de desenvolvimento (parser, changeset, preflight)

## Instalação

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar ambiente
cp env.example .env
# Editar .env com suas chaves API

# Executar
python main.py
```

## API

### Endpoints Principais

Ver [API_DOCUMENTATION.md](API_DOCUMENTATION.md) para documentação completa.

#### Core
- `POST /api/command` - Processar comandos
- `WebSocket /ws` - Comunicação em tempo real

#### Device Control
- `GET /api/devices` - Listar dispositivos
- `POST /api/devices/register` - Registrar device
- `POST /api/devices/actions` - Criar ação
- `POST /api/devices/actions/{id}/confirm` - Confirmar ação

#### Operacional
- `GET /api/health` - Status do sistema
- `GET /api/events/timeline` - Timeline de eventos

#### Preview
- `GET /api/preview/health` - Status preview
- `POST /api/preview` - Gerar preview
- `POST /api/preview/{id}/apply` - Aplicar preview
- `POST /api/preview/{id}/cancel` - Cancelar preview

## Testes

```bash
# Executar todos os testes
python -m pytest tests/ -v

# Testes básicos (recomendado)
python -m pytest tests/test_basic.py -v

# Testes de lock do StateStore
python -m pytest tests/test_state_store_lock.py -v
```

## Redis (opcional)

- Configure `STOA_STATE_REDIS_URL` para habilitar armazenamento compartilhado de preview:
  - `redis://user:pass@host:6379/0`
  - `rediss://...` para TLS
- Quando presente, `StateStore` usa Redis para `pending_preview`, `applied_state` e locks
- Se não configurado ou Redis não disponível, continua com SQLite local com lock a nível de arquivo
- Teste manual:
  - `STOA_STATE_REDIS_URL=redis://localhost:6379 pytest -q`

## Cloudflare Tunnel (opcional)

- Execute `install_cloudflared.bat` no Windows (linha de comando incluída no repositório).
- Acesse sua conta Cloudflare e crie um Tunnel chamado `stoa` (ou outro nome), com routing para:
  - `Service: http://localhost:8000`
- Configure hostname público no painel:
  - `https://stoa.seudominio.com` (ou o subdomínio desejado).
- No `.env`, set:
  - `PUBLIC_URL=https://stoa.seudominio.com`
- Para teste rápido sem configurar DNS:
  - `cloudflared tunnel --url http://localhost:8000`

> Se estiver usando `PUBLIC_URL`, verifique que o frontend (PWA) e o backend respondem corretamente pelas rotas esperadas.

### Cobertura de Testes

- ✅ Validações básicas (JSON, datetime, estruturas)
- ✅ Modelos mockados (VoiceCommand, AgentResponse)
- ✅ Padrões de comando (confirmação, device, ops)
- ✅ StateStore com lock (concorrência)
- 🔄 Endpoints FastAPI (em desenvolvimento)

## Desenvolvimento

### Regras

- Preview obrigatório antes de apply
- Ações device sensíveis requerem confirmação
- Estado persistido com locks para evitar race conditions
- Contratos públicos preservados

### Contribuição

1. Adicionar testes para novas funcionalidades
2. Documentar endpoints em `API_DOCUMENTATION.md`
3. Preservar fluxos críticos existentes
4. Executar testes antes de commit

## Monitoramento

### Health Checks
- `/api/health` - Status geral
- `/api/preview/health` - Módulo preview
- `/api/preflight/health` - Módulo preflight

### Logs
- `operation_log.py` - Eventos de operação
- `execution_event_query.py` - Consultas de eventos
- `trajectory_correlation.py` - Correlação de trajetórias

### Métricas
- Timeline de eventos: `/api/events/timeline`
- Resumo operacional: `/api/events/summary`
- Correlações: `/api/events/trajectories`

## Segurança

- Guardrail para validação de ações
- Preflight para conflitos
- Confirmação explícita para ações sensíveis
- Rate limiting (planejado)
- Whitelist de dispositivos (planejado)

## Roadmap

### Curto Prazo (2-4 dias)
- ✅ Documentação API consolidada
- ✅ Testes unitários básicos
- ✅ Lock no StateStore

### Médio Prazo (2-4 semanas)
- Endpoints REST explícitos para preview/apply/cancel
- Testes de integração completos
- Melhor UX no PWA

### Longo Prazo (1-2 meses)
- Multi-instance com Redis/Postgres
- Rollback automático
- Audit trail avançado
- Modularização em pacotes

---

Para mais detalhes, consulte `API_DOCUMENTATION.md` e `INTEGRATION_GUIDE.md`.
