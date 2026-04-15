"""
STOA Agent - Backend Principal
Sistema multimodal com reconhecimento de voz, múltiplos agentes e integração com APIs
"""

import os
import json
import asyncio
import re
import socket
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, WebSocket, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI
import uvicorn
from executive_orchestrator import ExecutiveOrchestrator, ResponseConsolidator
try:
    from stoa_memory import StoaMemory
except Exception:
    StoaMemory = None
try:
    from stoa_guardrail import StoaGuardrail
except Exception:
    StoaGuardrail = None
from device_command_router import DeviceCommandRouter
from device_control_core import DeviceControlCore
from device_state_store import DeviceStateStore
from device_control_models import ActionRequest, ActionResult, DeviceHeartbeat, DeviceRegistration
from state_store import StateStore
from planner_symbol import Planner, Executor

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_local_env() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


load_local_env()


def can_bind(host: str, port: int) -> tuple[bool, Optional[Exception]]:
    bind_host = "0.0.0.0" if host in {"0.0.0.0", ""} else host
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind_host, port))
        return True, None
    except OSError as exc:
        return False, exc
    finally:
        sock.close()


def resolve_runtime_port(host: str, preferred_port: int) -> int:
    ok, error = can_bind(host, preferred_port)
    if ok:
        return preferred_port

    logger.warning(
        f"⚠️ Porta {preferred_port} indisponível para {host}: {error}. Tentando fallback para 8001."
    )

    fallback_port = 8001
    ok, fallback_error = can_bind(host, fallback_port)
    if ok:
        logger.warning(f"⚠️ Usando porta alternativa {fallback_port}.")
        return fallback_port

    raise RuntimeError(
        "Não foi possível iniciar o STOA porque as portas 8000 e 8001 estão indisponíveis. "
        "Use 'netstat -ano | findstr :8000', 'tasklist /FI \"PID eq <PID>\"' e "
        "'taskkill /PID <PID> /F', ou defina PORT no .env."
    ) from fallback_error

# ==================== CONFIGURAÇÃO ====================
class Config:
    """Configuração centralizada"""
    API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8000))
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    RELOAD = os.getenv("RELOAD", "False").lower() == "true"
    STATE_DB = os.getenv("STOA_STATE_DB", str(Path(__file__).with_name(".stoa_state.db")))
    LOCATION = os.getenv("LOCATION", "Chapada dos Guimarães, Mato Grosso, BR")
    LAT = float(os.getenv("LAT", "-15.4667"))
    LON = float(os.getenv("LON", "-55.7500"))

config = Config()

if not config.API_KEY or "YOUR_KEY_HERE" in config.API_KEY:
    raise ValueError("OPENAI_API_KEY não configurada!")

# ==================== MODELOS ====================
class VoiceCommand(BaseModel):
    """Comando de voz transcrito"""
    text: str
    language: str = "pt-BR"
    timestamp: datetime = None


class DeviceActionConfirmation(BaseModel):
    reason: Optional[str] = None


class AgentResponse(BaseModel):
    """Resposta do agente"""
    response: str
    action_type: str  # "code", "web", "planning", "info", etc
    module: str       # qual módulo processou
    data: Optional[dict] = None


class STOAMode(Enum):
    CONVERSATION = "conversation"
    PLANNER = "planner"
    PREVIEW = "preview"
    DEV = "dev"
    OPS = "ops"
    STOA = "stoa"


class OpenAIAdapter:
    """Wrapper para a OpenAI Chat Completions API"""

    client = OpenAI(api_key=config.API_KEY)

    @staticmethod
    def generate_text(prompt: str, system: Optional[str] = None, max_output_tokens: int = 1000) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = OpenAIAdapter.client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=messages,
            max_tokens=max_output_tokens,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def generate_from_messages(messages: list[dict], system: Optional[str] = None, max_output_tokens: int = 1000) -> str:
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        response = OpenAIAdapter.client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=full_messages,
            max_tokens=max_output_tokens,
        )
        return response.choices[0].message.content or ""

# ==================== AGENTES ESPECIALIZADOS ====================
class WeatherAgent:
    """Agente de clima e informações meteorológicas"""

    @staticmethod
    async def get_info(lat: float, lon: float) -> dict:
        """Obtém informações de clima"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&lang=pt_br&units=metric&appid={config.OPENWEATHER_API_KEY}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "temperature": data["main"]["temp"],
                            "humidity": data["main"]["humidity"],
                            "description": data["weather"][0]["description"],
                            "wind_speed": data["wind"]["speed"],
                            "pressure": data["main"]["pressure"],
                            "location": data["name"],
                            "timestamp": datetime.now().isoformat()
                        }
        except Exception as e:
            logger.error(f"Erro ao obter clima: {e}")

        return {
            "error": "Impossível obter dados de clima",
            "fallback": True,
            "temperature": 26,
            "humidity": 65,
            "description": "Parcialmente nublado",
            "location": config.LOCATION
        }


class CodeAgent:
    """Agente gerador de código"""

    @staticmethod
    async def generate(prompt: str, language: str = "python") -> dict:
        """Gera código usando OpenAI API"""
        system = f"""Você é um especialista em programação ({language}). 
        Gere código limpo, bem estruturado e com comentários.
        Sempre retorne APENAS o código entre triples backticks.
        Inclua exemplos de uso."""

        code = OpenAIAdapter.generate_text(
            prompt,
            system=system,
            max_output_tokens=2000,
        )

        return {
            "code": code,
            "language": language,
            "generated_at": datetime.now().isoformat()
        }


class PlanningAgent:
    """Agente de planejamento e agenda"""

    @staticmethod
    async def create_schedule(requirements: str) -> dict:
        """Cria um plano detalhado do dia"""
        system = """Você é um expert em produtividade e planejamento.
        Crie um schedule detalhado com blocos de tempo específicos.
        Inclua pausas, prioridades e recomendações.
        Formato: lista com horários, atividades e duração."""

        schedule = OpenAIAdapter.generate_text(
            requirements,
            system=system,
            max_output_tokens=1500,
        )

        return {
            "schedule": schedule,
            "created_at": datetime.now().isoformat()
        }


class WebAgent:
    """Agente gerador de websites"""

    @staticmethod
    async def create_website(requirements: str) -> dict:
        """Gera website HTML/CSS/JS completo"""
        system = """Você é um web designer e desenvolvedor frontend.
        Gere um website completo, moderno e responsivo em uma única página HTML.
        Inclua:
        - HTML5 semântico
        - CSS com design responsivo
        - JavaScript interativo
        - Paleta de cores moderna
        - Boas práticas de UX/UI
        Retorne APENAS o código HTML completo com <style> e <script> internos."""

        html = OpenAIAdapter.generate_text(
            requirements,
            system=system,
            max_output_tokens=3000,
        )

        return {
            "html": html,
            "created_at": datetime.now().isoformat()
        }


class EducationAgent:
    """Agente educacional e de explicações técnicas"""

    @staticmethod
    async def explain(topic: str) -> dict:
        """Explica conceitos técnicos de forma clara"""
        system = """Você é um professor de tecnologia experiente.
        Explique o conceito de forma clara, com exemplos práticos.
        Inclua: definição, caso de uso, exemplo de código, e recursos para aprender mais."""

        explanation = OpenAIAdapter.generate_text(
            f"Explique: {topic}",
            system=system,
            max_output_tokens=2000,
        )

        return {
            "explanation": explanation,
            "topic": topic,
            "created_at": datetime.now().isoformat()
        }


class StrategyAgent:
    """Agente de análise estratégica e planejamento de projetos"""

    @staticmethod
    async def analyze(context: str) -> dict:
        """Analisa estratégia e cria plano de ação"""
        system = """Você é um estrategista e consultor técnico.
        Analise o contexto e crie um plano de ação estruturado.
        Inclua: análise SWOT, roadmap, milestones, e riscos."""

        strategy = OpenAIAdapter.generate_text(
            context,
            system=system,
            max_output_tokens=2000,
        )

        return {
            "strategy": strategy,
            "created_at": datetime.now().isoformat()
        }

# ==================== ORQUESTRADOR CENTRAL ====================
class STOAQuantumBrain:
    """Cérebro quântico central - orquestra múltiplos agentes"""

    PREVIEW_TTL_MINUTES = 15
    WORKING_CONTEXT_TTL_MINUTES = 30

    def __init__(self):
        self.conversation_history = []
        self.max_history = 20
        self.orchestrator = ExecutiveOrchestrator()
        runtime_state_db = os.getenv("STOA_STATE_DB", config.STATE_DB)
        self.state_store = StateStore(runtime_state_db)
        self.device_state_store = DeviceStateStore(runtime_state_db)
        self.device_control = DeviceControlCore(state_store=self.device_state_store)
        self.pending_preview = None
        self.working_context = {
            'current_goal': None,
            'current_mode': None,
            'current_project_root': None,
            'last_files': [],
            'last_plan': None,
            'last_change_set': None,
            'last_operation_id': None,
            'last_preview_id': None,
            'last_preview_summary': None,
            'current_plan_goal': None,
            'current_plan_steps': [],
            'current_step_index': 0,
            'last_touched_at': None,
        }
        self.active_goal = None
        self.operational_state = {
            'current_mode': None,
            'current_phase': 'idle',
            'last_intent': None,
            'last_risk_level': None,
            'last_risk_flags': [],
            'last_confirmation_action': None,
            'last_decision_id': None,
            'last_command': None,
            'last_transition': None,
            'active_goal_id': None,
            'active_goal_status': None,
            'pending_preview_id': None,
            'pending_preview_valid': False,
            'preview_validity_status': 'missing',
            'current_step_id': None,
            'current_step_status': None,
            'current_operation_id': None,
            'next_unlock_action': None,
            'blockers': [],
            'last_updated_at': None,
        }
        self._rehydrate_state()

    def _rehydrate_state(self) -> None:
        stored_preview = self.state_store.load_pending_preview()
        if stored_preview:
            self.pending_preview = stored_preview
            if self._get_pending_preview_status().get('expired'):
                self.pending_preview = None
                self.state_store.clear_pending_preview()

        stored_goal = self.state_store.load_active_goal()
        if isinstance(stored_goal, dict):
            self.active_goal = stored_goal

        stored_context = self.state_store.load_working_context()
        if isinstance(stored_context, dict):
            merged = dict(self.working_context)
            merged.update(stored_context)
            self.working_context = merged

        stored_operational_state = self.state_store.load_operational_state()
        if isinstance(stored_operational_state, dict):
            merged_state = dict(self.operational_state)
            merged_state.update(stored_operational_state)
            self.operational_state = merged_state

    def _persist_pending_preview(self) -> None:
        if self.pending_preview:
            self.state_store.save_pending_preview(self.pending_preview)
        else:
            self.state_store.clear_pending_preview()

    def _persist_active_goal(self) -> None:
        if self.active_goal:
            self.state_store.save_active_goal(self.active_goal)
        else:
            self.state_store.clear_active_goal()

    def _persist_working_context(self) -> None:
        self.state_store.save_working_context(self.working_context)

    def _persist_operational_state(self) -> None:
        self.state_store.save_operational_state(self.operational_state)

    @staticmethod
    def _generate_preview_id() -> str:
        return f"preview-{uuid4().hex[:8]}"

    @staticmethod
    def _generate_operation_id() -> str:
        return f"op_{uuid4().hex[:10]}"

    @staticmethod
    def _generate_goal_id() -> str:
        return f"goal_{uuid4().hex[:10]}"

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    def _now_iso(self) -> str:
        return self._now().isoformat()

    def _preview_ttl_minutes(self) -> int:
        return self.PREVIEW_TTL_MINUTES

    def _create_pending_preview(self, change_set: dict, preview_result: dict) -> tuple[dict, Optional[dict]]:
        previous = self.pending_preview
        created_at_dt = self._now()
        expires_at_dt = created_at_dt + timedelta(minutes=self._preview_ttl_minutes())
        plan_steps = change_set.get('plan_steps') or []
        pending = {
            'id': self._generate_preview_id(),
            'operation_id': self._generate_operation_id(),
            'change_set': json.loads(json.dumps(change_set)),
            'goal': change_set.get('goal'),
            'plan_step_ids': [step.get('id') for step in plan_steps if isinstance(step, dict) and step.get('id')],
            'summary': preview_result.get('summary'),
            'created_at': created_at_dt.isoformat(),
            'expires_at': expires_at_dt.isoformat(),
            'files_to_change': list(preview_result.get('files_to_change') or []),
            'step_count': len(preview_result.get('steps') or []),
        }
        self.pending_preview = pending
        self._persist_pending_preview()
        return pending, previous

    def _clear_pending_preview(self) -> Optional[dict]:
        previous = self.pending_preview
        self.pending_preview = None
        self._persist_pending_preview()
        return previous

    def _get_pending_preview_status(self) -> dict:
        preview = self.pending_preview
        if not preview:
            return {'exists': False, 'valid': False, 'expired': False, 'preview': None}

        expires_at_raw = preview.get('expires_at')
        try:
            expires_at = datetime.fromisoformat(expires_at_raw) if expires_at_raw else None
        except Exception:
            expires_at = None

        if not expires_at:
            return {'exists': True, 'valid': False, 'expired': True, 'preview': preview}

        expired = self._now() >= expires_at
        return {
            'exists': True,
            'valid': not expired,
            'expired': expired,
            'preview': preview,
        }

    def _has_valid_pending_preview(self) -> bool:
        return self._get_pending_preview_status().get('valid', False)

    def _get_working_context(self) -> dict:
        return dict(self.working_context or {})

    def _get_active_goal(self) -> Optional[dict]:
        return dict(self.active_goal) if isinstance(self.active_goal, dict) else None

    def _clear_active_goal(self) -> Optional[dict]:
        previous = self._get_active_goal()
        self.active_goal = None
        self._persist_active_goal()
        return previous

    def _active_goal_matches(self, title: Optional[str]) -> bool:
        active_goal = self._get_active_goal()
        if not active_goal or not title:
            return False
        current = re.sub(r'\s+', ' ', (active_goal.get('title') or '').strip().lower())
        incoming = re.sub(r'\s+', ' ', (title or '').strip().lower())
        return bool(current and incoming and current == incoming)

    def _create_active_goal(
        self,
        *,
        title: str,
        description: Optional[str] = None,
        plan_steps: Optional[list[dict]] = None,
        current_step_index: int = 0,
        operation_id: Optional[str] = None,
        status: str = 'active',
    ) -> dict:
        now = self._now_iso()
        active_goal = {
            'goal_id': self._generate_goal_id(),
            'title': title,
            'description': description or title,
            'status': status,
            'created_at': now,
            'last_updated_at': now,
            'linked_operation_ids': [operation_id] if operation_id else [],
            'plan_steps': [dict(step) for step in (plan_steps or []) if isinstance(step, dict)],
            'current_step_index': current_step_index,
        }
        self.active_goal = active_goal
        self._persist_active_goal()
        return dict(active_goal)

    def _update_active_goal(self, **kwargs) -> Optional[dict]:
        active_goal = self._get_active_goal()
        if not active_goal:
            return None
        for key, value in kwargs.items():
            if value is not None:
                active_goal[key] = value
        if active_goal.get('linked_operation_ids'):
            active_goal['linked_operation_ids'] = list(dict.fromkeys(active_goal['linked_operation_ids']))
        active_goal['last_updated_at'] = self._now_iso()
        self.active_goal = active_goal
        self._persist_active_goal()
        return dict(active_goal)

    def _set_active_goal_status(self, status: str) -> Optional[dict]:
        return self._update_active_goal(status=status)

    def _ensure_active_goal(
        self,
        *,
        goal: Optional[str],
        plan_steps: Optional[list[dict]] = None,
        current_step_index: int = 0,
        operation_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[dict]:
        if not goal:
            return self._get_active_goal()
        active_goal = self._get_active_goal()
        if not active_goal or not self._active_goal_matches(goal):
            return self._create_active_goal(
                title=goal,
                description=goal,
                plan_steps=plan_steps or [],
                current_step_index=current_step_index,
                operation_id=operation_id,
                status=status or 'active',
            )
        linked_operation_ids = list(active_goal.get('linked_operation_ids') or [])
        if operation_id:
            linked_operation_ids.append(operation_id)
        return self._update_active_goal(
            title=goal,
            description=goal,
            plan_steps=[dict(step) for step in (plan_steps or active_goal.get('plan_steps') or [])],
            current_step_index=current_step_index,
            linked_operation_ids=linked_operation_ids,
            status=status or active_goal.get('status') or 'active',
        )

    def _sync_active_goal_from_working_context(self, *, operation_id: Optional[str] = None, status: Optional[str] = None) -> Optional[dict]:
        context = self._get_working_context()
        goal = context.get('current_plan_goal') or context.get('current_goal')
        plan_steps = context.get('current_plan_steps') or []
        current_step_index = context.get('current_step_index', 0)
        return self._ensure_active_goal(
            goal=goal,
            plan_steps=plan_steps,
            current_step_index=current_step_index,
            operation_id=operation_id or context.get('last_operation_id'),
            status=status,
        )

    def _format_active_goal_summary(self) -> str:
        active_goal = self._get_active_goal()
        if not active_goal:
            return 'Nenhum objetivo ativo no momento.'
        plan_steps = active_goal.get('plan_steps') or []
        done_count = len([step for step in plan_steps if step.get('status') == 'done'])
        failed_count = len([step for step in plan_steps if step.get('status') == 'failed'])
        pending_count = len([step for step in plan_steps if step.get('status') not in {'done'}])
        next_step = next((step for step in plan_steps if step.get('status') in {'pending', 'in_progress', 'failed'}), None)
        return (
            f"Objetivo: {active_goal.get('title') or '-'} | "
            f"Status: {active_goal.get('status') or '-'} | "
            f"Etapas: {len(plan_steps)} | "
            f"Concluídas: {done_count} | "
            f"Pendentes/Falhas: {pending_count} | "
            f"Falhas: {failed_count} | "
            f"Próxima etapa: {(next_step or {}).get('title') or '-'}"
        )

    def _can_complete_active_goal(self) -> bool:
        active_goal = self._get_active_goal()
        if not active_goal:
            return False
        if active_goal.get('status') in {'paused', 'failed'}:
            return False
        plan_steps = active_goal.get('plan_steps') or []
        if not plan_steps:
            return False
        return all(step.get('status') == 'done' for step in plan_steps)

    def _get_goal_blockers(self) -> list[str]:
        blockers = []
        pending_preview = self._get_pending_preview_status()
        preview = pending_preview.get('preview')
        if pending_preview.get('valid') and preview:
            blockers.append(f"Há um preview pendente ({preview.get('id', '-')}) aguardando apply ou cancelamento.")

        active_goal = self._get_active_goal()
        if not active_goal:
            blockers.append('Não há objetivo ativo claro no momento.')
            return blockers

        if active_goal.get('status') == 'paused':
            blockers.append('O objetivo ativo está pausado.')
        elif active_goal.get('status') == 'failed':
            blockers.append('O objetivo ativo está marcado como failed.')

        for step in active_goal.get('plan_steps') or []:
            if step.get('status') == 'failed':
                blockers.append(f"Etapa falhou: {step.get('title') or step.get('id')}.")
                break
        return blockers

    def _get_next_action(self) -> dict:
        pending_preview = self._get_pending_preview_status()
        preview = pending_preview.get('preview')
        active_goal = self._get_active_goal()
        blockers = self._get_goal_blockers()

        if pending_preview.get('valid') and preview:
            return {
                'type': 'preview_pending',
                'message': (
                    f"Há um preview pendente ({preview.get('id', '-')}). "
                    "O próximo passo real é aplicar com 'aplique isso' ou cancelar com 'cancelar preview'."
                ),
                'active_goal_status': (active_goal or {}).get('status'),
                'next_step': None,
                'blockers': blockers,
                'can_complete_goal': self._can_complete_active_goal(),
                'preview_pending': True,
                'preview_id': preview.get('id'),
            }

        if not active_goal:
            return {
                'type': 'no_active_goal',
                'message': 'Não há objetivo ativo. O próximo passo é definir ou retomar uma linha de trabalho.',
                'active_goal_status': None,
                'next_step': None,
                'blockers': blockers,
                'can_complete_goal': False,
                'preview_pending': False,
                'preview_id': None,
            }

        if active_goal.get('status') == 'completed':
            return {
                'type': 'goal_ready_to_complete',
                'message': 'O objetivo atual já está concluído.',
                'active_goal_status': active_goal.get('status'),
                'next_step': None,
                'blockers': blockers,
                'can_complete_goal': True,
                'preview_pending': False,
                'preview_id': None,
            }

        if active_goal.get('status') == 'paused':
            return {
                'type': 'goal_paused',
                'message': 'O objetivo atual está pausado. O próximo passo é retomar com "retoma isso".',
                'active_goal_status': active_goal.get('status'),
                'next_step': None,
                'blockers': blockers,
                'can_complete_goal': False,
                'preview_pending': False,
                'preview_id': None,
            }

        plan_steps = active_goal.get('plan_steps') or []
        failed_step = next((step for step in plan_steps if step.get('status') == 'failed'), None)
        if failed_step:
            return {
                'type': 'step_failed',
                'message': f"A etapa bloqueada é '{failed_step.get('title')}'. Revise ou refaça essa etapa antes de avançar.",
                'active_goal_status': active_goal.get('status'),
                'next_step': failed_step,
                'blockers': blockers,
                'can_complete_goal': False,
                'preview_pending': False,
                'preview_id': None,
            }

        in_progress_step = next((step for step in plan_steps if step.get('status') == 'in_progress'), None)
        if in_progress_step:
            return {
                'type': 'step_in_progress',
                'message': f"A etapa em andamento é '{in_progress_step.get('title')}'. O próximo passo é concluir ou revisar essa etapa.",
                'active_goal_status': active_goal.get('status'),
                'next_step': in_progress_step,
                'blockers': blockers,
                'can_complete_goal': False,
                'preview_pending': False,
                'preview_id': None,
            }

        pending_step = next((step for step in plan_steps if step.get('status') == 'pending'), None)
        if pending_step:
            return {
                'type': 'next_step',
                'message': f"O próximo passo real é '{pending_step.get('title')}'. {pending_step.get('description')}",
                'active_goal_status': active_goal.get('status'),
                'next_step': pending_step,
                'blockers': blockers,
                'can_complete_goal': False,
                'preview_pending': False,
                'preview_id': None,
            }

        if self._can_complete_active_goal():
            return {
                'type': 'goal_ready_to_complete',
                'message': 'Todas as etapas estão concluídas. Você já pode concluir o objetivo atual.',
                'active_goal_status': active_goal.get('status'),
                'next_step': None,
                'blockers': blockers,
                'can_complete_goal': True,
                'preview_pending': False,
                'preview_id': None,
            }

        return {
            'type': 'no_active_goal',
            'message': 'Não foi possível determinar a próxima ação com segurança.',
            'active_goal_status': active_goal.get('status'),
            'next_step': None,
            'blockers': blockers,
            'can_complete_goal': False,
            'preview_pending': False,
            'preview_id': None,
        }

    def _format_goal_guidance(self) -> str:
        guidance = self._get_next_action()
        lines = [guidance.get('message') or 'Sem guidance disponível.']
        blockers = guidance.get('blockers') or []
        if blockers:
            lines.append('')
            lines.append('Bloqueios/observações:')
            for blocker in blockers:
                lines.append(f"- {blocker}")
        next_step = guidance.get('next_step')
        if next_step:
            lines.append('')
            lines.append(f"Próxima etapa: {next_step.get('title')}")
            if next_step.get('description'):
                lines.append(next_step.get('description'))
        return "\n".join(lines)

    def _clear_working_context(self) -> dict:
        previous = self._get_working_context()
        self.working_context = {
            'current_goal': None,
            'current_mode': None,
            'current_project_root': None,
            'last_files': [],
            'last_plan': None,
            'last_change_set': None,
            'last_operation_id': None,
            'last_preview_id': None,
            'last_preview_summary': None,
            'current_plan_goal': None,
            'current_plan_steps': [],
            'current_step_index': 0,
            'last_touched_at': None,
        }
        return previous

    def _working_context_is_fresh(self, minutes: Optional[int] = None) -> bool:
        ttl = minutes if minutes is not None else self.WORKING_CONTEXT_TTL_MINUTES
        last_touched_at = (self.working_context or {}).get('last_touched_at')
        if not last_touched_at:
            return False
        try:
            last_dt = datetime.fromisoformat(last_touched_at)
        except Exception:
            return False
        return self._now() - last_dt <= timedelta(minutes=ttl)

    def _format_working_context_summary(self) -> str:
        context = self._get_working_context()
        if not context.get('last_touched_at'):
            return 'Nenhum contexto operacional ativo.'
        files = context.get('last_files') or []
        pending_steps = len([step for step in (context.get('current_plan_steps') or []) if step.get('status') != 'done'])
        next_step = self._get_next_plan_step()
        return (
            f"Objetivo atual: {context.get('current_goal') or '-'} | "
            f"Modo atual: {context.get('current_mode') or '-'} | "
            f"Arquivos recentes: {', '.join(files) if files else '-'} | "
            f"Etapas pendentes: {pending_steps} | "
            f"Próxima etapa: {(next_step or {}).get('title') or '-'} | "
            f"Última operation_id: {context.get('last_operation_id') or '-'} | "
            f"Último preview_id: {context.get('last_preview_id') or '-'} | "
            f"Atualizado em: {context.get('last_touched_at') or '-'}"
        )

    def _update_working_context(self, **kwargs) -> dict:
        context = self._get_working_context()
        for key, value in kwargs.items():
            if value is not None:
                context[key] = value
        context['last_touched_at'] = self._now_iso()
        if context.get('last_files'):
            context['last_files'] = list(dict.fromkeys(context['last_files']))
        self.working_context = context
        self._persist_working_context()
        return context

    def _get_current_plan_steps(self) -> list[dict]:
        return [dict(step) for step in (self.working_context or {}).get('current_plan_steps') or [] if isinstance(step, dict)]

    def _get_pending_plan_steps(self) -> list[dict]:
        return [step for step in self._get_current_plan_steps() if step.get('status') != 'done']

    def _get_next_plan_step(self) -> Optional[dict]:
        pending = self._get_pending_plan_steps()
        return dict(pending[0]) if pending else None

    def _mark_current_step_done(self) -> Optional[dict]:
        context = self._get_working_context()
        plan_steps = self._get_current_plan_steps()
        for idx, step in enumerate(plan_steps):
            if step.get('status') != 'done':
                step['status'] = 'done'
                context['current_plan_steps'] = plan_steps
                context['current_step_index'] = min(idx + 1, len(plan_steps))
                context['last_touched_at'] = self._now_iso()
                self.working_context = context
                return dict(step)
        return None

    def _match_plan_steps_to_execution(self, execution_steps: list[dict], plan_steps: Optional[list[dict]] = None) -> list[int]:
        current_plan_steps = [dict(step) for step in (plan_steps or self._get_current_plan_steps())]
        matched_indexes = []
        for exec_step in execution_steps or []:
            exec_type = exec_step.get('type')
            exec_path = exec_step.get('path')
            for idx, plan_step in enumerate(current_plan_steps):
                linked_types = plan_step.get('linked_step_types') or []
                linked_files = plan_step.get('linked_files') or []
                if exec_type and linked_types and exec_type not in linked_types:
                    continue
                if exec_path and linked_files and exec_path not in linked_files:
                    continue
                matched_indexes.append(idx)
                break
        return list(dict.fromkeys(matched_indexes))

    def _mark_matching_steps_in_progress(self, execution_steps: list[dict], operation_id: Optional[str] = None) -> list[dict]:
        context = self._get_working_context()
        plan_steps = self._get_current_plan_steps()
        for idx in self._match_plan_steps_to_execution(execution_steps, plan_steps):
            if plan_steps[idx].get('status') != 'done':
                plan_steps[idx]['status'] = 'in_progress'
                if operation_id:
                    plan_steps[idx]['linked_operation_id'] = operation_id
        context['current_plan_steps'] = plan_steps
        self.working_context = context
        return plan_steps

    def _mark_matching_steps_done(self, execution_steps: list[dict], operation_id: Optional[str] = None) -> list[dict]:
        context = self._get_working_context()
        plan_steps = self._get_current_plan_steps()
        matched = self._match_plan_steps_to_execution(execution_steps, plan_steps)
        for idx in matched:
            plan_steps[idx]['status'] = 'done'
            if operation_id:
                plan_steps[idx]['linked_operation_id'] = operation_id
        pending = [step for step in plan_steps if step.get('status') != 'done']
        context['current_plan_steps'] = plan_steps
        context['current_step_index'] = len(plan_steps) - len(pending)
        self.working_context = context
        return plan_steps

    def _mark_matching_steps_failed(self, execution_steps: list[dict], operation_id: Optional[str] = None) -> list[dict]:
        context = self._get_working_context()
        plan_steps = self._get_current_plan_steps()
        for idx in self._match_plan_steps_to_execution(execution_steps, plan_steps):
            plan_steps[idx]['status'] = 'failed'
            if operation_id:
                plan_steps[idx]['linked_operation_id'] = operation_id
        context['current_plan_steps'] = plan_steps
        self.working_context = context
        return plan_steps

    def _handle_plan_progress_after_execution(self, execution_result: dict, operation_id: Optional[str] = None) -> dict:
        plan_steps_before = self._get_current_plan_steps()
        if not plan_steps_before:
            self._sync_active_goal_from_working_context(operation_id=operation_id)
            return {
                'updated_plan_steps': [],
                'current_step_index': self._get_working_context().get('current_step_index', 0),
                'next_step': None,
                'plan_progress_summary': self._format_plan_progress(),
            }

        applied_steps = execution_result.get('applied_steps') or []
        failed_step = execution_result.get('failed_step')
        rollback = execution_result.get('rollback') or {}

        self._mark_matching_steps_in_progress(applied_steps + ([failed_step] if failed_step else []), operation_id=operation_id)

        if execution_result.get('success'):
            updated = self._mark_matching_steps_done(applied_steps, operation_id=operation_id)
        else:
            if rollback.get('attempted'):
                updated = self._mark_matching_steps_failed(applied_steps + ([failed_step] if failed_step else []), operation_id=operation_id)
            else:
                updated = self._mark_matching_steps_failed(([failed_step] if failed_step else []), operation_id=operation_id)

        goal_status = 'failed' if not execution_result.get('success') else None
        self._sync_active_goal_from_working_context(operation_id=operation_id, status=goal_status)

        return {
            'updated_plan_steps': updated,
            'current_step_index': self._get_working_context().get('current_step_index', 0),
            'next_step': self._get_next_plan_step(),
            'plan_progress_summary': self._format_plan_progress(),
        }

    def _format_plan_progress(self) -> str:
        context = self._get_working_context()
        plan_steps = self._get_current_plan_steps()
        if not plan_steps:
            return 'Nenhum plano ativo com etapas explícitas.'
        pending = [step for step in plan_steps if step.get('status') != 'done']
        next_step = pending[0] if pending else None
        return (
            f"Plano atual: {context.get('current_plan_goal') or context.get('current_goal') or '-'} | "
            f"Etapas: {len(plan_steps)} | "
            f"Pendentes: {len(pending)} | "
            f"Próxima etapa: {(next_step or {}).get('title') or '-'}"
        )

    def _format_device_control_summary(self) -> str:
        devices = self.device_control.list_devices()
        if not devices:
            return 'Nenhum dispositivo registrado no STOA Device Control.'
        lines = [f"Dispositivos registrados: {len(devices)}"]
        for device in devices:
            capability_names = ", ".join(cap.get('action_type', '-') for cap in device.get('capabilities', [])[:4]) or '-'
            lines.append(
                f"- {device.get('device_name', device.get('device_id'))} "
                f"[{device.get('device_id')}] · {device.get('platform', '-')} · "
                f"status={device.get('status', '-')} · fila={device.get('queue_depth', 0)} · "
                f"caps={capability_names}"
            )
        return "\n".join(lines)

    def _get_pending_device_confirmations(
        self,
        *,
        session_id: str = 'default',
    ) -> list[dict]:
        pending = self.device_control.get_pending_actions_for_session(session_id=session_id)
        allowed_requesters = {'stoa_chat', 'stoa_pwa', 'stoa_core'}
        filtered = []
        for action in pending:
            requested_by = action.get('requested_by') or ((action.get('parameters') or {}).get('requested_by'))
            if requested_by in allowed_requesters:
                filtered.append(action)
        return filtered

    @staticmethod
    def _summarize_pending_device_actions(actions: list[dict]) -> list[dict]:
        summarized: list[dict] = []
        for index, action in enumerate(actions):
            summarized.append(
                {
                    'action_id': action.get('action_id'),
                    'action_type': action.get('action_type'),
                    'summary': action.get('summary'),
                    'created_at': action.get('created_at'),
                    'is_latest': index == 0,
                }
            )
        return summarized

    @staticmethod
    def is_confirmation_command(command: str) -> bool:
        normalized_command = re.sub(r"[.!?]+$", "", (command or '').lower().strip())
        confirm_shortcut, cancel_shortcut = STOAQuantumBrain._is_device_confirmation_shortcut(normalized_command)
        return confirm_shortcut or cancel_shortcut

    @staticmethod
    def _is_device_confirmation_shortcut(normalized_command: str) -> tuple[bool, bool]:
        confirm_shortcut = normalized_command in {
            'confirmar ação do dispositivo',
            'confirmar acao do dispositivo',
            'confirmar última ação',
            'confirmar ultima acao',
            'confirmar ação',
            'confirmar acao',
            'confirmar última ação do dispositivo',
            'confirmar ultima acao do dispositivo',
            'confirmar última ação sensível do dispositivo',
            'confirmar ultima acao sensivel do dispositivo',
        } or normalized_command.startswith('confirmar ação ') or normalized_command.startswith('confirmar acao ')
        cancel_shortcut = normalized_command in {
            'cancelar última ação',
            'cancelar ultima acao',
            'cancelar ação',
            'cancelar acao',
            'cancelar última ação do dispositivo',
            'cancelar ultima acao do dispositivo',
            'cancelar ação do dispositivo',
            'cancelar acao do dispositivo',
        } or normalized_command.startswith('cancelar ação ') or normalized_command.startswith('cancelar acao ')
        return confirm_shortcut, cancel_shortcut

    @staticmethod
    def _targets_latest_pending_action(normalized_command: str) -> bool:
        return normalized_command in {
            'confirmar última ação',
            'confirmar ultima acao',
            'confirmar última ação do dispositivo',
            'confirmar ultima acao do dispositivo',
            'confirmar última ação sensível do dispositivo',
            'confirmar ultima acao sensivel do dispositivo',
            'cancelar última ação',
            'cancelar ultima acao',
            'cancelar última ação do dispositivo',
            'cancelar ultima acao do dispositivo',
        }

    def handle_confirmation_shortcut(
        self,
        command: str,
        *,
        session_id: str = 'default',
        user_id: str = 'stoa_chat',
    ) -> Optional[AgentResponse]:
        normalized_command = re.sub(r"[.!?]+$", "", (command or '').lower().strip())
        action_id_match = re.search(r"(device-action-[a-z0-9]+)", normalized_command)
        confirm_shortcut, cancel_shortcut = self._is_device_confirmation_shortcut(normalized_command)
        if not (confirm_shortcut or cancel_shortcut):
            return None

        actions = self._get_pending_device_confirmations(session_id=session_id)
        pending_actions = self._summarize_pending_device_actions(actions)
        pending = None
        if action_id_match:
            pending = next((action for action in actions if action.get('action_id') == action_id_match.group(1)), None)
        elif actions and self._targets_latest_pending_action(normalized_command):
            pending = actions[0]
        elif len(actions) == 1:
            pending = actions[0]
        elif len(actions) > 1:
            action_lines = [
                f"- {item.get('action_id')} · {item.get('action_type')} · {item.get('device_id')} · {item.get('target') or '-'}"
                for item in actions[:5]
            ]
            return self._build_response(
                mode=STOAMode.OPS.value,
                status='ops_operation_summary',
                response="Há mais de uma ação sensível pendente. Escolha pelo Action ID:\n" + "\n".join(action_lines),
                action_type='ops',
                module='device_control',
                details={
                    'device_control': True,
                    'pending_device_actions': pending_actions,
                    'devices': self.device_control.list_devices(),
                    'device_control_summary': self._format_device_control_summary(),
                    'blockers': ['Mais de uma ação sensível pendente.'],
                    'next_unlock_action': 'choose_pending_action_id',
                },
            )
        if not pending:
            return self._build_response(
                mode=STOAMode.OPS.value,
                status='ops_not_found',
                response='Não há ação sensível pendente para confirmar ou cancelar.',
                action_type='ops',
                module='device_control',
                details={
                    'device_control': True,
                    'pending_device_actions': pending_actions,
                    'devices': self.device_control.list_devices(),
                    'device_control_summary': self._format_device_control_summary(),
                    'blockers': ['Nenhuma ação sensível pendente nesta sessão.'],
                    'next_unlock_action': 'send_sensitive_device_command',
                },
            )

        if confirm_shortcut:
            action = self.device_control.confirm_action(pending['action_id'], reason='Confirmado pelo chat do STOA')
            response_text = f"Ação confirmada: {action.get('action_type')} em {action.get('device_id')}.\nStatus: {action.get('status')}."
            next_unlock_action = 'await_device_result'
        else:
            action = self.device_control.cancel_action(pending['action_id'], reason='Cancelado pelo chat do STOA')
            response_text = f"Ação cancelada: {action.get('action_type')} em {action.get('device_id')}.\nStatus: {action.get('status')}."
            next_unlock_action = 'plan_next_device_action'

        return self._build_response(
            mode=STOAMode.OPS.value,
            status='ops_operation_summary',
            response=response_text,
            action_type='ops',
            module='device_control',
            details={
                'device_control': True,
                'device_action': action,
                'pending_device_actions': self._summarize_pending_device_actions(
                    self._get_pending_device_confirmations(session_id=session_id)
                ),
                'devices': self.device_control.list_devices(),
                'device_control_summary': self._format_device_control_summary(),
                'next_unlock_action': next_unlock_action,
                'blockers': [],
                'device_confirmation': {
                    'action_id': action.get('action_id'),
                    'summary': action.get('summary'),
                    'expires_at': action.get('confirmation_expires_at'),
                    'confirm_command': 'confirmar última ação',
                    'cancel_command': 'cancelar última ação',
                },
            },
        )

    def _handle_device_confirmation_command(self, normalized_command: str) -> Optional[AgentResponse]:
        return self.handle_confirmation_shortcut(normalized_command, session_id='default', user_id='stoa_chat')

    def preprocess_command(
        self,
        command: str,
        *,
        session_id: str = 'default',
        user_id: str = 'stoa_chat',
    ) -> Optional[AgentResponse]:
        if not self.is_confirmation_command(command):
            return None
        return self.handle_confirmation_shortcut(command, session_id=session_id, user_id=user_id)

    def _is_device_command(self, command: str) -> bool:
        return DeviceCommandRouter.is_device_command(command)

    def _build_device_action_response(self, *, command: str, action: dict, device: dict, planned: dict, context_goal_id: Optional[str] = None) -> AgentResponse:
        requires_confirmation = action.get('status') == 'waiting_confirmation'
        devices = self.device_control.list_devices()
        device_label = device.get('device_name', device.get('device_id'))
        response_text = f"{planned.get('user_summary')} em {device_label}."
        if requires_confirmation:
            response_text += (
                "\nStatus: aguardando confirmação."
                "\nPróximo passo: confirmar última ação ou cancelar última ação."
            )
        else:
            response_text += f"\nStatus: {action.get('status')}.\nPróximo passo: aguardar resultado."
        return self._build_response(
            mode=STOAMode.OPS.value,
            status='ops_operation_summary',
            response=response_text,
            action_type='ops',
            module='device_control',
            details={
                'device_control': True,
                'device_action': action,
                'device': device,
                'devices': devices,
                'pending_device_actions': self._get_pending_device_confirmations(session_id='default'),
                'devices_count': len(devices),
                'device_control_summary': self._format_device_control_summary(),
                'device_intent': planned.get('intent'),
                'device_target_resolved': device.get('device_id'),
                'preferred_device_id': (self.device_control.get_preferred_device() or {}).get('device_id'),
                'context_goal_id': context_goal_id,
                'requires_confirmation': requires_confirmation,
                'device_confirmation': {
                    'action_id': action.get('action_id'),
                    'summary': action.get('summary'),
                    'expires_at': action.get('confirmation_expires_at'),
                    'prompt': action.get('confirmation_prompt'),
                    'confirm_command': 'confirmar última ação',
                    'cancel_command': 'cancelar última ação',
                    'manual_confirm_command': f"confirmar ação {action.get('action_id')}",
                } if requires_confirmation else None,
                'risk_level': action.get('risk'),
                'retryable': action.get('retryable'),
                'retry_count': action.get('retry_count'),
                'max_retries': action.get('max_retries'),
                'terminal_failure': action.get('terminal_failure'),
                'terminal_reason_code': action.get('terminal_reason_code'),
                'last_error_code': action.get('last_error_code'),
                'timeout_seconds': action.get('timeout_seconds'),
                'next_unlock_action': 'confirm_device_action' if requires_confirmation else 'await_device_result',
                'blockers': ['Ação sensível aguardando confirmação.'] if requires_confirmation else [],
                'working_context_used': False,
            },
        )

    def _handle_device_command(self, command: str) -> Optional[AgentResponse]:
        if not self._is_device_command(command):
            return None
        planned = DeviceCommandRouter.plan(command)
        if _guardrail:
            try:
                blocked, reason = _guardrail.check_action(planned.get('action_type'), planned.get('parameters') or {})
                if blocked:
                    return self._build_response(
                        mode=STOAMode.OPS.value,
                        status='ops_blocked',
                        response=reason,
                        action_type='ops',
                        module='device_control',
                        details={
                            'device_control': True,
                            'blockers': [reason],
                            'next_unlock_action': 'ask_developer',
                        },
                    )
            except Exception as e:
                print(f"[GUARDRAIL] Erro ao validar ação de device: {e}")
        device_hint = planned.get('target_device_hint') or DeviceCommandRouter.extract_device_hint(command)
        active_goal = self._get_active_goal() or {}
        current_goal = active_goal.get('goal_id') or self._get_working_context().get('current_plan_goal') or self._get_working_context().get('current_goal')
        resolution = self.device_control.resolve_device_detailed(
            device_hint,
            goal_id=current_goal,
            action_type=planned.get('action_type'),
            session_id='default',
        )
        device = resolution.get('device')
        if resolution.get('status') == 'ambiguous':
            return self._build_response(
                mode=STOAMode.OPS.value,
                status='ops_operation_summary',
                response='Mais de um dispositivo corresponde ao alvo. Escolha o device pelo nome, id ou alias.',
                action_type='ops',
                module='device_control',
                details={
                    'device_control': True,
                    'device_hint': device_hint,
                    'devices': resolution.get('candidates') or self.device_control.list_devices(),
                    'devices_count': len(resolution.get('candidates') or self.device_control.list_devices()),
                    'device_control_summary': self._format_device_control_summary(),
                    'blockers': [resolution.get('reason') or 'Device ambíguo.'],
                    'next_unlock_action': 'specify_device_alias',
                },
            )
        if not device:
            reason = resolution.get('reason') or 'Não há dispositivo online compatível para executar esse comando.'
            return self._build_response(
                mode=STOAMode.OPS.value,
                status='ops_not_found',
                response=reason,
                action_type='ops',
                module='device_control',
                details={
                    'device_control': True,
                    'device_hint': device_hint,
                    'devices': resolution.get('candidates') or self.device_control.list_devices(),
                    'devices_count': len(resolution.get('candidates') or self.device_control.list_devices()),
                    'device_control_summary': self._format_device_control_summary(),
                    'blockers': [reason],
                    'next_unlock_action': 'register_device_agent' if resolution.get('status') in {'offline', 'not_found'} else 'specify_device_alias',
                },
            )
        try:
            action = self.device_control.request_action(
                ActionRequest(
                    device_id=device['device_id'],
                    action_type=planned['action_type'],
                    target=planned.get('target'),
                    parameters={
                        **(planned.get('parameters') or {}),
                        'goal_id': current_goal,
                        'session_id': 'default',
                        'requested_by': 'stoa_chat',
                    },
                    command_text=command,
                    requested_by='stoa_chat',
                    confirmed=False,
                )
            )
        except ValueError as error:
            return self._build_response(
                mode=STOAMode.OPS.value,
                status='ops_not_found',
                response=str(error),
                action_type='ops',
                module='device_control',
                details={
                    'device_control': True,
                    'device': device,
                    'devices': self.device_control.list_devices(),
                    'blockers': [str(error)],
                    'next_unlock_action': 'review_device_capabilities',
                },
            )
        return self._build_device_action_response(command=command, action=action, device=device, planned=planned, context_goal_id=current_goal)

    def _resolve_contextual_command(self, command: str) -> tuple[str, Optional[str], bool, bool, str]:
        normalized_command = (command or '').lower().strip()
        context = self._get_working_context()
        fresh = self._working_context_is_fresh()

        if normalized_command in {'agora aplique'}:
            return 'aplique isso', STOAMode.DEV.value, True, fresh, 'Reutilizando o preview pendente.'

        if not fresh:
            return command, None, False, False, ''

        current_goal = context.get('current_goal')
        last_files = context.get('last_files') or []

        if normalized_command in {'continue', 'próximo passo', 'proximo passo', 'retome isso', 'continue o plano anterior'}:
            if current_goal:
                return f'organize um plano com os próximos passos para {current_goal}', STOAMode.PLANNER.value, True, True, 'Continuando o objetivo atual.'
            return command, None, False, True, ''

        if normalized_command == 'use o mesmo arquivo':
            if last_files:
                return f'ler arquivo {last_files[0]}', STOAMode.DEV.value, True, True, f"Reutilizando o arquivo {last_files[0]}."
            return command, None, False, True, ''

        if normalized_command == 'documente isso também':
            target_readme = next((file_path for file_path in last_files if file_path.lower().startswith('readme')), None) or 'README.md'
            if current_goal or last_files:
                goal_text = current_goal or 'o trabalho atual'
                return f'planeje atualizar o {target_readme} com a documentação relacionada a {goal_text}', STOAMode.PREVIEW.value, True, True, f"Reutilizando contexto recente para documentar em {target_readme}."
            return command, None, False, True, ''

        return command, None, False, True, ''

    @staticmethod
    def _extract_file_path(command: str) -> Optional[str]:
        match = re.search(r'([\w./\-]+\.[A-Za-z0-9_]+)', command)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_append_content(command: str) -> Optional[str]:
        lowered = command.lower()
        if ':' in command:
            return command.split(':', 1)[1].strip()
        if '->' in command:
            return command.split('->', 1)[1].strip()
        marker = 'adicionar uma linha no final do arquivo'
        if marker in lowered:
            suffix = command[len(command[:lowered.index(marker) + len(marker)]):].strip()
            if suffix:
                return suffix
        return None

    @staticmethod
    def _format_preview_result(result: dict) -> str:
        lines = [result.get('summary', 'Preview gerado.')]

        files_to_change = result.get('files_to_change') or []
        if files_to_change:
            lines.extend(['', 'Arquivos afetados:'])
            for file_path in files_to_change:
                lines.append(f"- {file_path}")

        steps = result.get('steps') or []
        if steps:
            lines.extend(['', 'Etapas previstas:'])
            for step in steps:
                marker = 'modifica' if step.get('would_modify') else 'valida'
                lines.append(f"- {step['index'] + 1}. {step['type']} ({step.get('path') or '-'}) [{marker}]")
                diff_summary = step.get('estimated_diff_summary') or {}
                if diff_summary:
                    lines.append(f"  Diff estimado: +{diff_summary.get('added_lines', 0)} / -{diff_summary.get('removed_lines', 0)}")
                if step.get('simulation_error'):
                    lines.append(f"  Simulação: {step['simulation_error']}")
                estimated_diff = step.get('estimated_diff')
                if estimated_diff:
                    lines.append('  Trecho do diff:')
                    for diff_line in estimated_diff.splitlines()[:16]:
                        lines.append(f"    {diff_line}")

        preflight = result.get('preflight') or {}
        errors = preflight.get('errors') or []
        warnings = preflight.get('warnings') or []
        if errors:
            lines.extend(['', 'Conflitos de preflight:'])
            for error in errors:
                lines.append(f"- {error.get('message', 'Conflito')} ({error.get('path') or '-'})")
        if warnings:
            lines.extend(['', 'Avisos de preflight:'])
            for warning in warnings:
                lines.append(f"- {warning.get('message', 'Aviso')} ({warning.get('path') or '-'})")

        simulation_errors = result.get('simulation_errors') or []
        if simulation_errors:
            lines.extend(['', 'Problemas de simulação:'])
            for item in simulation_errors:
                lines.append(f"- Etapa {item.get('step_index', 0) + 1}: {item.get('message', 'Falha')} ({item.get('path') or '-'})")

        return "\n".join(lines)

    @staticmethod
    def _format_recent_operations(events: list[dict]) -> str:
        if not events:
            return 'Nenhum evento encontrado no histórico operacional.'

        lines = ['Últimas operações:']
        for event in events:
            timestamp = event.get('timestamp', '-')
            event_type = event.get('event_type', '-')
            status = event.get('status', '-')
            summary = event.get('summary', '-')
            preview_id = event.get('preview_id')
            operation_id = event.get('operation_id')
            files = event.get('files') or []
            suffix = f" | op={operation_id}" if operation_id else ''
            if preview_id:
                suffix += f" | preview={preview_id}"
            file_suffix = f" | arquivos={', '.join(files[:3])}" if files else ''
            lines.append(f"- [{timestamp}] {event_type} ({status}){suffix}{file_suffix}")
            lines.append(f"  {summary}")
        return "\n".join(lines)

    @staticmethod
    def _format_single_operation(event: dict, title: str) -> str:
        if not event:
            return f'{title}: nenhum evento encontrado.'
        lines = [title]
        lines.append(f"- tipo: {event.get('event_type', '-')}")
        lines.append(f"- quando: {event.get('timestamp', '-')}")
        lines.append(f"- status: {event.get('status', '-')}")
        if event.get('operation_id'):
            lines.append(f"- operation_id: {event.get('operation_id')}")
        if event.get('preview_id'):
            lines.append(f"- preview_id: {event.get('preview_id')}")
        files = event.get('files') or []
        if files:
            lines.append(f"- arquivos: {', '.join(files)}")
        lines.append(f"- resumo: {event.get('summary', '-')}")
        return "\n".join(lines)

    @staticmethod
    def _format_operational_summary(summary: dict, hours: int) -> str:
        files = summary.get('affected_files') or []
        lines = [f'Resumo operacional das últimas {hours}h:']
        lines.append(f"- total de eventos: {summary.get('total_events', 0)}")
        lines.append(f"- operações aplicadas: {summary.get('applied', 0)}")
        lines.append(f"- falhas: {summary.get('failed', 0)}")
        lines.append(f"- rollbacks: {summary.get('rollbacks', 0)}")
        lines.append(f"- previews criados: {summary.get('previews_created', 0)}")
        lines.append(f"- arquivos afetados: {', '.join(files) if files else '-'}")
        return "\n".join(lines)

    @staticmethod
    def _format_affected_files(files: list[str], title: str) -> str:
        if not files:
            return f'{title}: nenhum arquivo encontrado.'
        lines = [title]
        for file_path in files:
            lines.append(f"- {file_path}")
        return "\n".join(lines)


    @staticmethod
    def _format_changed_files_ranking(items: list[dict], title: str) -> str:
        if not items:
            return f'{title}: nenhum arquivo encontrado.'
        lines = [title]
        for item in items:
            lines.append(f"- {item.get('path', '-')}: {item.get('count', 0)} operação(ões)")
        return "\n".join(lines)

    @staticmethod
    def _format_preview_funnel(funnel: dict, hours: int) -> str:
        lines = [f'Funil de preview das últimas {hours}h:']
        lines.append(f"- previews criados: {funnel.get('preview_created', 0)}")
        lines.append(f"- previews aplicados: {funnel.get('preview_applied', 0)}")
        lines.append(f"- previews cancelados: {funnel.get('preview_cancelled', 0)}")
        lines.append(f"- previews expirados: {funnel.get('preview_expired', 0)}")
        lines.append(f"- apply sem preview: {funnel.get('apply_preview_missing', 0)}")
        lines.append(f"- rollbacks: {funnel.get('rollbacks', 0)}")
        return "\n".join(lines)

    @staticmethod
    def _format_health_metrics(metrics: dict) -> str:
        status_counts = metrics.get('final_status_counts') or {}
        top_files = metrics.get('top_changed_files') or []
        funnel = metrics.get('preview_funnel') or {}
        hours = metrics.get('hours', 24)
        lines = [f'Saúde operacional das últimas {hours}h:']
        lines.append(f"- total de eventos: {metrics.get('total_events', 0)}")
        lines.append(f"- total de operações: {metrics.get('total_operations', 0)}")
        lines.append(f"- applied: {status_counts.get('applied', 0)}")
        lines.append(f"- failed: {status_counts.get('failed', 0)}")
        lines.append(f"- rolled_back: {status_counts.get('rolled_back', 0)}")
        lines.append(f"- cancelled: {status_counts.get('cancelled', 0)}")
        lines.append(f"- expired: {status_counts.get('expired', 0)}")
        lines.append(f"- preview_only: {status_counts.get('preview_only', 0)}")
        lines.append(f"- rollback_rate: {metrics.get('rollback_rate', 0):.2f}")
        lines.append(f"- failure_rate: {metrics.get('failure_rate', 0):.2f}")
        lines.append('Funil:')
        lines.append(f"- criados={funnel.get('preview_created', 0)}, aplicados={funnel.get('preview_applied', 0)}, cancelados={funnel.get('preview_cancelled', 0)}, expirados={funnel.get('preview_expired', 0)}, apply_missing={funnel.get('apply_preview_missing', 0)}, rollbacks={funnel.get('rollbacks', 0)}")
        if top_files:
            lines.append('Arquivos mais alterados:')
            for item in top_files[:5]:
                lines.append(f"- {item.get('path', '-')}: {item.get('count', 0)} operação(ões)")
        return "\n".join(lines)

    @staticmethod
    def _format_operation_timeline(events: list[dict], operation_id: str) -> str:
        if not events:
            return f'Nenhum evento encontrado para a operação {operation_id}.'
        lines = [f'Linha do tempo da operação {operation_id}:']
        for event in events:
            timestamp = event.get('timestamp', '-')
            event_type = event.get('event_type', '-')
            status = event.get('status', '-')
            preview_id = event.get('preview_id')
            files = event.get('files') or []
            lines.append(f"- [{timestamp}] {event_type} ({status})")
            if preview_id:
                lines.append(f"  preview_id: {preview_id}")
            if files:
                lines.append(f"  arquivos: {', '.join(files)}")
            lines.append(f"  resumo: {event.get('summary', '-')}")
        return "\n".join(lines)


    @staticmethod
    def _format_operation_summary(summary: dict | None, operation_id: str) -> str:
        if not summary:
            return f'Nenhuma operação encontrada para {operation_id}.'
        lines = [f'Resumo da operação {operation_id}:']
        lines.append(f"- status final: {summary.get('final_status', '-')}")
        if summary.get('preview_id'):
            lines.append(f"- preview_id: {summary.get('preview_id')}")
        lines.append(f"- eventos: {summary.get('event_count', 0)}")
        if summary.get('step_count') is not None:
            lines.append(f"- steps: {summary.get('step_count')}")
        files = summary.get('files') or []
        lines.append(f"- arquivos: {', '.join(files) if files else '-'}")
        lines.append(f"- rollback: {'sim' if summary.get('rollback_triggered') else 'não'}")
        if summary.get('created_at'):
            lines.append(f"- criado em: {summary.get('created_at')}")
        if summary.get('last_event_at'):
            lines.append(f"- último evento: {summary.get('last_event_at')}")
        if summary.get('error'):
            lines.append(f"- erro: {summary.get('error')}")
        timeline = summary.get('events') or []
        if timeline:
            lines.append('Eventos:')
            for event in timeline:
                lines.append(f"- [{event.get('timestamp', '-')}] {event.get('event_type', '-')} ({event.get('status', '-')})")
        return "\n".join(lines)

    @staticmethod
    def _format_change_set_result(result: dict) -> str:
        lines = [result.get('summary', 'Change set executado.')]

        applied_steps = result.get('applied_steps') or []
        if applied_steps:
            lines.extend(['', 'Etapas aplicadas:'])
            for step in applied_steps:
                step_path = step.get('path') or '-'
                lines.append(f"- {step['index'] + 1}. {step['type']} ({step_path})")

        failed_step = result.get('failed_step')
        if failed_step:
            lines.extend([
                '',
                f"Falha na etapa {failed_step['index'] + 1}: {failed_step['type']} ({failed_step.get('path') or '-'})",
                failed_step.get('error', 'Erro não informado'),
            ])

        preflight = result.get('preflight') or {}
        warnings = preflight.get('warnings') or []
        if warnings:
            lines.extend(['', 'Avisos de preflight:'])
            for warning in warnings:
                warning_path = warning.get('path') or '-'
                lines.append(f"- {warning.get('message', 'Aviso')} ({warning_path})")

        rollback = result.get('rollback')
        if rollback:
            status = 'ok' if rollback.get('success') else 'parcial/falhou'
            lines.extend(['', f"Rollback: {status}"])
            for detail in rollback.get('details', []):
                step_path = detail.get('path') or '-'
                if detail.get('restored'):
                    lines.append(f"- restaurado: {detail.get('type', 'step')} ({step_path})")
                else:
                    lines.append(f"- não restaurado: {detail.get('type', 'step')} ({step_path}) - {detail.get('detail', 'sem detalhe')}")

        return "\n".join(lines)



    @classmethod
    def _detect_mode_from_command(cls, command: str) -> str:
        tmp = cls.__new__(cls)
        return tmp.route_mode(command)

    def route_mode(self, command: str) -> str:
        normalized_command = (command or '').lower().strip()
        if self.is_confirmation_command(normalized_command):
            return STOAMode.OPS.value

        dev_control_commands = {
            'aplique isso', 'confirmar', 'executar plano', 'aplicar patch', 'pode aplicar',
            'cancelar preview', 'descartar plano', 'não aplicar', 'nao aplicar'
        }
        if normalized_command in dev_control_commands:
            return STOAMode.DEV.value

        preview_terms = [
            'planeje ', 'simule ', 'dry run', 'mostre o patch', 'o que mudaria'
        ]
        dev_terms = [
            'crie', 'adicione', 'substitua', 'altere', 'aplique isso', 'confirmar', 'executar plano',
            'aplicar patch', 'pode aplicar', 'cancelar preview', 'descartar plano', 'não aplicar', 'nao aplicar',
            'listar arquivos', 'ler arquivo', 'validar arquivo', 'validar import', 'abrir vscode', 'editar arquivo',
            'criar arquivo', 'substituir bloco', 'substituir no arquivo', 'substituir em arquivo'
        ]
        ops_terms = [
            'historico', 'histórico', 'ultimas operacoes', 'últimas operações', 'mostrar operacao', 'mostrar operação',
            'detalhes da operacao', 'detalhes da operação', 'status da operacao', 'status da operação',
            'saude operacional', 'saúde operacional', 'metricas', 'métricas', 'rollbacks', 'previews expiraram',
            'arquivos mais mudaram', 'funil de preview', 'ultima operacao aplicada', 'última operação aplicada'
        ]
        planner_terms = [
            'organize isso', 'monte um plano', 'proximos passos', 'próximos passos', 'roadmap',
            'como estruturar esse projeto', 'como construir isso', 'plano para', 'estruturar esse projeto'
        ]

        if any(term in normalized_command for term in preview_terms):
            return STOAMode.PREVIEW.value
        if any(term in normalized_command for term in dev_terms):
            return STOAMode.DEV.value
        if any(term in normalized_command for term in ops_terms):
            return STOAMode.OPS.value
        if any(term in normalized_command for term in planner_terms):
            return STOAMode.PLANNER.value
        if normalized_command.startswith('stoa:') or normalized_command.startswith('modo stoa') or normalized_command in {'ativar stoa', 'desativar stoa'}:
            return STOAMode.STOA.value
        return STOAMode.CONVERSATION.value

    @staticmethod
    def _with_mode(metadata: Optional[dict], mode: str) -> dict:
        payload = dict(metadata or {})
        payload['mode'] = mode
        return payload

    @staticmethod
    def _now_response_timestamp() -> str:
        return datetime.now().isoformat()

    def _build_operational_state_snapshot(
        self,
        *,
        original_command: str,
        effective_command: str,
        forced_mode: Optional[str],
        legacy_mode_hint: str,
        context_used: bool,
        context_fresh: bool,
    ) -> dict:
        active_goal = self._get_active_goal() or {}
        pending_preview_status = self._get_pending_preview_status()
        working_context = self._get_working_context()
        plan_steps = active_goal.get('plan_steps') or working_context.get('current_plan_steps') or []
        next_step = next((step for step in plan_steps if step.get('status') in {'pending', 'in_progress', 'failed'}), None)
        return {
            'original_command': original_command,
            'effective_command': effective_command,
            'forced_mode': forced_mode,
            'legacy_mode_hint': legacy_mode_hint,
            'contextual_resolution_used': context_used,
            'context_fresh': context_fresh,
            'pending_preview_valid': pending_preview_status.get('valid', False),
            'pending_preview_exists': pending_preview_status.get('exists', False),
            'pending_preview_expired': pending_preview_status.get('expired', False),
            'pending_preview_id': (pending_preview_status.get('preview') or {}).get('id'),
            'pending_preview_goal': (pending_preview_status.get('preview') or {}).get('goal'),
            'pending_preview_plan_step_ids': (pending_preview_status.get('preview') or {}).get('plan_step_ids') or [],
            'pending_preview_step_count': len(((pending_preview_status.get('preview') or {}).get('steps') or [])),
            'active_goal_status': active_goal.get('status'),
            'active_goal_id': active_goal.get('goal_id'),
            'active_goal_step_count': len(plan_steps),
            'active_goal_current_step_index': active_goal.get('current_step_index', working_context.get('current_step_index', 0)),
            'active_goal_next_step_id': (next_step or {}).get('id'),
            'active_goal_next_step_status': (next_step or {}).get('status'),
            'operational_phase': (self.operational_state or {}).get('current_phase'),
            'working_context_file_count': len(working_context.get('last_files') or []),
            'has_failed_steps': any(step.get('status') == 'failed' for step in plan_steps),
            'has_in_progress_steps': any(step.get('status') == 'in_progress' for step in plan_steps),
            'working_context_summary': self._format_working_context_summary(),
            'last_operation_id': working_context.get('last_operation_id'),
        }

    async def _execute_mode_handler(self, mode: str, command: str):
        preprocessed = self.preprocess_command(command)
        if preprocessed:
            return preprocessed
        if mode == STOAMode.PREVIEW.value:
            return await self.handle_preview(command)
        if mode == STOAMode.DEV.value:
            return await self.handle_dev(command)
        if mode == STOAMode.OPS.value:
            return await self.handle_ops(command)
        if mode == STOAMode.PLANNER.value:
            return await self.handle_planner(command)
        if mode == STOAMode.STOA.value:
            return await self.handle_stoa(command)
        return await self.handle_conversation(command)

    def _log_orchestration_decision(self, decision, state_snapshot: dict) -> None:
        from operation_log import OperationLogger

        OperationLogger.log_event(
            'orchestrator_decision',
            'info',
            f"Intent={decision.intent.name} | mode={decision.mode} | risk={decision.risk.level}",
            operation_id=state_snapshot.get('last_operation_id'),
            preview_id=state_snapshot.get('pending_preview_id'),
            metadata={
                'decision_id': decision.decision_id,
                'command': state_snapshot.get('original_command'),
                'effective_command': decision.effective_command,
                'legacy_mode_hint': decision.legacy_mode_hint,
                'forced_mode': decision.forced_mode,
                'intent': decision.intent.name,
                'intent_confidence': decision.intent.confidence,
                'intent_signals': decision.intent.signals,
                'risk_level': decision.risk.level,
                'risk_reason': decision.risk.reason,
                'risk_flags': decision.risk.flags,
                'confirmation_action': decision.confirmation.action,
                'confirmation_required': decision.confirmation.required,
                'confirmation_reason': decision.confirmation.reason,
                'operation_profile': decision.as_dict().get('operation_profile'),
                'notes': decision.notes,
            },
        )

    def _log_execution_event(self, execution_event) -> None:
        from operation_log import OperationLogger

        event_payload = execution_event.as_dict() if hasattr(execution_event, 'as_dict') else dict(execution_event or {})
        OperationLogger.log_event(
            'execution_event',
            event_payload.get('severity', 'info'),
            event_payload.get('summary', 'Execution event'),
            operation_id=event_payload.get('operation_id'),
            preview_id=event_payload.get('preview_id'),
            metadata=event_payload,
        )

    def _update_operational_state_from_decision(self, decision, response) -> None:
        response_data = response.data if isinstance(response.data, dict) else {}
        details = response_data.get('details') or {}
        active_goal = self._get_active_goal() or {}
        pending_preview_status = self._get_pending_preview_status()
        working_context = self._get_working_context()
        runtime_state = {
            'active_goal': active_goal,
            'pending_preview_status': pending_preview_status,
            'working_context': working_context,
        }
        transition = self.orchestrator.derive_transition(
            decision,
            response,
            current_state=dict(self.operational_state),
            runtime_state=runtime_state,
        )
        details['operational_transition'] = transition.__dict__
        preview_validity = self.orchestrator.assess_preview_validity(
            decision,
            response,
            state_snapshot=self._build_operational_state_snapshot(
                original_command=decision.effective_command,
                effective_command=decision.effective_command,
                forced_mode=decision.forced_mode,
                legacy_mode_hint=decision.legacy_mode_hint,
                context_used=bool(details.get('working_context_used')),
                context_fresh=bool(details.get('context_fresh')),
            ),
            runtime_state=runtime_state,
        )
        execution_model = self.orchestrator.build_execution_model(
            decision,
            response,
            runtime_state=runtime_state,
            transition=transition,
            preview_validity=preview_validity,
        )
        completion = self.orchestrator.assess_completion(runtime_state, preview_validity)
        decision_explanation = self.orchestrator.build_decision_explanation(
            decision,
            response,
            transition=transition,
            execution_model=execution_model,
            preview_validity=preview_validity,
            runtime_state=runtime_state,
        )
        execution_event = self.orchestrator.build_execution_event(
            decision,
            response,
            transition=transition,
            preview_validity=preview_validity,
            completion=completion,
            execution_model=execution_model,
            explanation=decision_explanation,
        )
        details['preview_validity'] = preview_validity.__dict__
        details['execution_model'] = execution_model.__dict__
        details['completion'] = completion.__dict__
        details['execution_event'] = execution_event.as_dict()
        details['decision_explanation'] = decision_explanation.__dict__
        details['phase_label'] = decision_explanation.phase_label
        details['blockers'] = list(decision_explanation.blockers)
        details['blocker_codes'] = list(decision_explanation.blocker_codes)
        details['next_unlock_action'] = decision_explanation.next_unlock_action
        details['operational_message'] = decision_explanation.user_message
        next_step = details.get('next_step') or next(
            (
                step
                for step in (active_goal.get('plan_steps') or [])
                if step.get('status') in {'pending', 'in_progress', 'failed'}
            ),
            None,
        )
        self.operational_state = {
            'current_mode': response_data.get('mode') or decision.mode,
            'current_phase': transition.next_phase,
            'last_intent': decision.intent.name,
            'last_risk_level': decision.risk.level,
            'last_risk_flags': list(decision.risk.flags),
            'last_confirmation_action': decision.confirmation.action,
            'last_decision_id': decision.decision_id,
            'last_command': decision.effective_command,
            'last_transition': transition.__dict__,
            'active_goal_id': active_goal.get('goal_id'),
            'active_goal_status': active_goal.get('status'),
            'pending_preview_id': (pending_preview_status.get('preview') or {}).get('id'),
            'pending_preview_valid': pending_preview_status.get('valid', False),
            'preview_validity_status': preview_validity.status,
            'current_step_id': (next_step or {}).get('id'),
            'current_step_status': (next_step or {}).get('status'),
            'current_operation_id': execution_model.current_operation_id,
            'next_unlock_action': decision_explanation.next_unlock_action,
            'blockers': list(decision_explanation.blockers),
            'completion_ready': completion.can_complete,
            'completion_reason_code': completion.reason_code,
            'last_updated_at': self._now_iso(),
        }
        self._persist_operational_state()
        self._log_execution_event(execution_event)

    @staticmethod
    def _infer_conversation_status(module: str, response_text: str) -> str:
        if module == 'info' and not response_text:
            return 'conversation_fallback'
        return 'conversation_answer'

    @staticmethod
    def _infer_planner_status(details: dict) -> str:
        if details.get('steps') or details.get('goal') or details.get('next_step'):
            return 'planner_plan_ready'
        return 'planner_plan_partial'

    @staticmethod
    def _infer_preview_status(details: dict) -> str:
        operation = details.get('operation')
        if operation == 'preview_unknown':
            return 'preview_unknown'
        if operation == 'preflight_failed':
            return 'preview_conflict'
        if details.get('preview_pending'):
            return 'preview_pending_stored'
        return 'preview_ready'

    @staticmethod
    def _infer_dev_status(details: dict) -> str:
        operation = details.get('operation')
        change_set = details.get('change_set') or {}
        if operation in {'apply_preview_change_set', 'apply_change_set'} and isinstance(change_set, dict) and not change_set.get('success', True):
            return 'dev_apply_failed'
        status_map = {
            'apply_preview_change_set': 'dev_preview_applied',
            'apply_preview_missing': 'dev_preview_missing',
            'apply_preview_expired': 'dev_preview_expired',
            'cancel_preview': 'dev_preview_cancelled',
            'cancel_preview_missing': 'dev_preview_cancelled',
            'apply_preview_preflight_failed': 'dev_apply_failed',
            'apply_change_set': 'dev_applied',
            'preflight_failed': 'dev_apply_failed',
            'append_to_file': 'dev_edit_completed',
            'replace_in_file': 'dev_edit_completed',
            'replace_block': 'dev_edit_completed',
            'replace_function': 'dev_edit_completed',
            'replace_class': 'dev_edit_completed',
            'insert_after_function': 'dev_edit_completed',
            'insert_after_class': 'dev_edit_completed',
            'insert_route': 'dev_edit_completed',
            'read_file': 'dev_edit_completed',
            'list_files': 'dev_edit_completed',
            'open_vscode': 'dev_edit_completed',
            'run_validation': 'dev_validation_completed',
            'run_import_check': 'dev_validation_completed',
            'unknown': 'dev_unknown',
        }
        return status_map.get(operation, 'dev_unknown')

    @staticmethod
    def _infer_ops_status(details: dict) -> str:
        operation = details.get('operation')
        status_map = {
            'read_recent_operations': 'ops_history',
            'read_failed_operations': 'ops_history',
            'read_recent_previews': 'ops_history',
            'read_last_applied_operation': 'ops_history',
            'read_operation_timeline': 'ops_operation_timeline',
            'read_operation_summary': 'ops_operation_summary',
            'summarize_health_metrics': 'ops_health_summary',
            'summarize_recent_operations': 'ops_metrics',
            'read_most_changed_files': 'ops_metrics',
            'read_preview_funnel': 'ops_metrics',
            'count_failed_operations': 'ops_metrics',
            'count_rollbacks': 'ops_metrics',
            'count_preview_expired': 'ops_metrics',
            'ops_unknown': 'ops_not_found',
            'read_recent_affected_files': 'ops_metrics',
            'read_recent_rollbacks': 'ops_metrics',
        }
        return status_map.get(operation, 'ops_not_found')

    def _build_response(
        self,
        *,
        mode: str,
        status: str,
        response: str,
        action_type: str,
        module: str,
        details: Optional[dict] = None,
    ) -> AgentResponse:
        payload = {
            'mode': mode,
            'status': status,
            'timestamp': self._now_response_timestamp(),
            'details': dict(details or {}),
        }
        return AgentResponse(
            response=response,
            action_type=action_type,
            module=module,
            data=payload,
        )

    def _resolve_plan_for_modes(self, command: str) -> tuple[dict, dict]:
        from dev_planner import DevPlanner
        from project_indexer import ProjectIndexer

        project_index = ProjectIndexer.build_index()
        planned = DevPlanner.plan(
            command,
            project_index=project_index,
            working_context=self._get_working_context(),
        )
        return planned, project_index

    def _update_working_context_from_response(self, command: str, response: AgentResponse) -> None:
        data = getattr(response, 'data', None) or {}
        mode = data.get('mode')
        status = data.get('status')
        details = data.get('details') or {}
        summary = response.response[:200] if response.response else None

        if status in {'planner_plan_ready', 'planner_plan_partial'}:
            self._update_working_context(
                current_goal=details.get('goal') or command,
                current_mode=mode,
                last_files=details.get('files') or [],
                last_plan=details,
                current_plan_goal=details.get('goal') or command,
                current_plan_steps=details.get('plan_steps') or [],
                current_step_index=details.get('current_step_index', 0),
            )
            self._sync_active_goal_from_working_context(status='active')
            return

        if status in {'preview_ready', 'preview_pending_stored'}:
            self._update_working_context(
                current_goal=(details.get('parsed') or {}).get('goal') or command,
                current_mode=mode,
                last_files=details.get('files_to_change') or [],
                last_change_set=details.get('parsed'),
                last_operation_id=details.get('operation_id'),
                last_preview_id=details.get('preview_id'),
                last_preview_summary=details.get('preview') or details.get('preflight') or summary,
                current_plan_goal=details.get('goal') or (details.get('parsed') or {}).get('goal') or command,
                current_plan_steps=details.get('plan_steps') or [],
                current_step_index=details.get('current_step_index', 0),
            )
            self._sync_active_goal_from_working_context(operation_id=details.get('operation_id'), status='active')
            return

        if mode == STOAMode.PREVIEW.value:
            parsed = details.get('parsed') or {}
            preview_files = details.get('files_to_change') or []
            candidate_files = preview_files or ([parsed.get('path')] if parsed.get('path') else [])
            if not candidate_files:
                extracted = self._extract_file_path(command)
                if extracted:
                    candidate_files = [extracted]
            if candidate_files:
                self._update_working_context(
                    current_goal=command,
                    current_mode=mode,
                    last_files=candidate_files,
                    last_change_set=parsed or self.working_context.get('last_change_set'),
                    current_plan_goal=details.get('goal') or command,
                    current_plan_steps=details.get('plan_steps') or self.working_context.get('current_plan_steps') or [],
                    current_step_index=details.get('current_step_index', self.working_context.get('current_step_index', 0)),
                )
                self._sync_active_goal_from_working_context(operation_id=details.get('operation_id'))
                return

        if status in {'dev_applied', 'dev_preview_applied', 'dev_edit_completed', 'dev_validation_completed'}:
            updated_plan_steps = details.get('updated_plan_steps') or details.get('plan_steps') or self.working_context.get('current_plan_steps') or []
            current_step_index = self.working_context.get('current_step_index', 0)
            if status in {'dev_applied', 'dev_preview_applied'} and updated_plan_steps:
                marked = False
                updated_plan_steps = [dict(step) for step in updated_plan_steps]
                for idx, step in enumerate(updated_plan_steps):
                    if step.get('status') != 'done':
                        updated_plan_steps[idx]['status'] = 'done'
                        current_step_index = min(idx + 1, len(updated_plan_steps))
                        marked = True
                        break
                if not marked:
                    current_step_index = len(updated_plan_steps)
            self._update_working_context(
                current_goal=self.working_context.get('current_goal') or command,
                current_mode=mode,
                last_files=details.get('files_changed') or details.get('preview_files_to_change') or [],
                last_change_set=details.get('change_set') or self.working_context.get('last_change_set'),
                last_operation_id=details.get('operation_id') or self.working_context.get('last_operation_id'),
                last_preview_id=details.get('preview_id') or self.working_context.get('last_preview_id'),
                last_preview_summary=details.get('preview_summary') or self.working_context.get('last_preview_summary'),
                current_plan_goal=self.working_context.get('current_plan_goal') or self.working_context.get('current_goal') or command,
                current_plan_steps=updated_plan_steps,
                current_step_index=current_step_index,
            )
            self._sync_active_goal_from_working_context(
                operation_id=details.get('operation_id') or self.working_context.get('last_operation_id'),
                status='failed' if status == 'dev_apply_failed' else None,
            )
            return

        if mode == STOAMode.OPS.value and details.get('operation_id'):
            self._update_working_context(
                current_mode=mode,
                last_operation_id=details.get('operation_id'),
            )

    async def handle_conversation(self, command: str) -> AgentResponse:
        preprocessed = self.preprocess_command(command)
        if preprocessed:
            return preprocessed
        normalized_command = (command or '').lower().strip()
        module = 'info'
        routing_prompt = (
            f"Analise este comando e determine qual agente deve processar:\n\n"
            f"Comando: \"{command}\"\n\n"
            "Retorne APENAS um JSON com:\n"
            '{"module": "weather|code|planning|web|education|strategy|system|time|info", "reason": "breve explicacao"}'
        )
        routing_response = OpenAIAdapter.generate_text(routing_prompt, max_output_tokens=200)
        try:
            routing_data = json.loads(routing_response)
            module = routing_data.get('module', 'info')
        except Exception:
            module = 'info'

        if any(term in normalized_command for term in ['abre o notepad', 'abre notepad', 'abre calculadora', 'abre o calc', 'abre calc', 'abre vscode', 'abre o vscode', 'executa dir', 'echo ']):
            module = 'system'

        if module == 'weather':
            weather_data = await WeatherAgent.get_info(config.LAT, config.LON)
            return self._build_response(
                mode=STOAMode.CONVERSATION.value,
                status='conversation_answer',
                response=self._format_weather(weather_data),
                action_type='info',
                module='weather',
                details=weather_data,
            )
        if module == 'code':
            code_data = await CodeAgent.generate(command)
            return self._build_response(
                mode=STOAMode.CONVERSATION.value,
                status='conversation_answer',
                response=f"```{code_data['language']}\n{code_data['code']}\n```",
                action_type='code',
                module='code',
                details=code_data,
            )
        if module == 'planning':
            planning_data = await PlanningAgent.create_schedule(command)
            return self._build_response(
                mode=STOAMode.CONVERSATION.value,
                status='conversation_answer',
                response=planning_data['schedule'],
                action_type='planning',
                module='planning',
                details=planning_data,
            )
        if module == 'web':
            web_data = await WebAgent.create_website(command)
            return self._build_response(
                mode=STOAMode.CONVERSATION.value,
                status='conversation_answer',
                response='Website gerado com sucesso! Abra em seu navegador.',
                action_type='web',
                module='web',
                details={'html': web_data['html']},
            )
        if module == 'education':
            edu_data = await EducationAgent.explain(command)
            return self._build_response(
                mode=STOAMode.CONVERSATION.value,
                status='conversation_answer',
                response=edu_data['explanation'],
                action_type='info',
                module='education',
                details=edu_data,
            )
        if module == 'strategy':
            strategy_data = await StrategyAgent.analyze(command)
            return self._build_response(
                mode=STOAMode.CONVERSATION.value,
                status='conversation_answer',
                response=strategy_data['strategy'],
                action_type='planning',
                module='strategy',
                details=strategy_data,
            )
        if module == 'time':
            now = datetime.now()
            payload = {'time': now.strftime('%H:%M:%S'), 'date': now.strftime('%A, %d de %B de %Y')}
            return self._build_response(
                mode=STOAMode.CONVERSATION.value,
                status='conversation_answer',
                response=f"🕐 {payload['time']}\n📅 {payload['date']}",
                action_type='info',
                module='time',
                details=payload,
            )
        if module == 'system':
            from system_executor import SystemExecutor
            system_command = normalized_command
            if normalized_command in ['abre o notepad', 'abre notepad']:
                system_command = 'notepad'
            elif normalized_command in ['abre calculadora', 'abre o calc', 'abre calc']:
                system_command = 'calc'
            elif normalized_command in ['abre vscode', 'abre o vscode', 'abre code', 'abre o code']:
                system_command = 'code'
            elif normalized_command == 'executa dir':
                system_command = 'dir'
            logger.info(f'[SYSTEM] Executando: {system_command}')
            result = SystemExecutor.run(system_command)
            return self._build_response(
                mode=STOAMode.CONVERSATION.value,
                status='conversation_answer',
                response=result,
                action_type='system',
                module='system',
                details={'command': system_command},
            )

        user_message = command  # Nome local para o texto do turno atual do usuário no fluxo real de chat.
        messages = list(self.conversation_history)
        system_prompt = 'Voce e STOA Agent - um assistente IA multimodal. Responda de forma util e concisa em portugues.'
        if _stoa_memory:
            try:
                memory_block = _stoa_memory.build_context_block(user_message)
                if memory_block:
                    system_prompt = system_prompt + "\n\n" + memory_block
            except Exception as e:
                print(f"[STOA MEMORY] Erro ao construir contexto: {e}")

        info_text = OpenAIAdapter.generate_from_messages(
            messages,
            system=system_prompt,
            max_output_tokens=1000,
        )
        if _stoa_memory:
            try:
                _stoa_memory.learn_from_turn(user_message, info_text, project="STOA")
            except Exception as e:
                print(f"[STOA MEMORY] Erro ao salvar memória: {e}")
        if _stoa_memory:
            try:
                _stoa_memory.extract_and_save_facts(user_message, project="STOA")
            except Exception as e:
                print(f"[STOA MEMORY] Erro ao extrair fatos: {e}")
        if _guardrail:
            try:
                blocked, reason = _guardrail.check_response(info_text)
                if blocked:
                    info_text = reason
            except Exception as e:
                print(f"[GUARDRAIL] Erro ao validar resposta: {e}")
        return self._build_response(
            mode=STOAMode.CONVERSATION.value,
            status=self._infer_conversation_status('info', info_text),
            response=info_text,
            action_type='info',
            module='info',
            details={},
        )

    async def handle_planner(self, command: str) -> AgentResponse:
        planned, _project_index = self._resolve_plan_for_modes(command)

        if planned.get('action') == 'apply_change_set':
            steps = planned.get('steps') or []
            files = planned.get('files') or list(dict.fromkeys([step.get('path') for step in steps if step.get('path')]))
            plan_steps = planned.get('plan_steps') or []
            details = {
                'goal': planned.get('goal') or command,
                'steps': steps,
                'plan_steps': plan_steps,
                'files': files,
                'risks': [],
                'next_step': steps[0].get('type') if steps else None,
                'next_plan_step': plan_steps[0] if plan_steps else None,
                'pending_steps_count': len([step for step in plan_steps if step.get('status') != 'done']),
                'current_step_index': 0,
                'planner_type': 'contextual_changeset_plan',
                'planner_context_used': planned.get('planner_context_used', False),
                'context_fresh': planned.get('context_fresh', False),
                'inferred_from_context': planned.get('inferred_from_context', False),
                'change_set': planned,
            }
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready',
                response=(
                    f"Plano pronto para execução.\n"
                    f"Objetivo: {details['goal']}\n"
                    f"Etapas: {len(steps)}\n"
                    f"Arquivos: {', '.join(files) if files else '-'}"
                ),
                action_type='planning',
                module='planner',
                details=details,
            )

        if planned.get('action') == 'planner_partial':
            plan_steps = planned.get('plan_steps') or []
            details = {
                'goal': planned.get('goal') or command,
                'steps': planned.get('steps') or [],
                'plan_steps': plan_steps,
                'files': planned.get('files') or [],
                'risks': [planned.get('reason')] if planned.get('reason') else [],
                'next_step': None,
                'next_plan_step': plan_steps[0] if plan_steps else None,
                'pending_steps_count': len([step for step in plan_steps if step.get('status') != 'done']),
                'current_step_index': 0,
                'planner_type': 'contextual_partial_plan',
                'missing': planned.get('missing') or [],
                'planner_context_used': planned.get('planner_context_used', False),
                'context_fresh': planned.get('context_fresh', False),
                'inferred_from_context': planned.get('inferred_from_context', False),
                'reason': planned.get('reason'),
            }
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_partial',
                response=planned.get('reason') or 'Plano parcial: faltam dados para estruturar a execução com segurança.',
                action_type='planning',
                module='planner',
                details=details,
            )

        strategy_data = await StrategyAgent.analyze(command)
        details = {
            'goal': command,
            'steps': [],
            'files': [],
            'risks': [],
            'next_step': None,
            'planner_type': 'strategy_plan',
            'strategy': strategy_data.get('strategy'),
            'created_at': strategy_data.get('created_at'),
            'planner_context_used': planned.get('planner_context_used', False),
            'context_fresh': planned.get('context_fresh', False),
            'inferred_from_context': planned.get('inferred_from_context', False),
            'reason': planned.get('reason'),
        }
        return self._build_response(
            mode=STOAMode.PLANNER.value,
            status=self._infer_planner_status(details),
            response=strategy_data['strategy'],
            action_type='planning',
            module='planner',
            details=details,
        )

    async def handle_preview(self, command: str) -> AgentResponse:
        logger.info(f'[PREVIEW] Processando: {command}')
        from dev_changeset import DevChangeSetExecutor
        from operation_log import OperationLogger

        planner_command = command
        normalized_command = (command or '').lower().strip()
        for prefix in ['planeje ', 'simule ', 'dry run ', 'mostre o patch ']:
            if normalized_command.startswith(prefix):
                planner_command = command[len(prefix):].strip()
                break

        planned, project_index = self._resolve_plan_for_modes(planner_command)
        planner_details = {
            'goal': planned.get('goal') or planner_command,
            'planner_context_used': planned.get('planner_context_used', False),
            'context_fresh': planned.get('context_fresh', False),
            'inferred_from_context': planned.get('inferred_from_context', False),
            'parsed': planned,
            'plan_steps': planned.get('plan_steps') or [],
            'files_to_change': planned.get('files') or [],
            'step_count': len(planned.get('steps') or []),
            'pending_steps_count': len([step for step in (planned.get('plan_steps') or []) if step.get('status') != 'done']),
            'next_step': ((planned.get('plan_steps') or [None])[0]),
            'current_step_index': 0,
            'missing': planned.get('missing') or [],
            'reason': planned.get('reason'),
        }

        if planned.get('action') != 'apply_change_set' or not planned.get('steps'):
            message = planned.get('reason') or 'Não foi possível montar um preview confiável para esse pedido.'
            return self._build_response(
                mode=STOAMode.PREVIEW.value,
                status='preview_unknown',
                response=message,
                action_type='preview',
                module='preview',
                details=planner_details,
            )

        preview_result = DevChangeSetExecutor.preview(planned, project_index=project_index)
        details = dict(planner_details)
        details.update({
            'preview': preview_result,
            'preflight': preview_result.get('preflight'),
            'estimated_diffs': preview_result.get('steps') or [],
            'files_to_change': preview_result.get('files_to_change') or details.get('files_to_change') or [],
            'step_count': len(preview_result.get('steps') or []) or details.get('step_count') or 0,
        })

        if preview_result.get('success'):
            pending_preview, replaced_preview = self._create_pending_preview(planned, preview_result)
            OperationLogger.log_event(
                'preview_created',
                'success',
                preview_result.get('summary', 'Preview criado.'),
                operation_id=pending_preview['operation_id'],
                preview_id=pending_preview['id'],
                files=pending_preview['files_to_change'],
                step_count=pending_preview['step_count'],
                metadata={
                    'created_at': pending_preview['created_at'],
                    'expires_at': pending_preview['expires_at'],
                    'operation_id': pending_preview['operation_id'],
                },
            )
            if replaced_preview:
                OperationLogger.log_event(
                    'preview_replaced',
                    'info',
                    f"Preview {replaced_preview.get('id', '-')} substituído por {pending_preview['id']}.",
                    operation_id=pending_preview['operation_id'],
                    preview_id=pending_preview['id'],
                    files=pending_preview['files_to_change'],
                    step_count=pending_preview['step_count'],
                    metadata={
                        'replaced_preview_id': replaced_preview.get('id'),
                        'replaced_operation_id': replaced_preview.get('operation_id'),
                    },
                )
            preflight_warnings = (preview_result.get('preflight') or {}).get('warnings') or []
            if preflight_warnings:
                OperationLogger.log_event(
                    'preflight_warning',
                    'warning',
                    'Preview criado com avisos de preflight.',
                    operation_id=pending_preview['operation_id'],
                    preview_id=pending_preview['id'],
                    files=pending_preview['files_to_change'],
                    step_count=pending_preview['step_count'],
                    metadata={'warnings': preflight_warnings},
                )

            preview_text = STOAQuantumBrain._format_preview_result(preview_result)
            preview_text += (
                f"\n\nPreview pendente pronto para aplicação."
                f"\nPreview ID: {pending_preview['id']}"
                f"\nOperation ID: {pending_preview['operation_id']}"
                f"\nEtapas: {pending_preview['step_count']}"
                f"\nArquivos: {', '.join(pending_preview['files_to_change']) if pending_preview['files_to_change'] else '-'}"
                f"\nExpira em: {pending_preview['expires_at']}"
                "\nUse 'aplique isso', 'confirmar', 'executar plano' ou 'aplicar patch'."
            )
            if replaced_preview:
                preview_text += f"\nPreview anterior invalidado/substituído: {replaced_preview.get('id', '-')}"

            details.update({
                'preview_pending': True,
                'preview_id': pending_preview['id'],
                'operation_id': pending_preview['operation_id'],
                'expires_at': pending_preview['expires_at'],
                'preview_created_at': pending_preview['created_at'],
                'preview_expires_at': pending_preview['expires_at'],
                'preview_step_count': pending_preview['step_count'],
                'preview_files_to_change': pending_preview['files_to_change'],
                'replaced_preview_id': (replaced_preview or {}).get('id'),
            })
            return self._build_response(
                mode=STOAMode.PREVIEW.value,
                status=self._infer_preview_status(details),
                response=preview_text,
                action_type='preview',
                module='preview',
                details=details,
            )

        return self._build_response(
            mode=STOAMode.PREVIEW.value,
            status=self._infer_preview_status(details),
            response=STOAQuantumBrain._format_preview_result(preview_result),
            action_type='preview',
            module='preview',
            details=details,
        )

    async def handle_dev(self, command: str) -> AgentResponse:
        logger.info(f'[DEV] Processando: {command}')
        result, metadata = self._handle_dev_command(command, mode_override=STOAMode.DEV.value)
        details = dict(metadata or {})
        change_set = details.get('change_set') or {}
        applied_steps = change_set.get('applied_steps') or []
        current_plan_steps = details.get('updated_plan_steps') or details.get('plan_steps') or self._get_current_plan_steps()
        details.setdefault('operation_id', details.get('operation_id'))
        details.setdefault('preview_id', details.get('preview_id'))
        details.setdefault('plan_steps', current_plan_steps)
        details.setdefault('next_step', self._get_next_plan_step())
        details.setdefault('pending_steps_count', len([step for step in current_plan_steps if step.get('status') != 'done']))
        details.setdefault('current_step_index', self._get_working_context().get('current_step_index', 0))
        details.setdefault('plan_progress_summary', self._format_plan_progress())
        details.setdefault(
            'files_changed',
            list(
                dict.fromkeys(
                    [step.get('path') for step in applied_steps if step.get('path')]
                    + ([details.get('path')] if details.get('path') else [])
                    + (details.get('preview_files_to_change') or [])
                )
            ),
        )
        details.setdefault('step_count', details.get('preview_step_count') or len(applied_steps) or (change_set.get('step_count') if isinstance(change_set, dict) else None))
        details.setdefault('rollback_triggered', bool(change_set.get('rollback')) if isinstance(change_set, dict) else False)
        details.setdefault('validation', details.get('operation') if details.get('operation') == 'run_validation' else None)
        details.setdefault('import_check', details.get('operation') if details.get('operation') == 'run_import_check' else None)
        failed_step = change_set.get('failed_step') if isinstance(change_set, dict) else None
        details.setdefault('error', failed_step.get('error') if isinstance(failed_step, dict) else None)
        return self._build_response(
            mode=STOAMode.DEV.value,
            status=self._infer_dev_status(details),
            response=result,
            action_type='dev',
            module='dev',
            details=details,
        )

    async def handle_ops(self, command: str) -> AgentResponse:
        logger.info(f'[OPS] Processando: {command}')
        result, metadata = self._handle_dev_command(command, mode_override=STOAMode.OPS.value)
        details = dict(metadata or {})

    async def handle_stoa(self, command: str) -> AgentResponse:
        logger.info(f'[STOA] Processando: {command}')
        stoa_command = (command or '').strip()
        if stoa_command.lower().startswith('stoa:'):
            stoa_command = stoa_command[5:].strip()

        if not stoa_command:
            stoa_command = 'forneça um relatório operacional e próximos passos de alto nível.'

        normalized_stoa = stoa_command.lower().strip()

        # Comandos piloto STOA
        if normalized_stoa.startswith('defina objetivo') or normalized_stoa.startswith('meta:') or normalized_stoa.startswith('objetivo:'):
            goal_text = re.sub(r'^(defina objetivo|meta:|objetivo:)', '', stoa_command, flags=re.IGNORECASE).strip()
            if not goal_text:
                return self._build_response(
                    mode=STOAMode.STOA.value,
                    status='stoa_goal_error',
                    response='Informe o texto do objetivo após "defina objetivo".',
                    action_type='stoa',
                    module='stoa',
                    details={'stoa_command': stoa_command},
                )
            goal = self._ensure_active_goal(goal=goal_text)
            return self._build_response(
                mode=STOAMode.STOA.value,
                status='stoa_goal_set',
                response=f'Objetivo definido como: {goal_text}',
                action_type='stoa',
                module='stoa',
                details={'stoa_command': stoa_command, 'goal': goal},
            )

        if normalized_stoa in {'status do objetivo', 'status do objetivo atual', 'status geral', 'como estamos'}:
            active_goal = self._get_active_goal()
            response_text = self._format_active_goal_summary()
            if not active_goal:
                response_text += '\nUse "stoa: defina objetivo ..." para começar um objetivo piloto.'
            return self._build_response(
                mode=STOAMode.STOA.value,
                status='stoa_status',
                response=response_text,
                action_type='stoa',
                module='stoa',
                details={'stoa_command': stoa_command, 'active_goal': active_goal},
            )

        if normalized_stoa in {'limpar objetivo', 'resetar objetivo', 'encerrar objetivo', 'cancelar objetivo'}:
            previous_goal = self._clear_active_goal()
            result_msg = 'Objetivo limpo.' if previous_goal else 'Não havia objetivo ativo.'
            return self._build_response(
                mode=STOAMode.STOA.value,
                status='stoa_goal_cleared',
                response=result_msg,
                action_type='stoa',
                module='stoa',
                details={'stoa_command': stoa_command, 'previous_goal': previous_goal},
            )

        if normalized_stoa in {'proximo passo', 'próximo passo', 'passo seguinte', 'o que fazer agora'}:
            guidance = self._get_next_action()
            return self._build_response(
                mode=STOAMode.STOA.value,
                status='stoa_next_step',
                response=self._format_goal_guidance(),
                action_type='stoa',
                module='stoa',
                details={'stoa_command': stoa_command, **guidance},
            )

        # Reuso das capacidades existentes, com forçamento de modo stoa no resultado.
        target_mode = self.route_mode(stoa_command)
        if target_mode == STOAMode.PLANNER.value:
            response = await self.handle_planner(stoa_command)
        elif target_mode == STOAMode.DEV.value:
            response = await self.handle_dev(stoa_command)
        elif target_mode == STOAMode.OPS.value:
            response = await self.handle_ops(stoa_command)
        else:
            response = await self.handle_conversation(stoa_command)

        response.data = response.data or {}
        response.data['mode'] = STOAMode.STOA.value
        response.data['details'] = response.data.get('details', {})
        response.data['details']['stoa_command'] = stoa_command
        response.action_type = 'stoa'
        response.module = 'stoa'
        return response
        if details.get('operation_id') and details.get('summary'):
            details.setdefault('summary', details.get('summary'))
        if details.get('operation_id') and details.get('count') is not None:
            details.setdefault('events', details.get('count'))
        if details.get('metrics'):
            details.setdefault('metrics', details.get('metrics'))
        if details.get('files'):
            details.setdefault('files', details.get('files'))
        return self._build_response(
            mode=STOAMode.OPS.value,
            status=self._infer_ops_status(details),
            response=result,
            action_type='ops',
            module='ops',
            details=details,
        )

    async def process_command(self, command: str) -> AgentResponse:
        """Processa comando em linguagem natural usando roteamento multimodo explicito."""
        preprocessed = self.preprocess_command(command)
        if preprocessed:
            return preprocessed

        normalized_command = (command or '').lower().strip()

        if normalized_command.startswith('stoa:') or normalized_command.startswith('modo stoa') or normalized_command in {'ativar stoa', 'desativar stoa'}:
            return await self.handle_stoa(command)

        if normalized_command in {
            'listar dispositivos',
            'liste os dispositivos',
            'quais dispositivos estão online',
            'quais dispositivos estao online',
            'mostrar dispositivos',
        }:
            devices = self.device_control.list_devices()
            return self._build_response(
                mode=STOAMode.OPS.value,
                status='ops_operation_summary',
                response=self._format_device_control_summary(),
                action_type='ops',
                module='ops',
                details={
                    'devices': devices,
                    'devices_count': len(devices),
                    'device_control_summary': self._format_device_control_summary(),
                },
            )

        if self._is_device_command(command):
            device_response = self._handle_device_command(command)
            if device_response:
                return device_response

        if normalized_command in {'o que eu faço agora?', 'o que eu faço agora', 'qual o próximo passo real', 'qual o proximo passo real'}:
            guidance = self._get_next_action()
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready' if guidance.get('type') != 'no_active_goal' else 'planner_plan_partial',
                response=self._format_goal_guidance(),
                action_type='planning',
                module='planner',
                details={
                    'guidance_type': guidance.get('type'),
                    'active_goal_used': bool(self._get_active_goal()),
                    'active_goal_status': guidance.get('active_goal_status'),
                    'next_step': guidance.get('next_step'),
                    'blockers': guidance.get('blockers') or [],
                    'can_complete_goal': guidance.get('can_complete_goal', False),
                    'preview_pending': guidance.get('preview_pending', False),
                    'preview_id': guidance.get('preview_id'),
                },
            )

        if normalized_command in {'o que está bloqueando', 'o que esta bloqueando'}:
            guidance = self._get_next_action()
            blockers = guidance.get('blockers') or []
            response_text = (
                "Bloqueios atuais:\n" + "\n".join(f"- {item}" for item in blockers)
                if blockers else
                'Não há bloqueios explícitos no momento.'
            )
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready' if blockers else 'planner_plan_partial',
                response=response_text,
                action_type='planning',
                module='planner',
                details={
                    'guidance_type': guidance.get('type'),
                    'active_goal_used': bool(self._get_active_goal()),
                    'active_goal_status': guidance.get('active_goal_status'),
                    'next_step': guidance.get('next_step'),
                    'blockers': blockers,
                    'can_complete_goal': guidance.get('can_complete_goal', False),
                    'preview_pending': guidance.get('preview_pending', False),
                    'preview_id': guidance.get('preview_id'),
                },
            )

        if normalized_command in {'posso concluir isso', 'o que falta para concluir'}:
            guidance = self._get_next_action()
            can_complete = self._can_complete_active_goal()
            active_goal = self._get_active_goal()
            if normalized_command == 'posso concluir isso':
                response_text = (
                    'Sim. Todas as etapas relevantes parecem concluídas.' if can_complete else
                    'Ainda não. Há pendências ou bloqueios antes da conclusão do objetivo.'
                )
            else:
                plan_steps = (active_goal or {}).get('plan_steps') or []
                remaining = [step for step in plan_steps if step.get('status') in {'pending', 'failed', 'in_progress'}]
                response_text = (
                    "Falta para concluir:\n" + "\n".join(f"- {step.get('title')}: {step.get('status')}" for step in remaining)
                    if remaining else
                    'Nada relevante falta para concluir pelo estado atual.'
                )
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready' if can_complete or active_goal else 'planner_plan_partial',
                response=response_text,
                action_type='planning',
                module='planner',
                details={
                    'guidance_type': guidance.get('type'),
                    'active_goal_used': bool(active_goal),
                    'active_goal_status': guidance.get('active_goal_status'),
                    'next_step': guidance.get('next_step'),
                    'blockers': guidance.get('blockers') or [],
                    'can_complete_goal': can_complete,
                    'preview_pending': guidance.get('preview_pending', False),
                    'preview_id': guidance.get('preview_id'),
                },
            )

        if normalized_command in {'qual é o objetivo atual', 'qual e o objetivo atual', 'qual o status do objetivo atual'}:
            active_goal = self._get_active_goal()
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready' if active_goal else 'planner_plan_partial',
                response=self._format_active_goal_summary(),
                action_type='planning',
                module='planner',
                details={
                    'active_goal_used': bool(active_goal),
                    'active_goal_summary': self._format_active_goal_summary(),
                    'active_goal_status': (active_goal or {}).get('status'),
                    'goal_id': (active_goal or {}).get('goal_id'),
                    'linked_operation_ids': (active_goal or {}).get('linked_operation_ids') or [],
                    'plan_steps': (active_goal or {}).get('plan_steps') or [],
                    'current_step_index': (active_goal or {}).get('current_step_index', 0),
                },
            )

        if normalized_command in {'pausa isso', 'retoma isso', 'conclui isso', 'marque isso como concluído', 'marque isso como concluido', 'falhou', 'limpar objetivo', 'encerrar objetivo'}:
            active_goal = self._get_active_goal()
            if not active_goal and normalized_command not in {'limpar objetivo', 'encerrar objetivo'}:
                return self._build_response(
                    mode=STOAMode.PLANNER.value,
                    status='planner_plan_partial',
                    response='Não há objetivo ativo para atualizar.',
                    action_type='planning',
                    module='planner',
                    details={
                        'active_goal_used': False,
                        'active_goal_summary': self._format_active_goal_summary(),
                        'active_goal_status': None,
                        'goal_id': None,
                        'linked_operation_ids': [],
                    },
                )

            if normalized_command in {'limpar objetivo', 'encerrar objetivo'}:
                previous_goal = self._clear_active_goal()
                return self._build_response(
                    mode=STOAMode.PLANNER.value,
                    status='planner_plan_ready',
                    response='Objetivo ativo removido da sessão.' if previous_goal else 'Não havia objetivo ativo para encerrar.',
                    action_type='planning',
                    module='planner',
                    details={
                        'active_goal_used': bool(previous_goal),
                        'active_goal_summary': self._format_active_goal_summary(),
                        'active_goal_status': None,
                        'goal_id': (previous_goal or {}).get('goal_id'),
                        'linked_operation_ids': (previous_goal or {}).get('linked_operation_ids') or [],
                    },
                )

            target_status = {
                'pausa isso': 'paused',
                'retoma isso': 'active',
                'conclui isso': 'completed',
                'marque isso como concluído': 'completed',
                'marque isso como concluido': 'completed',
                'falhou': 'failed',
            }[normalized_command]
            updated_goal = self._set_active_goal_status(target_status)
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready',
                response=self._format_active_goal_summary(),
                action_type='planning',
                module='planner',
                details={
                    'active_goal_used': True,
                    'active_goal_summary': self._format_active_goal_summary(),
                    'active_goal_status': (updated_goal or {}).get('status'),
                    'goal_id': (updated_goal or {}).get('goal_id'),
                    'linked_operation_ids': (updated_goal or {}).get('linked_operation_ids') or [],
                    'plan_steps': (updated_goal or {}).get('plan_steps') or [],
                    'current_step_index': (updated_goal or {}).get('current_step_index', 0),
                },
            )

        if normalized_command in {'próximo passo', 'proximo passo'}:
            if not self._working_context_is_fresh() or not self._get_current_plan_steps():
                return self._build_response(
                    mode=STOAMode.PLANNER.value,
                    status='planner_plan_partial',
                    response='Não há plano recente com etapas explícitas suficiente para indicar o próximo passo com segurança.',
                    action_type='planning',
                    module='planner',
                    details={
                        'goal': self._get_working_context().get('current_plan_goal') or self._get_working_context().get('current_goal'),
                        'plan_steps': self._get_current_plan_steps(),
                        'next_step': None,
                        'pending_steps_count': 0,
                        'current_step_index': self._get_working_context().get('current_step_index', 0),
                        'working_context_used': True,
                        'working_context_summary': self._format_working_context_summary(),
                        'context_fresh': self._working_context_is_fresh(),
                    },
                )
            next_step = self._get_next_plan_step()
            pending_steps = self._get_pending_plan_steps()
            if not next_step:
                return self._build_response(
                    mode=STOAMode.PLANNER.value,
                    status='planner_plan_ready',
                    response='O plano atual parece concluído. Não há etapas pendentes.',
                    action_type='planning',
                    module='planner',
                    details={
                        'goal': self._get_working_context().get('current_plan_goal') or self._get_working_context().get('current_goal'),
                        'plan_steps': self._get_current_plan_steps(),
                        'next_step': None,
                        'pending_steps_count': 0,
                        'current_step_index': self._get_working_context().get('current_step_index', 0),
                        'working_context_used': True,
                        'working_context_summary': self._format_working_context_summary(),
                        'context_fresh': True,
                    },
                )
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready',
                response=f"Próxima etapa: {next_step.get('title')}\n{next_step.get('description')}",
                action_type='planning',
                module='planner',
                details={
                    'goal': self._get_working_context().get('current_plan_goal') or self._get_working_context().get('current_goal'),
                    'plan_steps': self._get_current_plan_steps(),
                    'next_step': next_step,
                    'pending_steps_count': len(pending_steps),
                    'current_step_index': self._get_working_context().get('current_step_index', 0),
                    'working_context_used': True,
                    'working_context_summary': self._format_working_context_summary(),
                    'context_fresh': True,
                },
            )

        if normalized_command in {'o que falta?', 'o que falta'}:
            pending_steps = self._get_pending_plan_steps()
            if not self._working_context_is_fresh() or not self._get_current_plan_steps():
                return self._build_response(
                    mode=STOAMode.PLANNER.value,
                    status='planner_plan_partial',
                    response='Não há um plano recente com etapas explícitas suficiente para listar pendências.',
                    action_type='planning',
                    module='planner',
                    details={
                        'plan_steps': self._get_current_plan_steps(),
                        'pending_steps_count': 0,
                        'working_context_used': True,
                        'working_context_summary': self._format_working_context_summary(),
                        'context_fresh': self._working_context_is_fresh(),
                    },
                )
            if not pending_steps:
                response_text = 'Nada pendente no plano atual.'
            else:
                response_text = "Pendências do plano atual:\n" + "\n".join(
                    f"- {step.get('title')}: {step.get('description')}" for step in pending_steps
                )
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready',
                response=response_text,
                action_type='planning',
                module='planner',
                details={
                    'goal': self._get_working_context().get('current_plan_goal') or self._get_working_context().get('current_goal'),
                    'plan_steps': self._get_current_plan_steps(),
                    'pending_steps_count': len(pending_steps),
                    'next_step': pending_steps[0] if pending_steps else None,
                    'current_step_index': self._get_working_context().get('current_step_index', 0),
                    'working_context_used': True,
                    'working_context_summary': self._format_working_context_summary(),
                    'context_fresh': True,
                },
            )

        if normalized_command in {'essa etapa já foi feita?', 'essa etapa ja foi feita?', 'essa etapa já foi feita', 'essa etapa ja foi feita'}:
            next_step = self._get_next_plan_step()
            if not self._working_context_is_fresh() or not self._get_current_plan_steps():
                response_text = 'Não há contexto suficiente para confirmar o estado dessa etapa com segurança.'
            elif not next_step:
                response_text = 'Pelo contexto atual, todas as etapas do plano parecem concluídas.'
            else:
                response_text = f"A próxima etapa ainda está pendente: {next_step.get('title')}."
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_partial',
                response=response_text,
                action_type='planning',
                module='planner',
                details={
                    'goal': self._get_working_context().get('current_plan_goal') or self._get_working_context().get('current_goal'),
                    'plan_steps': self._get_current_plan_steps(),
                    'next_step': next_step,
                    'pending_steps_count': len(self._get_pending_plan_steps()),
                    'current_step_index': self._get_working_context().get('current_step_index', 0),
                    'working_context_used': True,
                    'working_context_summary': self._format_working_context_summary(),
                    'context_fresh': self._working_context_is_fresh(),
                },
            )

        if normalized_command in {'marque essa etapa como concluída', 'marque essa etapa como concluida'}:
            if not self._working_context_is_fresh() or not self._get_current_plan_steps():
                return self._build_response(
                    mode=STOAMode.PLANNER.value,
                    status='planner_plan_partial',
                    response='Não há etapa ativa suficiente no contexto para marcar como concluída.',
                    action_type='planning',
                    module='planner',
                    details={
                        'plan_steps': self._get_current_plan_steps(),
                        'pending_steps_count': len(self._get_pending_plan_steps()),
                        'current_step_index': self._get_working_context().get('current_step_index', 0),
                        'working_context_used': True,
                        'working_context_summary': self._format_working_context_summary(),
                        'context_fresh': self._working_context_is_fresh(),
                    },
                )
            completed_step = self._mark_current_step_done()
            return self._build_response(
                mode=STOAMode.PLANNER.value,
                status='planner_plan_ready',
                response=(
                    f"Etapa marcada como concluída: {completed_step.get('title')}"
                    if completed_step else
                    'Não havia etapa pendente para marcar como concluída.'
                ),
                action_type='planning',
                module='planner',
                details={
                    'plan_steps': self._get_current_plan_steps(),
                    'next_step': self._get_next_plan_step(),
                    'pending_steps_count': len(self._get_pending_plan_steps()),
                    'current_step_index': self._get_working_context().get('current_step_index', 0),
                    'completed_step': completed_step,
                    'working_context_used': True,
                    'working_context_summary': self._format_working_context_summary(),
                    'context_fresh': True,
                },
            )

        if normalized_command in {'qual é o contexto atual', 'qual e o contexto atual', 'em que estamos trabalhando'}:
            summary = self._format_working_context_summary()
            details = {
                'working_context_used': False,
                'working_context_summary': summary,
                'context_fresh': self._working_context_is_fresh(),
                'context': self._get_working_context(),
            }
            return self._build_response(
                mode=STOAMode.OPS.value,
                status='ops_operation_summary',
                response=summary,
                action_type='ops',
                module='ops',
                details=details,
            )

        if normalized_command in {'limpar contexto', 'esquecer contexto atual'}:
            previous = self._clear_working_context()
            return self._build_response(
                mode=STOAMode.OPS.value,
                status='ops_operation_summary',
                response='Contexto operacional limpo.',
                action_type='ops',
                module='ops',
                details={
                    'working_context_used': False,
                    'working_context_summary': 'Nenhum contexto operacional ativo.',
                    'context_fresh': False,
                    'previous_context': previous,
                },
            )

        resolved_command, forced_mode, context_used, context_fresh, context_note = self._resolve_contextual_command(command)
        effective_command = resolved_command

        # ── Memória: buscar contexto relevante e injetar no histórico ─────────
        try:
            mem_block = _stoa_memory.build_context_block(command, top_k=5)
            if mem_block:
                self.conversation_history.append({'role': 'system', 'content': mem_block})
        except Exception:
            pass
        # ── Fim injeção de memória ────────────────────────────────────────────

        self.conversation_history.append({'role': 'user', 'content': command})
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]

        legacy_mode_hint = self.route_mode(effective_command)
        state_snapshot = self._build_operational_state_snapshot(
            original_command=command,
            effective_command=effective_command,
            forced_mode=forced_mode,
            legacy_mode_hint=legacy_mode_hint,
            context_used=context_used,
            context_fresh=context_fresh,
        )
        decision = self.orchestrator.decide(
            effective_command,
            state_snapshot=state_snapshot,
            legacy_mode_hint=legacy_mode_hint,
            forced_mode=forced_mode,
        )
        mode = decision.mode
        logger.info(
            f"Comando orquestrado: intent={decision.intent.name} mode={mode} risk={decision.risk.level} confirmation={decision.confirmation.action}"
        )
        self._log_orchestration_decision(decision, state_snapshot)

        response = await self._execute_mode_handler(mode, effective_command)
        response = ResponseConsolidator.consolidate(response, decision)

        if not isinstance(getattr(response, 'data', None), dict):
            response.data = {
                'mode': mode,
                'status': 'conversation_fallback',
                'timestamp': self._now_response_timestamp(),
                'details': {},
            }
        details = response.data.setdefault('details', {})
        details.setdefault('working_context_used', context_used)
        details.setdefault('working_context_summary', self._format_working_context_summary())
        details.setdefault('context_fresh', context_fresh)
        if context_note:
            details.setdefault('context_note', context_note)
        if effective_command != command:
            details.setdefault('resolved_command', effective_command)
        details.setdefault('operational_state', dict(self.operational_state))

        self._update_working_context_from_response(command, response)
        details['working_context_summary'] = self._format_working_context_summary()
        details['context_fresh'] = self._working_context_is_fresh()

        # ── Memória: salvar turno e extrair fatos ─────────────────────────────
        try:
            _stoa_memory.learn_from_turn(command, response.response, project=None)
            _stoa_memory.extract_and_save_facts(command)
        except Exception:
            pass
        # ── Fim Memória ───────────────────────────────────────────────────────

        active_goal = self._get_active_goal()
        details.setdefault('active_goal_used', bool(active_goal))
        details.setdefault('active_goal_summary', self._format_active_goal_summary())
        details.setdefault('active_goal_status', (active_goal or {}).get('status'))
        details.setdefault('goal_id', (active_goal or {}).get('goal_id'))
        details.setdefault('linked_operation_ids', (active_goal or {}).get('linked_operation_ids') or [])
        if active_goal:
            details.setdefault('next_step', next((step for step in (active_goal.get('plan_steps') or []) if step.get('status') in {'pending', 'in_progress', 'failed'}), None))

        self._update_operational_state_from_decision(decision, response)
        details['operational_state'] = dict(self.operational_state)

        self.conversation_history.append({'role': 'assistant', 'content': response.response})
        return response

    def _handle_dev_command(self, command: str, mode_override: Optional[str] = None) -> tuple[str, dict]:
        from operation_log import OperationLogger
        from planner_symbol import Planner, Executor
        from project_indexer import ProjectIndexer

        # Instancia o planner com o state store
        planner = Planner(self.state_store)

        normalized_command = (command or '').lower().strip()
        preview_mode = (
            mode_override == STOAMode.PREVIEW.value
            or normalized_command.startswith('planeje ')
            or normalized_command.startswith('simule ')
            or ' simule ' in f' {normalized_command} '
            or 'dry run' in normalized_command
            or 'mostre o patch' in normalized_command
            or 'o que mudaria' in normalized_command
            or normalized_command == 'preview'
        )
        apply_preview_mode = mode_override == STOAMode.DEV.value and normalized_command in {
            'aplique isso',
            'confirmar',
            'executar plano',
            'aplicar patch',
            'pode aplicar',
        }
        cancel_preview_mode = mode_override == STOAMode.DEV.value and normalized_command in {
            'cancelar preview',
            'descartar plano',
            'não aplicar',
            'nao aplicar',
        }

        # Métricas e relatórios operacionais permanecem no main
        if 'resuma a saúde operacional' in normalized_command or 'resuma a saude operacional' in normalized_command or 'métricas das últimas 24h' in normalized_command or 'metricas das ultimas 24h' in normalized_command:
            metrics = OperationLogger.summarize_metrics(hours=24)
            return STOAQuantumBrain._format_health_metrics(metrics), {
                'operation': 'summarize_health_metrics',
                'metrics': metrics,
            }

        if 'quantas operações falharam hoje' in normalized_command or 'quantas operacoes falharam hoje' in normalized_command:
            counts = OperationLogger.count_by_final_status(hours=24)
            failed = counts.get('failed', 0)
            return f'Operações com status final failed nas últimas 24h: {failed}', {
                'operation': 'count_failed_operations',
                'hours': 24,
                'failed': failed,
                'counts': counts,
            }

        if 'quantos rollbacks ocorreram hoje' in normalized_command or 'quantos rollbacks ocorreram' in normalized_command:
            counts = OperationLogger.count_by_event_type(hours=24)
            rollbacks = counts.get('rollback_executed', 0)
            return f'Rollbacks executados nas últimas 24h: {rollbacks}', {
                'operation': 'count_rollbacks',
                'hours': 24,
                'rollbacks': rollbacks,
                'counts': counts,
            }

        if 'quantos previews expiraram' in normalized_command:
            counts = OperationLogger.count_by_event_type(hours=24)
            expired = counts.get('preview_expired', 0)
            return f'Previews expirados nas últimas 24h: {expired}', {
                'operation': 'count_preview_expired',
                'hours': 24,
                'expired': expired,
                'counts': counts,
            }

        if 'quais arquivos mais mudaram' in normalized_command:
            ranking = OperationLogger.most_changed_files(hours=24, limit=10)
            return STOAQuantumBrain._format_changed_files_ranking(ranking, 'Arquivos que mais mudaram nas últimas 24h'), {
                'operation': 'read_most_changed_files',
                'hours': 24,
                'ranking': ranking,
            }

        if 'mostre o funil de preview' in normalized_command:
            funnel = OperationLogger.preview_funnel(hours=24)
            return STOAQuantumBrain._format_preview_funnel(funnel, 24), {
                'operation': 'read_preview_funnel',
                'hours': 24,
                'funnel': funnel,
            }

        if 'resuma as últimas operações' in normalized_command or 'resuma as ultimas operacoes' in normalized_command:
            summary = OperationLogger.summarize_recent(hours=24)
            return STOAQuantumBrain._format_operational_summary(summary, 24), {
                'operation': 'summarize_recent_operations',
                'summary': summary,
            }

        operation_lookup = re.search(r'(op_[A-Za-z0-9]+)', command)
        if operation_lookup and ('resuma a operação' in normalized_command or 'resuma a operacao' in normalized_command or 'status da operação' in normalized_command or 'status da operacao' in normalized_command or 'qual o status da operação' in normalized_command or 'qual o status da operacao' in normalized_command):
            operation_id = operation_lookup.group(1)
            summary = OperationLogger.summarize_operation(operation_id)
            return STOAQuantumBrain._format_operation_summary(summary, operation_id), {
                'operation': 'read_operation_summary',
                'operation_id': operation_id,
                'summary': summary,
            }

        if operation_lookup and ('mostrar operação' in normalized_command or 'mostrar operacao' in normalized_command or 'detalhes da operação' in normalized_command or 'detalhes da operacao' in normalized_command):
            operation_id = operation_lookup.group(1)
            events = OperationLogger.find_by_operation_id(operation_id)
            return STOAQuantumBrain._format_operation_timeline(events, operation_id), {
                'operation': 'read_operation_timeline',
                'operation_id': operation_id,
                'count': len(events),
            }

        history_match = None
        if any(term in normalized_command for term in ['mostrar histórico', 'mostrar historico', 'últimas operações', 'ultimas operacoes', 'mostrar log', 'ultimos eventos', 'últimos eventos']):
            import re as _re
            history_match = _re.search(r'(\d+)', normalized_command)
            limit = int(history_match.group(1)) if history_match else 10
            events = OperationLogger.read_recent(limit=limit)
            return STOAQuantumBrain._format_recent_operations(events), {
                'operation': 'read_recent_operations',
                'count': len(events),
                'log_path': OperationLogger.log_path(),
            }

        if 'qual foi a última operação aplicada' in normalized_command or 'qual foi a ultima operação aplicada' in normalized_command or 'qual foi a ultima operacao aplicada' in normalized_command:
            event = OperationLogger.find_last_event('preview_applied') or OperationLogger.find_last_event('changeset_executed')
            return STOAQuantumBrain._format_single_operation(event, 'Última operação aplicada'), {
                'operation': 'read_last_applied_operation',
                'event': event,
            }

        if 'quais operações falharam' in normalized_command or 'quais operacoes falharam' in normalized_command:
            events = OperationLogger.filter_by_status('error', limit=10)
            return STOAQuantumBrain._format_recent_operations(events), {
                'operation': 'read_failed_operations',
                'count': len(events),
            }

        if 'houve rollback hoje' in normalized_command:
            summary = OperationLogger.summarize_recent(hours=24)
            rollback_event = OperationLogger.find_last_event('rollback_executed') or OperationLogger.find_last_event('rollback_failed')
            if summary.get('rollbacks', 0) > 0:
                message = STOAQuantumBrain._format_single_operation(rollback_event, 'Houve rollback nas últimas 24h')
            else:
                message = 'Não houve rollback nas últimas 24h.'
            return message, {
                'operation': 'read_recent_rollbacks',
                'summary': summary,
                'event': rollback_event,
            }

        if 'mostre os últimos previews' in normalized_command or 'mostre os ultimos previews' in normalized_command:
            events = OperationLogger.filter_by_event_type('preview_created', limit=10)
            return STOAQuantumBrain._format_recent_operations(events), {
                'operation': 'read_recent_previews',
                'count': len(events),
            }

        if 'quais arquivos foram alterados hoje' in normalized_command:
            files = OperationLogger.recent_affected_files(limit=50)
            return STOAQuantumBrain._format_affected_files(files, 'Arquivos alterados recentemente'), {
                'operation': 'read_recent_affected_files',
                'files': files,
            }

        if mode_override == STOAMode.OPS.value:
            return '❌ Esse pedido nao e uma consulta operacional valida. Use historico, operacao, status, metricas, rollbacks, previews expirados, arquivos mais mudaram ou funil de preview.', {
                'operation': 'ops_unknown',
            }

        # Delega operações de preview para a classe Planner
        if preview_mode:
            project_index = ProjectIndexer.build_index()
            response, details = planner.plan_and_preview(command, project_index, self._get_working_context())
            return response, details

        if apply_preview_mode:
            response, details = planner.apply_pending_preview()
            if details.get('operation') == 'apply_preview_change_set':
                # Atualiza progresso do plano se houver
                change_set_result = details.get('change_set', {})
                change_set_result['plan_progress'] = self._handle_plan_progress_after_execution(
                    change_set_result,
                    operation_id=details.get('operation_id'),
                )
                details.update({
                    'updated_plan_steps': change_set_result['plan_progress'].get('updated_plan_steps'),
                    'current_step_index': change_set_result['plan_progress'].get('current_step_index'),
                    'next_step': change_set_result['plan_progress'].get('next_step'),
                    'plan_progress_summary': change_set_result['plan_progress'].get('plan_progress_summary'),
                })
            return response, details

        if cancel_preview_mode:
            response, details = planner.cancel_pending_preview()
            return response, details

        # Delega comandos básicos de execução para a classe Executor
        response, details = Executor.execute_command(command, None, self._get_working_context())
        return response, details

    @staticmethod
    def _format_weather(data: dict) -> str:
        """Formata dados de clima em texto legível"""
        if "error" in data:
            return data["error"]

        return f"""🌤️ Clima em {data.get('location', 'Local')}:

🌡️ Temperatura: {data.get('temperature')}°C
💧 Humidade: {data.get('humidity')}%
🌬️ Vento: {data.get('wind_speed')} km/h
☁️ Condição: {data.get('description', 'N/A')}
📊 Pressão: {data.get('pressure')} hPa
"""

# ==================== APLICAÇÃO FASTAPI ====================
app = FastAPI(
    title="STOA Agent - IA Multimodal",
    description="Sistema completo de IA com reconhecimento de voz e múltiplos agentes",
    version="1.0.0"
)

try:
    if StoaMemory is None:
        raise RuntimeError("stoa_memory indisponível")
    _stoa_memory = StoaMemory(user_id="default")
except Exception as e:
    print(f"[STOA MEMORY] Falha ao inicializar: {e}")
    _stoa_memory = None
try:
    if StoaGuardrail is None:
        raise RuntimeError("stoa_guardrail indisponível")
    _guardrail = StoaGuardrail(enabled=True)
except Exception as e:
    print(f"[GUARDRAIL] Falha ao inicializar: {e}")
    _guardrail = None

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth
from stoa_auth import TokenAuthMiddleware
app.add_middleware(TokenAuthMiddleware)

# Instância global do agente
brain = STOAQuantumBrain()
active_connections = []


async def broadcast_ws_payload(payload: dict) -> None:
    stale_connections = []
    for websocket in list(active_connections):
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:
            stale_connections.append(websocket)
    for websocket in stale_connections:
        if websocket in active_connections:
            active_connections.remove(websocket)


def publish_device_event(event: dict) -> None:
    payload = {
        "type": "device_event",
        "event": event,
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_ws_payload(payload))
    except RuntimeError:
        pass


brain.device_control.event_callback = publish_device_event

# ==================== ROUTERS ====================
from device_routes import make_device_router
from ops_routes import make_ops_router
from planner_main import router as planner_router
from preview_main import router as preview_router
from stoa_changeset_route import router as changeset_router
from preflight_routes import router as preflight_router

app.include_router(make_device_router(brain))
app.include_router(make_ops_router(brain, config))
app.include_router(planner_router)
app.include_router(preview_router)
app.include_router(changeset_router)
app.include_router(preflight_router)

# ==================== ENDPOINTS HTTP ====================
@app.get("/", response_class=HTMLResponse)
async def root():
    """Frontend principal"""
    return FileResponse(str(Path(__file__).with_name("stoa_mobile.html")))


@app.get("/manifest.webmanifest")
async def web_manifest():
    """Manifesto da PWA"""
    return FileResponse(str(Path(__file__).with_name("manifest.webmanifest")), media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    """Service worker da PWA"""
    return FileResponse(str(Path(__file__).with_name("sw.js")), media_type="application/javascript")


@app.get("/icons/{icon_name}")
async def app_icon(icon_name: str):
    """Ícones da PWA"""
    icon_path = Path(__file__).with_name("icons") / icon_name
    if not icon_path.exists():
        raise HTTPException(status_code=404, detail="Ícone não encontrado")
    return FileResponse(str(icon_path), media_type="image/png")


@app.post("/api/voice")
async def transcribe_voice(file: UploadFile = File(...)):
    """Recebe áudio (webm/ogg/mp4) e transcreve com Whisper"""
    try:
        audio_bytes = await file.read()
        suffix = ".webm"
        if file.filename:
            ext = Path(file.filename).suffix.lower()
            if ext in {".ogg", ".mp3", ".mp4", ".wav", ".m4a"}:
                suffix = ext
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as audio_file:
                transcription = OpenAIAdapter.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="pt",
                )
            text = transcription.text.strip()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return {"text": text, "language": "pt-BR"}
    except Exception as e:
        logger.exception("Erro na transcrição de voz")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/command")
async def process_command(command: VoiceCommand):
    """Processa comando via REST API"""
    try:
        response = await brain.process_command(command.text)
        return response
    except Exception as e:
        logger.exception("Erro ao processar comando via /api/command")
        error_text = str(e)
        is_openai_auth_error = "invalid_api_key" in error_text or "Incorrect API key provided" in error_text
        fallback_message = (
            "O backend STOA está sem uma chave OpenAI válida para comandos conversacionais. "
            "Os fluxos locais de preview, aplicar e cancelar continuam disponíveis."
            if is_openai_auth_error
            else "O backend STOA falhou ao processar este comando, mas a interface continua ativa."
        )
        return AgentResponse(
            response=fallback_message,
            action_type="error",
            module="conversation",
            data={
                "mode": "conversation",
                "status": "conversation_fallback",
                "timestamp": datetime.now().isoformat(),
                "details": {
                    "error": error_text,
                    "error_type": "openai_auth" if is_openai_auth_error else "command_error",
                    "working_context_used": False,
                },
            },
        )


@app.post("/api/code-generate")
async def generate_code(request: dict):
    """Endpoint específico para geração de código"""
    prompt = request.get("prompt", "")
    language = request.get("language", "python")

    code_data = await CodeAgent.generate(prompt, language)
    return code_data


@app.post("/api/website-generate")
async def generate_website(request: dict):
    """Endpoint específico para geração de websites"""
    requirements = request.get("requirements", "")
    web_data = await WebAgent.create_website(requirements)
    return web_data


@app.post("/api/schedule")
async def create_schedule(request: dict):
    """Endpoint específico para criar agenda"""
    requirements = request.get("requirements", "")
    schedule_data = await PlanningAgent.create_schedule(requirements)
    return schedule_data


@app.get("/api/memory/recent")
async def memory_recent(limit: int = 20):
    """Retorna as memórias mais recentes (episódicas + semânticas + projeto)"""
    if _stoa_memory is None:
        return {"items": [], "count": 0, "stats": {}, "warning": "Memória vetorial indisponível"}
    try:
        results = []
        for cat in ("episodic", "semantic", "project"):
            col = _stoa_memory.collections.get(cat)
            if col is None or col.count() == 0:
                continue
            k = min(limit, col.count())
            raw = col.get(include=["documents", "metadatas"])
            docs = raw["documents"][:k]
            metas = raw["metadatas"][:k]
            ids = raw["ids"][:k]
            for doc, meta, mem_id in zip(docs, metas, ids):
                results.append({
                    "id": mem_id,
                    "text": doc,
                    "category": cat,
                    "timestamp": meta.get("timestamp"),
                    "meta": meta,
                })
        results.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        return {"items": results[:limit], "count": len(results[:limit]), "stats": _stoa_memory.stats()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/memory/{mem_id}")
async def memory_delete(mem_id: str):
    """Apaga uma memória específica por ID"""
    if _stoa_memory is None:
        raise HTTPException(status_code=503, detail="Memória vetorial indisponível")
    try:
        for cat, col in _stoa_memory.collections.items():
            try:
                col.delete(ids=[mem_id])
            except Exception:
                pass
        return {"deleted": mem_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/memory/save")
async def memory_save(request: dict):
    """Salva uma memória semântica manualmente"""
    if _stoa_memory is None:
        raise HTTPException(status_code=503, detail="Memória vetorial indisponível")
    text = (request.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text é obrigatório")
    category = request.get("category", "semantic")
    mem_id = _stoa_memory.save(text, category=category)
    return {"id": mem_id, "text": text, "category": category}


@app.post("/api/weather")
async def get_weather():
    """Obtém dados de clima"""
    weather_data = await WeatherAgent.get_info(config.LAT, config.LON)
    return weather_data


@app.get("/api/time")
async def get_time():
    """Obtém hora atual"""
    now = datetime.now()
    return {
        "timestamp": now.isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "day": now.strftime("%A"),
        "timezone": "America/Cuiaba"
    }


# ==================== WEBSOCKET ====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = ""):
    """WebSocket para comunicação em tempo real"""
    from stoa_auth import validate_ws_token, _get_configured_token
    ws_token = token or websocket.query_params.get("token", "")
    server_token = _get_configured_token()
    # Rejeita apenas se: servidor tem token configurado E cliente não enviou token válido
    if server_token and not validate_ws_token(ws_token):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    active_connections.append(websocket)

    try:
        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                command = message.get("text", "")

                if not command:
                    await websocket.send_text(json.dumps({"error": "Comando vazio"}))
                    continue

                response = await brain.process_command(command)

                await websocket.send_text(json.dumps({
                    "response": response.response,
                    "module": response.module,
                    "action_type": response.action_type
                }))

            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "JSON inválido"}))
            except Exception as e:
                logger.error(f"Erro no WebSocket: {e}")
                try:
                    await websocket.send_text(json.dumps({"error": str(e)}))
                except Exception:
                    break

    except Exception as e:
        logger.error(f"Conexão WebSocket fechada: {e}")
    finally:
        try:
            active_connections.remove(websocket)
        except ValueError:
            pass

# ==================== FRONTEND ====================
async def get_frontend() -> str:
    """Retorna o frontend HTML/JS completo"""
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STOA Agent - IA Multimodal</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #333;
        }

        .container {
            width: 100%;
            max-width: 900px;
            height: 90vh;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            display: flex;
            flex-direction: column;
            margin: 20px;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 12px 12px 0 0;
            text-align: center;
        }

        .header h1 {
            font-size: 28px;
            margin-bottom: 5px;
        }

        .header p {
            font-size: 14px;
            opacity: 0.9;
        }

        .status {
            display: flex;
            gap: 10px;
            justify-content: center;
            margin-top: 10px;
            flex-wrap: wrap;
        }

        .badge {
            background: rgba(255,255,255,0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
        }

        .chat-area {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            border-bottom: 1px solid #eee;
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        .message {
            display: flex;
            gap: 10px;
            animation: slideIn 0.3s ease;
        }

        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .message.user {
            justify-content: flex-end;
        }

        .message.assistant {
            justify-content: flex-start;
        }

        .bubble {
            max-width: 70%;
            padding: 12px 16px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.5;
            word-wrap: break-word;
            white-space: pre-wrap;
        }

        .message.user .bubble {
            background: #667eea;
            color: white;
        }

        .message.assistant .bubble {
            background: #f0f0f0;
            color: #333;
        }

        .loading {
            display: flex;
            gap: 5px;
        }

        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #667eea;
            animation: bounce 1.4s infinite;
        }

        .dot:nth-child(2) { animation-delay: 0.2s; }
        .dot:nth-child(3) { animation-delay: 0.4s; }

        @keyframes bounce {
            0%, 100% { opacity: 0.3; }
            50% { opacity: 1; }
        }

        .input-section {
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .voice-section {
            display: flex;
            gap: 10px;
        }

        button {
            padding: 12px 16px;
            border: 1px solid #ddd;
            border-radius: 8px;
            background: white;
            color: #333;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.2s;
        }

        button:hover {
            background: #f0f0f0;
            border-color: #667eea;
        }

        #voiceBtn {
            flex: 1;
            background: #667eea;
            color: white;
            border-color: #667eea;
        }

        #voiceBtn.recording {
            background: #e74c3c;
            border-color: #e74c3c;
            animation: pulse 1s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        .input-row {
            display: flex;
            gap: 10px;
        }

        input {
            flex: 1;
            padding: 12px 16px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
        }

        input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        #sendBtn {
            background: #667eea;
            color: white;
            border-color: #667eea;
            padding: 12px 24px;
        }

        .capabilities {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
            gap: 10px;
            margin-bottom: 10px;
        }

        .capability {
            padding: 10px;
            background: #f9f9f9;
            border: 1px solid #eee;
            border-radius: 6px;
            text-align: center;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .capability:hover {
            background: #667eea;
            color: white;
            border-color: #667eea;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 STOA Agent</h1>
            <p>IA Multimodal com Reconhecimento de Voz</p>
            <div class="status">
                <span class="badge">✓ Voz</span>
                <span class="badge">✓ Código</span>
                <span class="badge">✓ Web</span>
                <span class="badge">✓ Clima</span>
                <span class="badge">✓ Planejamento</span>
            </div>
        </div>

        <div class="chat-area" id="chatArea"></div>

        <div class="input-section">
            <div class="capabilities" id="capabilities"></div>

            <div class="voice-section">
                <button id="voiceBtn">🎤 Ativar Voz</button>
            </div>

            <div class="input-row">
                <input 
                    type="text" 
                    id="textInput" 
                    placeholder="Digite seu comando aqui..."
                    onkeypress="if(event.key === 'Enter') sendMessage()"
                >
                <button id="sendBtn" onclick="sendMessage()">Enviar</button>
            </div>
        </div>
    </div>

    <script>
        const chatArea = document.getElementById('chatArea');
        const textInput = document.getElementById('textInput');
        const voiceBtn = document.getElementById('voiceBtn');

        let ws = null;
        let isRecording = false;
        let recognition = null;

        // Inicializa WebSocket
        function initWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(protocol + '//' + window.location.host + '/ws');

            ws.onopen = () => console.log('WebSocket conectado');
            ws.onmessage = (event) => handleWebSocketMessage(event.data);
            ws.onerror = (error) => console.error('Erro WebSocket:', error);
            ws.onclose = () => setTimeout(initWebSocket, 3000);
        }

        function handleWebSocketMessage(data) {
            try {
                const msg = JSON.parse(data);
                if (msg.error) {
                    addMessage('❌ ' + msg.error, 'assistant');
                } else {
                    addMessage(msg.response, 'assistant');
                }
            } catch (e) {
                console.error('Erro ao parsear WebSocket:', e);
            }
        }

        // Reconhecimento de voz
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            recognition = new SpeechRecognition();
            recognition.lang = 'pt-BR';
            recognition.continuous = false;

            recognition.onstart = () => {
                isRecording = true;
                voiceBtn.classList.add('recording');
                voiceBtn.textContent = '🎙️ Ouvindo...';
            };

            recognition.onresult = (event) => {
                let transcript = '';
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    transcript += event.results[i][0].transcript;
                }
                if (transcript) {
                    textInput.value = transcript;
                    sendMessage();
                }
            };

            recognition.onend = () => {
                isRecording = false;
                voiceBtn.classList.remove('recording');
                voiceBtn.textContent = '🎤 Ativar Voz';
            };
        }

        voiceBtn.onclick = () => {
            if (!recognition) {
                addMessage('Voz não suportada neste navegador', 'assistant');
                return;
            }
            if (isRecording) {
                recognition.stop();
            } else {
                recognition.start();
            }
        };

        function addMessage(text, role) {
            const msg = document.createElement('div');
            msg.className = 'message ' + role;
            msg.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
            chatArea.appendChild(msg);
            chatArea.scrollTop = chatArea.scrollHeight;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function sendMessage() {
            const text = textInput.value.trim();
            if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

            addMessage(text, 'user');
            textInput.value = '';

            // Mostra loading
            const loadingMsg = document.createElement('div');
            loadingMsg.className = 'message assistant';
            loadingMsg.innerHTML = `<div class="bubble"><div class="loading"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div></div>`;
            chatArea.appendChild(loadingMsg);
            chatArea.scrollTop = chatArea.scrollHeight;

            setTimeout(() => {
                ws.send(JSON.stringify({ text: text }));
                loadingMsg.remove();
            }, 300);
        }

        // Carrega capabilidades
        const capabilities = [
            { icon: '🌤️', text: 'Clima & Hora' },
            { icon: '📅', text: 'Planejamento' },
            { icon: '💻', text: 'Codificação' },
            { icon: '🌐', text: 'Web Design' },
            { icon: '📚', text: 'Educação' },
            { icon: '🚀', text: 'Estratégia' }
        ];

        document.getElementById('capabilities').innerHTML = capabilities
            .map(c => `<div class="capability" onclick="textInput.value='${c.text}'; sendMessage()">${c.icon} ${c.text}</div>`)
            .join('');

        // Boas-vindas
        addMessage('Olá! 👋 Sou STOA Agent. Use o reconhecimento de voz ou digite seus comandos.', 'assistant');

        // Inicializa WebSocket
        initWebSocket();
    </script>
</body>
</html>"""

# ==================== EXECUÇÃO ====================
if __name__ == "__main__":
    runtime_port = resolve_runtime_port(config.HOST, config.PORT)
    reload_enabled = config.RELOAD and os.name != "nt"

    if config.RELOAD and os.name == "nt":
        logger.warning("⚠️ RELOAD=True foi ignorado no Windows para evitar conflito de bind/socket.")

    logger.info(f"🚀 Iniciando STOA Agent em {config.HOST}:{runtime_port}")
    logger.info(f"📍 Localização: {config.LOCATION}")
    logger.info(f"🔧 Debug: {config.DEBUG}")
    logger.info(f"🔁 Reload ativo: {reload_enabled}")

    ssl_certfile = os.getenv("STOA_SSL_CERTFILE")
    ssl_keyfile = os.getenv("STOA_SSL_KEYFILE")

    uvicorn_kwargs = {
        "host": config.HOST,
        "port": runtime_port,
        "reload": reload_enabled,
        "log_level": "info",
    }

    if ssl_certfile and ssl_keyfile:
        logger.info(f"🔒 HTTPS ativo com certificado: {ssl_certfile}")
        uvicorn_kwargs["ssl_certfile"] = ssl_certfile
        uvicorn_kwargs["ssl_keyfile"] = ssl_keyfile
    else:
        logger.warning("⚠️ Chrome Android só reconhece installability real de PWA em origem segura. Em http://IP da rede local ele tende a mostrar apenas 'Adicionar à tela inicial'.")

    uvicorn.run(
        "main:app",
        **uvicorn_kwargs,
    )

