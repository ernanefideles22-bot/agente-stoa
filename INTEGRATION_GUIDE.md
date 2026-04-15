# 🔗 Integração com STOA e Trading Bot

Este guia mostra como conectar o STOA Agent com seus projetos existentes.

## 1️⃣ Integração com STOA Platform

### Adicionar Agente ao seu FastAPI STOA

**Passo 1: Instalar Cliente Anthropic no seu STOA**

```bash
pip install anthropic
```

**Passo 2: Criar módulo de agente em seu STOA**

`stoa/modules/agent.py`:
```python
from anthropic import Anthropic
from typing import Optional

class STOAAgent:
    """Agente IA integrado ao STOA"""
    
    def __init__(self, project_id: str):
        self.client = Anthropic()
        self.project_id = project_id
        self.conversation = []
    
    async def process_command(self, command: str) -> str:
        """Processa comando com contexto do projeto"""
        
        # Busca contexto do projeto
        project_context = await self.get_project_context()
        
        # Monta mensagem com contexto
        system_prompt = f"""Você é agente IA integrado ao STOA Platform.
        
Contexto do Projeto:
- Nome: {project_context.get('name')}
- Módulos: {', '.join(project_context.get('modules', []))}
- Progresso: {project_context.get('progress')}

Você pode:
1. Gerar código
2. Criar designs
3. Planejar tarefas
4. Analisar estrutura
5. Sugerir melhorias

Responda em português."""
        
        self.conversation.append({
            "role": "user",
            "content": command
        })
        
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            system=system_prompt,
            messages=self.conversation
        )
        
        answer = response.content[0].text
        self.conversation.append({
            "role": "assistant",
            "content": answer
        })
        
        return answer
    
    async def get_project_context(self) -> dict:
        """Busca contexto do projeto STOA"""
        # Conecta ao banco do STOA
        from stoa.models import Project
        
        project = await Project.get(self.project_id)
        
        return {
            "name": project.name,
            "description": project.description,
            "modules": [m.name for m in project.modules],
            "progress": project.progress_percentage,
            "last_update": project.updated_at
        }
    
    async def suggest_improvements(self) -> str:
        """Sugere melhorias para o projeto"""
        context = await self.get_project_context()
        
        prompt = f"""Analise este projeto STOA e sugira 3 melhorias:
        
Nome: {context['name']}
Módulos: {context['modules']}
Progresso: {context['progress']}%

Foque em:
1. Features importantes faltando
2. Arquitetura/performance
3. UX/acessibilidade

Formato: Liste cada melhoria com prioridade (Alta/Média/Baixa)"""
        
        return await self.process_command(prompt)
```

**Passo 3: Criar endpoint no STOA**

No seu `stoa/routes/agent.py`:
```python
from fastapi import APIRouter, Depends
from stoa.modules.agent import STOAAgent

router = APIRouter(prefix="/api/agent", tags=["agent"])

@router.post("/command/{project_id}")
async def agent_command(project_id: str, command_data: dict):
    """Processa comando de agente para projeto"""
    agent = STOAAgent(project_id)
    response = await agent.process_command(command_data["command"])
    return {"response": response}

@router.get("/suggestions/{project_id}")
async def get_suggestions(project_id: str):
    """Obtém sugestões de melhorias"""
    agent = STOAAgent(project_id)
    suggestions = await agent.suggest_improvements()
    return {"suggestions": suggestions}
```

**Passo 4: Usar no Frontend STOA**

```javascript
// Em seu React/Vue do STOA
async function askAgent(projectId, command) {
    const response = await fetch(
        `/api/agent/command/${projectId}`,
        {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command })
        }
    );
    
    return await response.json();
}

// Usar
const result = await askAgent("project-123", "Crie componente de input para orçamento");
console.log(result.response);
```

---

## 2️⃣ Integração com Trading Bot

### Adicionar Agente ao seu Bot de Trading

**Passo 1: Criar módulo agent no bot**

`bot/agents/trading_agent.py`:
```python
from anthropic import Anthropic
from bot.services.db import get_trades, get_performance
from bot.services.exchange import get_price, get_balance
from datetime import datetime, timedelta

class TradingAgent:
    """Agente para análise e controle do bot de trading"""
    
    def __init__(self, bot_instance):
        self.client = Anthropic()
        self.bot = bot_instance
        self.conversation = []
    
    async def analyze_performance(self, hours: int = 24) -> str:
        """Analisa performance do bot"""
        
        # Busca dados
        trades = await get_trades(hours=hours)
        perf = await get_performance()
        balance = await get_balance()
        
        summary = f"""
Análise de Trading - Últimas {hours}h:

📊 Performance:
- Win Rate: {perf['win_rate']}%
- Profit/Loss: {perf['pnl']}%
- Trades: {len(trades)} ({perf['wins']}W/{perf['losses']}L)

💰 Conta:
- Saldo: ${balance['total']}
- Lucro: ${balance['profit']}
- Drawdown: {balance['drawdown']}%

🎯 Últimos Trades:
{self._format_trades(trades[-5:])}
"""
        
        return await self.ask(f"Analise esta performance e dê sugestões: {summary}")
    
    async def suggest_optimization(self) -> str:
        """Sugere otimizações para o bot"""
        
        perf = await get_performance()
        
        prompt = f"""O bot teve:
- Win rate: {perf['win_rate']}%
- Sharpe ratio: {perf['sharpe']}
- Max drawdown: {perf['max_drawdown']}%

Sugira 3 otimizações específicas para melhorar."""
        
        return await self.ask(prompt)
    
    async def debug_signal(self, symbol: str, timeframe: str) -> str:
        """Debuga por que um sinal não foi gerado"""
        
        from bot.services.signals import get_signal_debug_info
        
        debug_info = await get_signal_debug_info(symbol, timeframe)
        
        prompt = f"""Debug de sinal para {symbol} {timeframe}:

{debug_info}

Por que o sinal não foi gerado? Qual é o problema?"""
        
        return await self.ask(prompt)
    
    async def ask(self, question: str) -> str:
        """Faz pergunta ao agente com contexto de trading"""
        
        system = """Você é um especialista em trading e desenvolvimento de bots.
Analise dados de trading e sugira melhorias específicas.
Seja direto e focado em resultados."""
        
        self.conversation.append({"role": "user", "content": question})
        
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1500,
            system=system,
            messages=self.conversation
        )
        
        answer = response.content[0].text
        self.conversation.append({"role": "assistant", "content": answer})
        
        return answer
    
    @staticmethod
    def _format_trades(trades) -> str:
        """Formata trades para exibição"""
        lines = []
        for trade in trades:
            lines.append(f"- {trade['symbol']} @ ${trade['price']} ({trade['pnl']:+.2f}%)")
        return "\n".join(lines)
```

**Passo 2: Integrar com seu CLI/Dashboard**

```python
# Em seu main bot ou CLI
from bot.agents.trading_agent import TradingAgent

async def bot_status(bot_instance):
    """Mostra status com análise de agente"""
    agent = TradingAgent(bot_instance)
    
    analysis = await agent.analyze_performance(hours=24)
    suggestions = await agent.suggest_optimization()
    
    print(f"""
╔════════════════════════════════════════╗
║   Trading Bot Status & Analysis        ║
╚════════════════════════════════════════╝

📊 ANÁLISE:
{analysis}

🎯 SUGESTÕES:
{suggestions}
""")

# Use em seu admin CLI
if __name__ == "__main__":
    import asyncio
    from bot.core import TradingBot
    
    bot = TradingBot()
    asyncio.run(bot_status(bot))
```

**Passo 3: Webhook para alertas**

```python
# bot/webhooks/agent_alerts.py
from fastapi import APIRouter, BackgroundTasks
from bot.agents.trading_agent import TradingAgent

router = APIRouter(prefix="/webhooks", tags=["agent"])

@router.post("/analyze-if-poor-performance")
async def check_performance(background_tasks: BackgroundTasks):
    """Verifica performance e alerta se ruim"""
    
    agent = TradingAgent(bot)
    analysis = await agent.analyze_performance(hours=1)
    
    # Se performance ruim, notifica
    if "problema" in analysis.lower() or "atenção" in analysis.lower():
        background_tasks.add_task(send_alert, analysis)
    
    return {"status": "ok"}

async def send_alert(message: str):
    """Envia alerta por email/Discord/Telegram"""
    # Implementar notificação
    pass
```

---

## 3️⃣ Comunicação Entre Agentes

### Padrão: Agent Bridge

```python
# agent_bridge.py
"""Bridge entre STOA Agent e Trading Bot Agent"""

class AgentBridge:
    
    def __init__(self, stoa_agent, trading_agent):
        self.stoa = stoa_agent
        self.trading = trading_agent
    
    async def cross_analyze(self):
        """Analisa relação entre projeto STOA e bot"""
        
        stoa_status = await self.stoa.get_project_context()
        trading_status = await self.trading.analyze_performance()
        
        prompt = f"""
Projeto STOA:
{stoa_status}

Bot de Trading:
{trading_status}

Existe alguma relação? O development do STOA afeta o bot?
Como melhorar ambos em paralelo?"""
        
        return await self.stoa.process_command(prompt)
    
    async def suggest_priorities(self):
        """Sugere prioridades globais"""
        
        stoa_needs = await self.stoa.suggest_improvements()
        bot_needs = await self.trading.suggest_optimization()
        
        prompt = f"""
STOA precisa: {stoa_needs}
Bot precisa: {bot_needs}

Qual deve ser a prioridade? Como distribuo meu tempo?"""
        
        return await self.stoa.process_command(prompt)

# Uso
bridge = AgentBridge(stoa_agent, trading_agent)
priorities = await bridge.suggest_priorities()
```

---

## 🚀 Exemplo Completo: Workflow Diário

```python
# daily_workflow.py
"""Workflow diário com agentes"""

async def daily_standup(stoa_agent, trading_agent):
    """Standup diário automático"""
    
    print("═" * 50)
    print("📊 DAILY STANDUP")
    print("═" * 50)
    
    # 1. Status do bot
    print("\n🤖 Bot Status:")
    bot_analysis = await trading_agent.analyze_performance(hours=24)
    print(bot_analysis)
    
    # 2. Status do STOA
    print("\n🏗️ STOA Status:")
    stoa_status = await stoa_agent.suggest_improvements()
    print(stoa_status)
    
    # 3. Agenda
    print("\n📅 Agenda Recomendada:")
    schedule = await stoa_agent.process_command(
        "Monte agenda para hoje balanceando STOA e bot baseado no status"
    )
    print(schedule)
    
    print("\n═" * 50)

# Executar diariamente com APScheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

scheduler.add_job(
    daily_standup,
    'cron',
    hour=9, minute=0,  # 9:00 AM
    args=[stoa_agent, trading_agent]
)

scheduler.start()
```

---

## 📝 Checklist de Integração

- [ ] Criar módulo de agente no STOA
- [ ] Adicionar endpoints no STOA API
- [ ] Integrar no frontend STOA
- [ ] Criar agente no bot de trading
- [ ] Adicionar comandos de análise
- [ ] Configurar webhooks
- [ ] Testar comunicação entre agentes
- [ ] Setups de notificações (email/Discord)
- [ ] Documentar novos endpoints

---

**Próximo: Faça seu próprio agente especializado! 🚀**
