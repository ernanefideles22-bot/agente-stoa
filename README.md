# Uso mais seguro do agente STOA

Este pacote agora roda uma versão endurecida do agente dentro de `C:\Users\ernan\OneDrive\Documentos\Playground\safe-stoa`, usando a API da OpenAI em vez da Anthropic.

## O que ele faz

- Usa uma implementação local endurecida em [app/main.py](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/app/main.py).
- Gera uma imagem Docker separada, sem embutir `.env` na imagem.
- Roda o app como usuário não-root.
- Publica a porta apenas em `127.0.0.1`, então o agente não fica exposto na rede local.
- Usa filesystem somente-leitura no container, com `tmpfs` restrito para `/tmp`.
- Remove capacidades Linux extras e ativa `no-new-privileges`.
- Mantém `OPENAI_API_KEY` e `STOA_ACCESS_TOKEN` em `.env.safe`, fora do código.
- Remove o WebSocket público e usa apenas `POST /api/command` com bearer token.
- Adiciona `POST /api/super-command` para orquestrar múltiplas etapas.
- Adiciona memória curta por `session_id` com limite de mensagens.
- Salva artefatos por sessão em uma área segura de workspace.
- Adiciona `TrustedHostMiddleware` e cabeçalhos de segurança no frontend.
- Faz roteamento local por heurística, sem chamada extra ao modelo só para decidir módulo.

## Riscos que ainda existem

- Qualquer processo no seu próprio computador ainda pode acessar `http://127.0.0.1:18000` se souber o `STOA_ACCESS_TOKEN`.
- O app ainda faz chamadas externas para OpenAI e, se configurado, OpenWeather.
- O frontend guarda o token em `sessionStorage`, então ele não deve ser usado em máquina compartilhada.

## Como usar

1. Copie `.env.safe.example` para `.env.safe`.
2. Preencha `OPENAI_API_KEY`.
3. Defina um `STOA_ACCESS_TOKEN` forte.
4. Rode:

```powershell
cd C:\Users\ernan\OneDrive\Documentos\Playground\safe-stoa
.\run-safe-stoa.ps1
```

5. Abra:

```text
http://127.0.0.1:18000
```

6. Para parar:

```powershell
.\stop-safe-stoa.ps1
```

## Sem Docker

Se o Docker não estiver instalado, rode localmente:

```powershell
cd C:\Users\ernan\OneDrive\Documentos\Playground\safe-stoa
.\setup-safe-stoa-local.ps1
.\run-safe-stoa-local.ps1
```

Isso sobe o app em:

```text
http://127.0.0.1:18000
```

## Modo super agente

- No frontend, marque `usar modo super agente`.
- Esse modo cria um plano curto, executa até `MAX_PLAN_STEPS` etapas e sintetiza a resposta final.
- Os módulos permitidos ficam em `ENABLED_MODULES` no `.env.safe`.

## Memória de sessão

- O frontend guarda um `session_id` em `sessionStorage`.
- O backend mantém até `MAX_SESSION_MESSAGES` mensagens recentes por sessão.
- Você pode inspecionar a memória em `GET /api/session/{session_id}` com bearer token.

## Arquivos gerados

- Os resultados podem ser salvos automaticamente em `WORKSPACE_ROOT/<session_id>/`.
- Liste com `GET /api/files/{session_id}`.
- Leia um arquivo com `GET /api/file/{session_id}/{file_name}`.

## Área editável

- Existe uma área segura em `WORKSPACE_ROOT/<session_id>/editable/`.
- Liste com `GET /api/editable-files/{session_id}`.
- Leia um arquivo com `POST /api/read-file`.
- Crie ou sobrescreva com `POST /api/write-file`.
- Edite por instrução com `POST /api/edit-file`.
- Revise um arquivo com `POST /api/review-file`.
- Apenas extensões em `EDITABLE_EXTENSIONS` são aceitas.

## Passo 4: Entregáveis finais

- No modo super, o planejador pode sugerir `output_file` por etapa e `final_files` para os entregáveis finais.
- Quando isso acontece, o backend salva automaticamente arquivos utilizáveis na área `editable/`.
- Exemplo típico: gerar `site/index.html` ou `docs/plano.md` sem chamada extra manual.

## Passo 5: Leitura com contexto

- O agente agora pode ler arquivos existentes da área editável antes de revisar ou editar.
- Isso permite evoluir entregáveis em múltiplos passos com contexto real, sem acesso arbitrário ao disco fora da sandbox lógica do app.

## Passo 6: Visão de projeto

- Liste a árvore da área editável com `GET /api/project-tree/{session_id}`.
- Gere um resumo de vários arquivos com `POST /api/project-summary`.
- Isso permite ao agente entender um mini projeto com múltiplos arquivos antes de propor mudanças.

## Passo 7: Patch de projeto

- Use `POST /api/project-patch` para aplicar mudanças coordenadas em vários arquivos já existentes.
- O backend lê os arquivos permitidos, cria um plano de patch e edita apenas os caminhos fornecidos.
- Isso reduz risco porque o agente não pode inventar arquivos fora do conjunto autorizado nessa operação.

## Passo 8: Frontend operacional

- O frontend agora mostra sessão, árvore do projeto e arquivos editáveis.
- Dá para selecionar arquivos, ler conteúdo e pedir revisão sem sair da interface web.
- Isso reduz a necessidade de chamadas manuais à API para o ciclo básico de trabalho.
- A interface principal agora publica `manifest.webmanifest`, registra `sw.js` e expõe ícones locais em `static/pwa-icons/`, permitindo instalação do app shell no celular sem alterar os fluxos existentes.

## Endurecimento operacional

- Há rate limiting simples por token/IP para rotas `/api/`.
- A trilha de auditoria é gravada em `AUDIT_LOG_PATH`.
- Eventos críticos como comandos, patch de projeto e escrita de arquivos passam a deixar registro.

## Regressão mínima automatizada

- A suíte inicial fica em [tests/test_app.py](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/tests/test_app.py).
- Ela cobre healthcheck público, autenticação bearer, manifesto PWA, registro do service worker, trimming da memória de sessão e bloqueio de path traversal.
- Rode com:

```powershell
cd C:\Users\ernan\OneDrive\Documentos\Playground\safe-stoa
python -m unittest tests.test_app
```

## Modos de trabalho

- `builder`: prioriza criação de entregáveis, estrutura inicial e implementação.
- `operator`: prioriza revisão, organização, evolução incremental e análise de risco.
- O frontend agora expõe esses dois modos e alguns presets rápidos.

## Autopilot

- Use `autopilot` para mandar um pedido único e deixar o agente decidir se cria do zero ou aplica patch no projeto existente.
- O endpoint é `POST /api/autopilot`.
- A decisão usa os arquivos já existentes da área editável como contexto quando isso fizer sentido.

## Orchestrate

- `POST /api/orchestrate` é o modo mais próximo de um comando único.
- Ele decide entre:
  - `autopilot`
  - `run_command`
  - `prepare_editor_task`
  - `create_spreadsheet`
- O frontend agora usa esse modo por padrão quando a opção principal está marcada.

## Fila de tarefas

- `POST /api/queue-task`: adiciona uma tarefa para a sessão.
- `GET /api/queue/{session_id}`: lista tarefas.
- `POST /api/queue-run-next/{session_id}`: executa a próxima tarefa pendente.
- Isso permite empilhar objetivos para o STOA executar em sequência.

## Claude coworker v1

- O app agora também pode operar como um `coworker` de trabalho persistente, não só como executor de comando único.
- O estado fica em `COWORKER_STORE_PATH`.
- A interface principal agora já abre com a opção `coworker` marcada.

## Modelo operacional do coworker

- O coworker agora também tem um perfil operacional global por sessão.
- Esse perfil define nome, função, missão, estilo de comunicação, forças e regras de decisão.
- O perfil também inclui personas por domínio, como `business`, `product`, `code`, `operations` e `finance`.
- `Project`: contexto de trabalho com nome, resumo e root opcional.
- Cada projeto agora também tem acompanhamento operacional com `phase`, `health`, `next_action`, `blockers` e `risks`.
- Cada projeto agora também guarda memória estratégica: `preferences`, `decisions`, `facts` e `working_style`.
- `Objective`: meta de longo prazo ligada ou não a um projeto, com plano curto de milestones.
- `Task`: item de trabalho com `priority`, `status`, `task_type` e resultado.
- `Routine`: tarefa recorrente/manual reutilizável, que gera nova task operacional.
- `Action`: trilha do que o coworker executou.
- `Decision`: registro do porquê ele escolheu uma ação.

## Endpoints do coworker

- `POST /api/coworker/intake`: transforma um pedido livre em projeto e tarefa operacional.
- O intake agora também cria um `Objective` persistente para o pedido amplo.
- `POST /api/coworker/objective`: cria um objetivo explicitamente.
- `POST /api/coworker/objective/plan`: quebra um objetivo em milestones e subtarefas executáveis.
- `GET /api/coworker/{session_id}/overview`: visão geral de projetos, tarefas, rotinas e relatório da sessão.
- `GET /api/coworker/profile/{session_id}`: lê o perfil operacional do coworker.
- `POST /api/coworker/profile`: atualiza o perfil operacional do coworker.
- `POST /api/coworker/persona`: cria ou atualiza uma persona de domínio.
- `GET /api/coworker/tasks/{session_id}`: lista as tarefas do coworker ordenadas por prioridade/status.
- `POST /api/coworker/project`: cria projeto explicitamente.
- `GET /api/coworker/project-memory/{session_id}/{project_id}`: lê a memória estratégica do projeto.
- `POST /api/coworker/project-memory`: atualiza a memória estratégica do projeto.
- `GET /api/coworker/project-status/{session_id}/{project_id}`: lê o estado operacional do projeto.
- `POST /api/coworker/project-status`: atualiza estado operacional, bloqueios, risco e próxima ação.
- `POST /api/coworker/supervisor/{session_id}/{project_id}`: força uma rodada do supervisor para recalcular saúde e próxima ação.
- `GET /api/project-supervisor-worker`: mostra o estado do worker contínuo do supervisor.
- `POST /api/project-supervisor-worker/start`: liga o worker contínuo do supervisor.
- `POST /api/project-supervisor-worker/stop`: desliga o worker contínuo do supervisor.
- `GET /api/coworker/briefing/{session_id}`: lê o briefing diário mais recente da sessão.
- `POST /api/coworker/briefing/{session_id}`: gera um briefing diário manualmente.
- `GET /api/coworker/inbox/{session_id}`: lista a inbox operacional da sessão.
- `POST /api/coworker/inbox/status`: marca item da inbox como `open`, `done` ou `dismissed`.
- `POST /api/coworker/inbox/execute`: executa a ação sugerida de um item da inbox.
- `GET /api/daily-briefing-worker`: mostra o estado do worker contínuo de briefing.
- `POST /api/daily-briefing-worker/start`: liga o worker contínuo de briefing.
- `POST /api/daily-briefing-worker/stop`: desliga o worker contínuo de briefing.
- `POST /api/coworker/task`: cria tarefa explicitamente.
- `POST /api/coworker/task/update`: atualiza `status`, `priority` ou notas.
- `POST /api/coworker/routine`: cria rotina reutilizável.
- `POST /api/coworker/routine/run/{session_id}/{routine_id}`: materializa uma rotina em task.
- `POST /api/coworker/run-next/{session_id}`: executa a próxima tarefa do coworker usando o orquestrador.
- `GET /api/coworker/daily-report/{session_id}`: gera um relatório diário textual da sessão.

## Fluxo crítico de comando

- `POST /api/command` agora opera em duas fases por sessão:
  - primeiro cria um preview pendente com o módulo orquestrado e aguarda confirmação
  - depois executa com `apply` ou descarta com `cancel`
- `GET /api/pending-preview/{session_id}` expõe o estado pendente atual para inspeção operacional e testes.
- O ciclo registra eventos no histórico da sessão e no `AUDIT_LOG_PATH` com:
  - `command_preview_created`
  - `command_preview_applied`
  - `command_preview_cancelled`
  - `command_preview_apply_failed`
- A interface principal servida por `GET /` consome esse contrato explicitamente:
  - mostra preview pendente em `#previewPanel`
  - oferece `apply` e `cancel` pelos botões `#previewApplyBtn` e `#previewCancelBtn`
  - bloqueia novo comando ambíguo enquanto houver preview pendente
  - restaura o preview da sessão após recarregar a página
  - limpa a UI corretamente após `apply`, `cancel` e erro `409` de preview ausente
- Os modos da interface que alteram o roteamento do comando (`coworker`, `orchestrate`, `super agente`) agora persistem em `sessionStorage` para não quebrar a continuidade do fluxo após reload.

## Fechamento da v1

- Escopo fechado da v1:
  - backend principal com `preview -> apply/cancel` por sessão
  - interface principal servida pelo backend integrada ao fluxo de preview
  - persistência e limpeza de preview por sessão
  - bloqueio de ambiguidade enquanto houver preview pendente
  - restauração do preview após reload na interface principal
  - cobertura automatizada em [tests/test_app.py](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/tests/test_app.py)
  - validação em navegador real da interface principal no ciclo `preview -> cancel` e `preview -> apply`
- Evidência automatizada atual:
  - `python -m unittest tests.test_app -v`
  - suíte cobrindo backend do fluxo crítico e regressões mínimas do shell principal
- Evidência de uso real atual:
  - a interface principal em `GET /` foi exercitada em Microsoft Edge real em `http://127.0.0.1:18000`
  - o fluxo validado em navegador inclui preview visível, bloqueio de ambiguidade, restore por reload, cancel, apply e erro real de `apply` sem preview
- Documentação final de encerramento:
  - [docs/release-v1-closeout.md](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/docs/release-v1-closeout.md)
  - [docs/release-v1-pr.md](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/docs/release-v1-pr.md)
  - [docs/release-v1.1-hardening-backlog.md](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/docs/release-v1.1-hardening-backlog.md)
  - [docs/release-v1-commit.txt](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/docs/release-v1-commit.txt)

## Fora do escopo da v1

- `stoa_mobile.html` não faz parte do fechamento da v1 enquanto interface principal; o fluxo validado é o shell servido por `GET /`.
- Não há validação humana manual em celular nesta v1 fechada.
- Warnings antigos de `@app.on_event("startup")` e `datetime.utcnow()` permanecem fora do escopo.
- Ajustes finos visuais, polimento adicional de UX e endurecimento extra de canais secundários ficam fora deste fechamento.

## Execução do coworker

- O worker automático agora também processa tarefas do coworker antes da fila legada.
- Quando as subtarefas ligadas a um objetivo são concluídas, o objetivo é marcado como concluído.
- Quando uma tarefa de projeto é concluída, o coworker tenta extrair fatos e decisões úteis para memória futura.
- O intake, o planner de objetivos e a extração de memória agora usam a identidade operacional do coworker.
- O sistema escolhe automaticamente uma persona de domínio para cada objetivo ou tarefa ampla.
- O supervisor do coworker também recalcula a saúde do projeto, bloqueios, riscos e próxima ação após progresso ou falha.
- Se um projeto cair para `yellow` ou `red`, o supervisor cria automaticamente uma tarefa de recuperação sem duplicar a mesma ação.
- O supervisor contínuo pode rodar sozinho em segundo plano, em intervalo definido por `PROJECT_SUPERVISOR_INTERVAL_SECONDS`.
- O briefing diário contínuo pode rodar sozinho em segundo plano, em intervalo definido por `DAILY_BRIEFING_INTERVAL_SECONDS`.
- Briefings diários e alertas de recuperação agora entram numa inbox operacional por sessão.
- O frontend também aceita comando de voz via navegador compatível e pode enviar o pedido automaticamente.
- O modo de voz agora suporta palavra de ativação configurável, como `stoa`, enquanto a página estiver aberta.
- Fora do navegador, você também pode rodar um listener local de hotword no Windows via PowerShell.

## Voice daemon local

- Script principal: [stoa-voice-listener.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/stoa-voice-listener.ps1)
- Daemon:
  - [run-stoa-voice-daemon.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/run-stoa-voice-daemon.ps1)
  - [status-stoa-voice-daemon.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/status-stoa-voice-daemon.ps1)
  - [stop-stoa-voice-daemon.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/stop-stoa-voice-daemon.ps1)
- Variáveis opcionais no `.env.safe`:
  - `STOA_WAKE_WORD`
  - `STOA_VOICE_ENDPOINT`
  - `STOA_VOICE_MODE`
  - `STOA_VOICE_SESSION_ID`
  - `STOA_VOICE_CONFIDENCE`
  - `STOA_VOICE_COOLDOWN_SECONDS`
- O listener usa `System.Speech` do Windows PowerShell para ouvir o microfone padrão e mandar o comando para a API local.

## Tray e startup no Windows

- Tray residente:
  - [stoa-tray.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/stoa-tray.ps1)
  - [run-stoa-tray.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/run-stoa-tray.ps1)
  - [status-stoa-tray.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/status-stoa-tray.ps1)
  - [stop-stoa-tray.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/stop-stoa-tray.ps1)
- Inicialização automática no logon:
  - [install-stoa-startup.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/install-stoa-startup.ps1)
  - [remove-stoa-startup.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/remove-stoa-startup.ps1)
- O tray permite abrir a interface, checar status e iniciar/parar API e listener de voz.

## Supervisor local

- Supervisor único:
  - [stoa-supervisor.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/stoa-supervisor.ps1)
  - [run-stoa-supervisor.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/run-stoa-supervisor.ps1)
  - [status-stoa-supervisor.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/status-stoa-supervisor.ps1)
  - [stop-stoa-supervisor.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/stop-stoa-supervisor.ps1)
- O supervisor verifica periodicamente se API, voz e tray estão ativos e relança o que cair.

## Tarefa agendada do Windows

- Fluxo principal com o nome correto do projeto:
  - [install-stoa.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/install-stoa.ps1)
  - [uninstall-stoa.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/uninstall-stoa.ps1)
- Esses scripts instalam ou removem o STOA como conjunto local.
- Instalação:
  - [install-stoa-scheduled-task.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/install-stoa-scheduled-task.ps1)
- Remoção:
  - [remove-stoa-scheduled-task.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/remove-stoa-scheduled-task.ps1)
- A tarefa principal `STOALocalSupervisor` inicia o supervisor no logon do usuário.

## STOA Control

- Painel web simples de controle:
  - [http://127.0.0.1:18000/control](http://127.0.0.1:18000/control)
- Launchers:
  - [STOA-Control.hta](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/STOA-Control.hta)
  - [stoa-control.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/stoa-control.ps1)
  - [run-stoa-control.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/run-stoa-control.ps1)
  - [run-stoa-control.cmd](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/run-stoa-control.cmd)
- Publicação de atalhos:
  - [install-stoa-control-shortcuts.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/install-stoa-control-shortcuts.ps1)
  - [remove-stoa-control-shortcuts.ps1](C:/Users/ernan/OneDrive/Documentos/Playground/safe-stoa/remove-stoa-control-shortcuts.ps1)
- O `install-stoa.ps1` agora também publica atalhos para o painel `/control` na área de trabalho e no menu Iniciar.
- O caminho preferido agora é o painel web `/control`, porque evita `mshta` e tende a sofrer menos bloqueios do Windows Defender.
- Se o `.ps1` abrir no Bloco de Notas no seu Windows, use os wrappers `.cmd`.
- As prioridades aceitas são `critical`, `high`, `medium` e `low`.
- Os status aceitos são `pending`, `running`, `blocked`, `completed`, `failed` e `cancelled`.
- O relatório diário resume foco imediato, entregas concluídas, falhas e ações recentes.
- O briefing diário resume foco do dia, progresso, riscos/bloqueios e próxima ação recomendada.

## Worker automático da fila

- `POST /api/queue-worker/start`: liga o processamento automático.
- `POST /api/queue-worker/stop`: desliga.
- `GET /api/queue-worker`: mostra o estado atual.
- O worker roda em intervalo definido por `QUEUE_WORKER_INTERVAL_SECONDS`.

## STOA local

- A memória de sessão agora persiste em `SESSION_STORE_PATH`.
- Para rodar em segundo plano:
  - `.\run-stoa-daemon.ps1`
  - `.\status-stoa-daemon.ps1`
  - `.\stop-stoa-daemon.ps1`
- O frontend abre com `autopilot` ativo por padrão.

## Roots externos permitidos

- Você pode autorizar projetos reais fora do `safe-stoa` com `EXTERNAL_ALLOWED_ROOTS`.
- Formato:
  - `alias=C:\caminho\projeto;outro=C:\outro\caminho`
- Os conectores de editor, planilha e arquivos podem usar `root_alias` para operar nessas pastas autorizadas.

## Conectores controlados

- `POST /api/run-command`: executa comandos permitidos por `ALLOWED_COMMAND_PREFIXES`.
- `POST /api/launch-app`: abre apps permitidos por `ALLOWED_APPS`.
- Ambos deixam trilha no log de auditoria.

## Navegador guiado

- `POST /api/open-url`: abre uma URL permitida em browser permitido.
- `POST /api/prepare-browser-task`: cria um brief web e abre a URL.
- `POST /api/browser-plan`: gera um plano de execução web por etapas.
- Os domínios aceitos ficam em `ALLOWED_BROWSER_DOMAINS`.

## Passo 3: IDE e planilha

- `POST /api/open-workspace`: abre um caminho da sessão no `code` ou `cursor`.
- `POST /api/create-spreadsheet`: cria uma planilha `.csv` e pode abrir no Excel.
- `POST /api/create-excel-workbook`: cria uma planilha `.xlsx` real via automação local do Excel.
- `POST /api/update-excel-cell`: atualiza célula específica em `.xlsx`.
- Esses conectores ainda operam apenas dentro da área autorizada da sessão.

## Próximo passo: fluxo de editor

- `POST /api/open-file-in-editor`: abre um arquivo específico no `code` ou `cursor`.
- `POST /api/prepare-editor-task`: prepara um `JARVIS_TASK.md` no workspace e abre o editor já no contexto certo.

## Se quiser endurecer mais

- Rode só quando for usar e depois desligue o container.
- Use uma chave de API dedicada a esse agente.
- Troque o `STOA_ACCESS_TOKEN` periodicamente.
- Se quiser, o próximo passo é eu adicionar rate limiting e logs estruturados.
