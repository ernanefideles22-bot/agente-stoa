# STOA Agent - API Documentation

## Visão Geral

O STOA Agent é um sistema multimodal com backend FastAPI que orquestra conversas, planejamento, preview/apply/cancel, e controle de dispositivos. A arquitetura é orientada a estado com persistência SQLite e fluxo crítico preview obrigatório antes de mutações.

## Endpoints Principais

### Core Conversation & Commands

#### POST `/api/command`
Processa comandos via REST API.
- **Body**: `VoiceCommand` (text, language, timestamp)
- **Response**: `AgentResponse` com mode, status, response, details
- **Uso**: Interface principal para comandos textuais

#### WebSocket `/ws`
Comunicação em tempo real.
- **Query**: `token` (opcional, se auth configurado)
- **Mensagem**: `{"text": "comando"}`
- **Response**: `{"response": "...", "module": "...", "action_type": "..."}`

### Device Control

#### GET `/api/devices`
Lista dispositivos registrados.
- **Response**: `{items: [...], count: N, timestamp: "..."}`

#### POST `/api/devices/register`
Registra novo dispositivo.
- **Body**: `DeviceRegistration`
- **Response**: `{device: {...}, status: "registered", message: "..."}`

#### POST `/api/devices/actions`
Cria ação para dispositivo.
- **Body**: `ActionRequest`
- **Response**: `{action: {...}, requires_confirmation: bool, message: "..."}`

#### POST `/api/devices/actions/{action_id}/confirm`
Confirma ação sensível.
- **Body**: `DeviceActionConfirmation`
- **Response**: `{action: {...}, message: "..."}`

#### POST `/api/devices/{device_id}/actions/{action_id}/result`
Submete resultado de ação.
- **Body**: `ActionResult`
- **Response**: `{action: {...}, message: "..."}`

### Operational Monitoring

#### GET `/api/health`
Status de saúde do sistema.
- **Response**: `{status: "online", agent: "...", timestamp: "...", location: "...", devices_registered: N}`

#### GET `/api/events/timeline`
Timeline de eventos de execução.
- **Query**: `goal_id`, `operation_id`, `phase`, `severity`, `event_domain`, `limit`
- **Response**: `{items: [...], summary: {...}, filters: {...}}`

#### GET `/api/events/summary`
Resumo de eventos.
- **Query**: `goal_id`, `operation_id`, `phase`, `severity`, `event_domain`, `limit`
- **Response**: `{summary: {...}, count: N, filters: {...}}`

### Preview & Changeset

#### GET `/api/preview/health`
Status do módulo preview.
- **Response**: `{status: "ok"}`

#### POST `/api/preview` (via planner_router)
Gera preview de mudanças.
- **Body**: ChangeSet request
- **Response**: Preview result com steps, files, summary

#### POST `/api/preview/{id}/apply`
Aplica preview pendente.
- **Response**: Application result

#### POST `/api/preview/{id}/cancel`
Cancela preview pendente.
- **Response**: Cancellation confirmation

### Preflight

#### GET `/api/preflight/health`
Status do módulo preflight.
- **Response**: `{status: "ok"}`

#### POST `/api/preflight/check`
Valida changeset antes de aplicação.
- **Body**: ChangeSet
- **Response**: Preflight result com errors/warnings

### Planner

#### GET `/api/planner/health`
Status do módulo planner.
- **Response**: `{status: "ok"}`

#### POST `/api/planner/plan`
Cria plano estruturado.
- **Body**: Planning request
- **Response**: Plan com steps, goals, risks

### Specialized Agents

#### POST `/api/voice`
Transcreve áudio para texto.
- **Body**: Audio file (webm/ogg/mp4)
- **Response**: `{text: "...", language: "pt-BR"}`

#### POST `/api/code-generate`
Gera código via OpenAI.
- **Body**: `{prompt: "...", language: "python"}`
- **Response**: `{code: "...", language: "...", generated_at: "..."}`

#### POST `/api/website-generate`
Gera website HTML.
- **Body**: `{requirements: "..."}`
- **Response**: `{html: "...", css: "...", js: "..."}`

#### POST `/api/schedule`
Cria agenda/plano.
- **Body**: `{requirements: "..."}`
- **Response**: `{schedule: "...", created_at: "..."}`

#### POST `/api/weather`
Obtém dados climáticos.
- **Response**: `{temperature: N, humidity: N, description: "...", ...}`

#### GET `/api/time`
Obtém hora atual.
- **Response**: `{timestamp: "...", time: "...", date: "...", day: "..."}`

### Memory System

#### GET `/api/memory/recent`
Memórias recentes (episódicas + semânticas + projeto).
- **Query**: `limit`
- **Response**: `{items: [...], count: N, stats: {...}}`

#### POST `/api/memory/save`
Salva memória manualmente.
- **Body**: `{text: "...", category: "semantic"}`
- **Response**: `{id: "...", text: "...", category: "..."}`

#### DELETE `/api/memory/{mem_id}`
Apaga memória específica.

### Static Assets (PWA)

#### GET `/`
Frontend principal (stoa_mobile.html)

#### GET `/manifest.webmanifest`
Manifesto PWA

#### GET `/sw.js`
Service Worker

#### GET `/icons/{icon_name}`
Ícones PWA

## Estados e Fluxos Críticos

### Preview/Apply/Cancel Flow
1. **Preview**: Gera changeset simulado, armazena em `pending_preview` (TTL 15min)
2. **Apply**: Aplica changeset armazenado se preview válido
3. **Cancel**: Remove preview pendente

### Device Action Flow
1. **Request**: Cria ação com confirmação se sensível
2. **Confirm**: Libera ação para execução
3. **Execute**: Device local executa e reporta resultado

### Operational States
- `working_context`: Contexto atual (goal, files, plan_steps)
- `active_goal`: Objetivo em andamento com steps
- `pending_preview`: Preview aguardando apply/cancel
- `operational_state`: Estado de risco/decisão atual

## Segurança e Validação

- **Guardrail**: Validação de ações device e respostas
- **Preflight**: Verificação de conflitos antes de apply
- **Confirmation**: Ações sensíveis requerem confirmação explícita
- **TTL**: Previews expiram automaticamente
- **Audit**: Todos os eventos logados em `operation_log.py`

## Dependências Externas

- **OpenAI API**: Conversa, código, transcrição voz
- **OpenWeatherMap**: Dados climáticos
- **SQLite**: Persistência local de estados
- **ChromaDB**: Memória vetorial (opcional)

## Desenvolvimento

Para testar localmente:
```bash
python main.py
# Acesse http://localhost:8000/docs para OpenAPI docs
```

Para contribuir:
1. Adicione testes em `tests/`
2. Documente novos endpoints aqui
3. Preserve contratos existentes
4. Teste preview/apply/cancel flow