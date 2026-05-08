import logging
import os
import re
import secrets
import json
import csv
import subprocess
import time
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4
import asyncio
from urllib.parse import urlparse

import aiohttp
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import anthropic
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import uvicorn


load_dotenv(Path(__file__).resolve().parents[1] / ".env.safe")


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("safe_stoa")

REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_repo_path(env_name: str, default_path: Path) -> Path:
    raw_value = os.getenv(env_name, str(default_path))
    resolved = Path(raw_value)
    if resolved.is_absolute():
        return resolved
    return REPO_ROOT / resolved


class Config:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
    OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
    ACCESS_TOKEN = os.getenv("STOA_ACCESS_TOKEN", "").strip()
    PORT = int(os.getenv("PORT", "8000"))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    LOCATION = os.getenv("LOCATION", "Chapada dos Guimarães, Mato Grosso, BR")
    LAT = float(os.getenv("LAT", "-15.4667"))
    LON = float(os.getenv("LON", "-55.7500"))
    HOST = os.getenv("BIND_HOST", "0.0.0.0")
    ALLOWED_HOSTS = [
        host.strip()
        for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
        if host.strip()
    ]
    MODEL_ROUTER = os.getenv("ANTHROPIC_ROUTER_MODEL", "claude-haiku-4-5-20251001")
    MODEL_DEFAULT = os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
    MODEL_PLANNER = os.getenv("ANTHROPIC_PLANNER_MODEL", "claude-sonnet-4-6")
    MODEL_SYNTHESIS = os.getenv("ANTHROPIC_SYNTHESIS_MODEL", "claude-sonnet-4-6")
    MODEL_AUTOPILOT = os.getenv("ANTHROPIC_AUTOPILOT_MODEL", "claude-sonnet-4-6")
    MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "4000"))
    MAX_PLAN_STEPS = int(os.getenv("MAX_PLAN_STEPS", "4"))
    MAX_STEP_OUTPUT_CHARS = int(os.getenv("MAX_STEP_OUTPUT_CHARS", "1200"))
    MAX_SESSION_MESSAGES = int(os.getenv("MAX_SESSION_MESSAGES", "12"))
    AUTOPILOT_MAX_FILES = int(os.getenv("AUTOPILOT_MAX_FILES", "8"))
    QUEUE_WORKER_INTERVAL_SECONDS = int(os.getenv("QUEUE_WORKER_INTERVAL_SECONDS", "10"))
    PROJECT_SUPERVISOR_INTERVAL_SECONDS = int(os.getenv("PROJECT_SUPERVISOR_INTERVAL_SECONDS", "45"))
    PROJECT_SUPERVISOR_ENABLED = os.getenv("PROJECT_SUPERVISOR_ENABLED", "true").lower() == "true"
    DAILY_BRIEFING_INTERVAL_SECONDS = int(os.getenv("DAILY_BRIEFING_INTERVAL_SECONDS", "300"))
    DAILY_BRIEFING_ENABLED = os.getenv("DAILY_BRIEFING_ENABLED", "true").lower() == "true"
    AUTO_SAVE_ARTIFACTS = os.getenv("AUTO_SAVE_ARTIFACTS", "true").lower() == "true"
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "30"))
    AUDIT_LOG_PATH = resolve_repo_path(
        "AUDIT_LOG_PATH",
        REPO_ROOT / "logs" / "audit.log",
    )
    SESSION_STORE_PATH = resolve_repo_path(
        "SESSION_STORE_PATH",
        REPO_ROOT / "data" / "sessions.json",
    )
    PREVIEW_STORE_PATH = resolve_repo_path(
        "PREVIEW_STORE_PATH",
        REPO_ROOT / "data" / "previews.json",
    )
    COWORKER_STORE_PATH = resolve_repo_path(
        "COWORKER_STORE_PATH",
        REPO_ROOT / "data" / "coworker.json",
    )
    TERMINAL_TIMEOUT_SECONDS = int(os.getenv("TERMINAL_TIMEOUT_SECONDS", "20"))
    ALLOWED_COMMAND_PREFIXES = [
        [part.strip() for part in prefix.split("|") if part.strip()]
        for prefix in os.getenv(
            "ALLOWED_COMMAND_PREFIXES",
            "python|--version;python|-m|pip|list;git|status;git|diff;git|log;dir;Get-ChildItem",
        ).split(";")
        if prefix.strip()
    ]
    ALLOWED_APPS = {
        app.strip().lower()
        for app in os.getenv("ALLOWED_APPS", "notepad,code,cursor,excel").split(",")
        if app.strip()
    }
    ALLOWED_BROWSERS = {
        app.strip().lower()
        for app in os.getenv("ALLOWED_BROWSERS", "msedge,chrome,firefox").split(",")
        if app.strip()
    }
    ALLOWED_BROWSER_DOMAINS = {
        domain.strip().lower()
        for domain in os.getenv("ALLOWED_BROWSER_DOMAINS", "localhost,127.0.0.1").split(",")
        if domain.strip()
    }
    EXTERNAL_ALLOWED_ROOTS = {
        alias.strip(): Path(path.strip())
        for entry in os.getenv("EXTERNAL_ALLOWED_ROOTS", "").split(";")
        if entry.strip() and "=" in entry
        for alias, path in [entry.split("=", 1)]
        if alias.strip() and path.strip()
    }
    WORKSPACE_ROOT = resolve_repo_path(
        "WORKSPACE_ROOT",
        REPO_ROOT / "workspace",
    )
    AVATAR_REFERENCE_PATH = resolve_repo_path(
        "STOA_AVATAR_REFERENCE_PATH",
        REPO_ROOT / "static" / "pwa-icons" / "icon-any.svg",
    )
    REMOTE_HTML_PATH = resolve_repo_path(
        "STOA_REMOTE_HTML_PATH",
        REPO_ROOT / "stoa_remote.html",
    )
    ALIVE_HTML_PATH = resolve_repo_path(
        "STOA_ALIVE_HTML_PATH",
        REPO_ROOT / "stoa_alive.html",
    )
    EDITABLE_EXTENSIONS = {
        ext.strip().lower()
        for ext in os.getenv(
            "EDITABLE_EXTENSIONS",
            ".md,.txt,.html,.css,.js,.json,.py",
        ).split(",")
        if ext.strip()
    }
    ENABLED_MODULES = {
        module.strip()
        for module in os.getenv(
            "ENABLED_MODULES", "weather,time,planning,web,education,strategy,code,info"
        ).split(",")
        if module.strip()
    }


config = Config()

if not config.ACCESS_TOKEN:
    raise ValueError("STOA_ACCESS_TOKEN não configurado.")

client: Optional[anthropic.Anthropic] = None
session_store: dict[str, list[dict]] = {}
preview_store: dict[str, dict] = {}
coworker_store: dict[str, dict[str, list[dict]]] = {}
rate_limit_store: dict[str, list[float]] = {}
websocket_connections: list[dict] = []
preview_locks: dict[str, asyncio.Lock] = {}


class VoiceCommand(BaseModel):
    text: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)
    language: str = "pt-BR"
    session_id: Optional[str] = None
    mode: str = "builder"


class AgentResponse(BaseModel):
    response: str
    action_type: str
    module: str
    session_id: Optional[str] = None
    data: Optional[dict] = None
    artifact_path: Optional[str] = None


class PendingPreview(BaseModel):
    id: str
    session_id: str
    original_text: str
    prompt: str
    module: str
    mode: str
    status: str = "pending"
    created_at: str


class SuperTaskStep(BaseModel):
    module: str
    prompt: str
    goal: str
    output_file: Optional[str] = None


class SuperTaskPlan(BaseModel):
    mode: str
    objective: str
    steps: list[SuperTaskStep]
    final_files: list[str] = []


class SuperTaskResult(BaseModel):
    objective: str
    session_id: str
    plan: list[dict]
    steps: list[dict]
    final_response: str
    artifact_paths: list[str]


class FileWriteRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1, max_length=240)
    content: str
    overwrite: bool = True


class FileEditInstructionRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1, max_length=240)
    instruction: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)
    overwrite: bool = True


class FileReadRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1, max_length=240)


class FileReviewInstructionRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1, max_length=240)
    instruction: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)


class ProjectReadRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_paths: list[str] = Field(min_length=1, max_length=20)
    instruction: Optional[str] = None


class ProjectPatchStep(BaseModel):
    relative_path: str
    instruction: str


class ProjectPatchRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_paths: list[str] = Field(min_length=1, max_length=20)
    instruction: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)
    overwrite: bool = True


class ProjectPatchPlan(BaseModel):
    objective: str
    steps: list[ProjectPatchStep]


class AutopilotDecision(BaseModel):
    mode: str
    objective: str
    relative_paths: list[str] = []
    prompt: Optional[str] = None
    instruction: Optional[str] = None


class AutopilotResult(BaseModel):
    session_id: str
    mode: str
    objective: str
    result: dict


class OrchestratorDecision(BaseModel):
    action: str
    objective: str
    app: Optional[str] = None
    relative_path: Optional[str] = None
    workspace_relative_path: Optional[str] = None
    command: Optional[str] = None
    rows: list[list[str]] = []
    sheets: list[dict] = []
    prompt: Optional[str] = None


class OrchestratorRequest(BaseModel):
    session_id: Optional[str] = None
    mode: str = "builder"
    text: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)


class OrchestratorResult(BaseModel):
    session_id: str
    action: str
    objective: str
    result: dict


class QueueTaskRequest(BaseModel):
    session_id: Optional[str] = None
    mode: str = "builder"
    text: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)


class CoworkerProjectRequest(BaseModel):
    session_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    root_alias: str = "session"
    relative_path: Optional[str] = Field(default=None, max_length=240)


class CoworkerProjectMemoryRequest(BaseModel):
    session_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    preferences: list[str] = Field(default_factory=list, max_length=20)
    decisions: list[str] = Field(default_factory=list, max_length=20)
    facts: list[str] = Field(default_factory=list, max_length=30)
    working_style: Optional[str] = Field(default=None, max_length=1000)
    replace: bool = False


class CoworkerProjectStatusRequest(BaseModel):
    session_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    phase: Optional[str] = Field(default=None, max_length=120)
    health: Optional[str] = Field(default=None, max_length=40)
    next_action: Optional[str] = Field(default=None, max_length=1000)
    blockers: list[str] = Field(default_factory=list, max_length=15)
    risks: list[str] = Field(default_factory=list, max_length=15)
    replace: bool = False


class InboxItemUpdateRequest(BaseModel):
    session_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    status: str = Field(min_length=1, max_length=20)


class InboxItemExecuteRequest(BaseModel):
    session_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)


class SystemActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=80)


class CoworkerProfileRequest(BaseModel):
    session_id: str = Field(min_length=1)
    name: str = Field(default="Claude Coworker", max_length=120)
    role: str = Field(default="Senior AI coworker", max_length=160)
    mission: str = Field(default="Transformar pedidos em trabalho executável e entregáveis reais.", max_length=1000)
    decision_rules: list[str] = Field(default_factory=list, max_length=20)
    strengths: list[str] = Field(default_factory=list, max_length=20)
    default_mode: str = "builder"
    communication_style: str = Field(default="Direto, pragmático e focado em execução.", max_length=500)
    replace: bool = False


class CoworkerPersonaRequest(BaseModel):
    session_id: str = Field(min_length=1)
    domain: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=160)
    mission: str = Field(min_length=1, max_length=1000)
    decision_rules: list[str] = Field(default_factory=list, max_length=20)
    strengths: list[str] = Field(default_factory=list, max_length=20)
    default_mode: str = "builder"
    communication_style: str = Field(default="Direto, pragmático e focado em execução.", max_length=500)


class CoworkerTaskRequest(BaseModel):
    session_id: Optional[str] = None
    text: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)
    mode: str = "builder"
    priority: str = "medium"
    project_id: Optional[str] = None
    task_type: str = "deliverable"


class CoworkerTaskUpdateRequest(BaseModel):
    session_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class CoworkerRoutineRequest(BaseModel):
    session_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)
    mode: str = "operator"
    priority: str = "medium"
    project_id: Optional[str] = None
    trigger: str = "manual"
    enabled: bool = True


class CoworkerIntakeRequest(BaseModel):
    session_id: Optional[str] = None
    text: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)
    mode: str = "builder"


class CoworkerObjectiveRequest(BaseModel):
    session_id: Optional[str] = None
    objective: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)
    mode: str = "builder"
    priority: str = "high"
    project_id: Optional[str] = None


class CoworkerObjectivePlanRequest(BaseModel):
    session_id: str = Field(min_length=1)
    objective_id: str = Field(min_length=1)
    replace_pending: bool = False


task_queue_store: dict[str, list[dict]] = {}
queue_worker_enabled = False
project_supervisor_enabled = config.PROJECT_SUPERVISOR_ENABLED
project_supervisor_last_run: dict[str, str] = {}
daily_briefing_enabled = config.DAILY_BRIEFING_ENABLED
daily_briefing_last_run: dict[str, str] = {}


class TerminalCommandRequest(BaseModel):
    session_id: str = Field(min_length=1)
    command: str = Field(min_length=1, max_length=400)
    cwd: Optional[str] = None


class AppLaunchRequest(BaseModel):
    session_id: str = Field(min_length=1)
    app: str = Field(min_length=1, max_length=50)
    args: list[str] = Field(default_factory=list, max_length=10)


class WorkspaceOpenRequest(BaseModel):
    session_id: str = Field(min_length=1)
    app: str = Field(min_length=1, max_length=20)
    relative_path: str = Field(min_length=1, max_length=240)
    root_alias: str = "session"


class SpreadsheetCreateRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1, max_length=240)
    rows: list[list[str]] = Field(min_length=1, max_length=500)
    open_in_excel: bool = False
    root_alias: str = "session"


class ExcelSheetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=31)
    rows: list[list[str]] = Field(min_length=1, max_length=500)


class ExcelWorkbookRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1, max_length=240)
    sheets: list[ExcelSheetRequest] = Field(min_length=1, max_length=10)
    open_in_excel: bool = False
    root_alias: str = "session"


class ExcelCellUpdateRequest(BaseModel):
    session_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1, max_length=240)
    sheet_name: str = Field(min_length=1, max_length=31)
    cell: str = Field(min_length=1, max_length=20)
    value: str = Field(max_length=500)
    open_in_excel: bool = False
    root_alias: str = "session"


class EditorOpenFileRequest(BaseModel):
    session_id: str = Field(min_length=1)
    app: str = Field(min_length=1, max_length=20)
    relative_path: str = Field(min_length=1, max_length=240)
    root_alias: str = "session"


class EditorTaskRequest(BaseModel):
    session_id: str = Field(min_length=1)
    app: str = Field(min_length=1, max_length=20)
    workspace_relative_path: str = Field(min_length=1, max_length=240)
    task: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)
    root_alias: str = "session"


class BrowserOpenUrlRequest(BaseModel):
    session_id: str = Field(min_length=1)
    browser: str = Field(min_length=1, max_length=20)
    url: str = Field(min_length=1, max_length=500)


class BrowserTaskRequest(BaseModel):
    session_id: str = Field(min_length=1)
    browser: str = Field(min_length=1, max_length=20)
    url: str = Field(min_length=1, max_length=500)
    task: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)


class BrowserExecutionPlanRequest(BaseModel):
    session_id: str = Field(min_length=1)
    url: str = Field(min_length=1, max_length=500)
    task: str = Field(min_length=1, max_length=config.MAX_PROMPT_CHARS)


def require_bearer_token(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {config.ACCESS_TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Token inválido.")


def ensure_audit_log_parent() -> None:
    config.AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def audit_log(event_type: str, request: Optional[Request], details: dict) -> None:
    ensure_audit_log_parent()
    payload = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "client_ip": request.client.host if request and request.client else None,
        "details": details,
    }
    with config.AUDIT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def ensure_session_store_parent() -> None:
    config.SESSION_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def ensure_preview_store_parent() -> None:
    config.PREVIEW_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_session_store() -> None:
    global session_store
    ensure_session_store_parent()
    if not config.SESSION_STORE_PATH.exists():
        session_store = {}
        return

    try:
        raw = json.loads(config.SESSION_STORE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            normalized: dict[str, list[dict]] = {}
            for session_id, messages in raw.items():
                if isinstance(session_id, str) and isinstance(messages, list):
                    normalized[session_id] = messages[-config.MAX_SESSION_MESSAGES :]
            session_store = normalized
        else:
            session_store = {}
    except Exception as exc:
        logger.warning("Falha ao carregar sessions.json: %s", exc)
        session_store = {}


def persist_session_store() -> None:
    ensure_session_store_parent()
    config.SESSION_STORE_PATH.write_text(
        json.dumps(session_store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_preview_store() -> None:
    global preview_store
    ensure_preview_store_parent()
    if not config.PREVIEW_STORE_PATH.exists():
        preview_store = {}
        return

    try:
        raw = json.loads(config.PREVIEW_STORE_PATH.read_text(encoding="utf-8"))
        normalized: dict[str, dict] = {}
        if isinstance(raw, dict):
            for session_id, preview in raw.items():
                if isinstance(session_id, str) and isinstance(preview, dict):
                    try:
                        # session_id pode já estar no dict (de model_dump); garante
                        # que o valor correto da chave do store prevalece.
                        normalized[session_id] = PendingPreview(
                            **{**preview, "session_id": session_id}
                        ).model_dump()
                    except Exception:
                        continue
        preview_store = normalized
    except Exception as exc:
        logger.warning("Falha ao carregar previews.json: %s", exc)
        preview_store = {}


def persist_preview_store() -> None:
    ensure_preview_store_parent()
    config.PREVIEW_STORE_PATH.write_text(
        json.dumps(preview_store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def empty_coworker_store() -> dict[str, dict[str, list[dict]]]:
    return {"projects": {}, "tasks": {}, "routines": {}, "actions": {}, "decisions": {}}


def ensure_coworker_store_parent() -> None:
    config.COWORKER_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_coworker_store() -> None:
    global coworker_store
    ensure_coworker_store_parent()
    if not config.COWORKER_STORE_PATH.exists():
        coworker_store = empty_coworker_store()
        return

    try:
        raw = json.loads(config.COWORKER_STORE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            base = empty_coworker_store()
            for key in base:
                value = raw.get(key, {})
                base[key] = value if isinstance(value, dict) else {}
            coworker_store = base
        else:
            coworker_store = empty_coworker_store()
    except Exception as exc:
        logger.warning("Falha ao carregar coworker.json: %s", exc)
        coworker_store = empty_coworker_store()


def persist_coworker_store() -> None:
    ensure_coworker_store_parent()
    config.COWORKER_STORE_PATH.write_text(
        json.dumps(coworker_store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_preview_lock(session_id: str) -> asyncio.Lock:
    lock = preview_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        preview_locks[session_id] = lock
    return lock


def classify_preview_control(text: str) -> Optional[str]:
    normalized = (text or "").strip().lower()
    if normalized in {"apply", "aplicar", "confirmar", "executar", "ok"}:
        return "apply"
    if normalized in {"cancel", "cancelar", "descartar", "abortar", "nao", "não"}:
        return "cancel"
    return None


def get_pending_preview(session_id: str) -> Optional[PendingPreview]:
    stored = preview_store.get(session_id)
    if not stored:
        return None
    try:
        return PendingPreview(**stored)
    except Exception:
        preview_store.pop(session_id, None)
        persist_preview_store()
        return None


def save_pending_preview(preview: PendingPreview) -> None:
    preview_store[preview.session_id] = preview.model_dump()
    persist_preview_store()


def clear_pending_preview(session_id: str) -> Optional[PendingPreview]:
    preview = get_pending_preview(session_id)
    if session_id in preview_store:
        preview_store.pop(session_id, None)
        persist_preview_store()
    return preview


def preview_public_payload(preview: PendingPreview) -> dict:
    return {
        "id": preview.id,
        "session_id": preview.session_id,
        "original_text": preview.original_text,
        "prompt": preview.prompt,
        "module": preview.module,
        "mode": preview.mode,
        "status": preview.status,
        "created_at": preview.created_at,
    }


def append_timeline_event(session_id: str, event_type: str, details: dict) -> None:
    append_session_message(
        session_id,
        "system",
        json.dumps(
            {
                "event_type": event_type,
                "timestamp": datetime.now().isoformat(),
                "details": details,
            },
            ensure_ascii=False,
        ),
    )


def build_command_preview(command: VoiceCommand, session_id: str) -> PendingPreview:
    prompt = f"{mode_preamble(command.mode)}\n\nPedido:\n{command.text}"
    module = route_command(prompt)
    return PendingPreview(
        id=str(uuid4()),
        session_id=session_id,
        original_text=command.text,
        prompt=prompt,
        module=module,
        mode=command.mode,
        created_at=datetime.now().isoformat(),
    )


def get_coworker_bucket(kind: str, session_id: str) -> list[dict]:
    return coworker_store.setdefault(kind, {}).setdefault(session_id, [])


def default_coworker_profile() -> dict:
    return {
        "name": "Claude Coworker",
        "role": "Senior AI coworker",
        "mission": "Transformar pedidos em trabalho executável, entregar artefatos úteis e manter contexto operacional.",
        "decision_rules": [
            "Priorizar entregáveis concretos antes de análise longa.",
            "Quebrar objetivos grandes em etapas curtas e verificáveis.",
            "Reutilizar contexto e memória do projeto antes de replanejar.",
            "Elevar prioridade de itens bloqueadores para o trabalho seguinte.",
        ],
        "strengths": [
            "planejamento prático",
            "execução em projeto",
            "revisão operacional",
            "organização de backlog",
        ],
        "default_mode": "builder",
        "communication_style": "Direto, pragmático e focado em execução.",
        "personas": {
            "business": {
                "label": "Business Operator",
                "role": "AI coworker para negócio e posicionamento",
                "mission": "Traduzir objetivos de negócio em entregáveis comerciais claros.",
                "decision_rules": [
                    "Priorizar clareza comercial e valor percebido.",
                    "Conectar entregas a objetivo de negócio e conversão.",
                ],
                "strengths": ["posicionamento", "oferta", "mensagem", "priorização comercial"],
                "default_mode": "builder",
                "communication_style": "Executivo, direto e focado em valor.",
            },
            "product": {
                "label": "Product Planner",
                "role": "AI coworker para produto e experiência",
                "mission": "Transformar ideias em escopo enxuto, fluxo de uso e roadmap executável.",
                "decision_rules": [
                    "Quebrar produto em incrementos pequenos e testáveis.",
                    "Priorizar experiência central antes de expansão de escopo.",
                ],
                "strengths": ["roadmap", "escopo", "UX funcional", "sequenciamento"],
                "default_mode": "builder",
                "communication_style": "Prático e orientado a entrega incremental.",
            },
            "code": {
                "label": "Technical Builder",
                "role": "AI coworker para código e implementação",
                "mission": "Entregar estrutura técnica utilizável com mínimo atrito operacional.",
                "decision_rules": [
                    "Preferir estrutura simples e funcional antes de abstrações.",
                    "Corrigir bloqueadores técnicos antes de refinamentos.",
                ],
                "strengths": ["implementação", "refatoração", "integração", "estrutura de projeto"],
                "default_mode": "builder",
                "communication_style": "Técnico, enxuto e objetivo.",
            },
            "operations": {
                "label": "Operations Supervisor",
                "role": "AI coworker para operação e organização",
                "mission": "Manter trabalho organizado, rastreável e executável sem desperdício.",
                "decision_rules": [
                    "Eliminar ambiguidade operacional antes de executar.",
                    "Promover visibilidade de pendências, risco e próxima ação.",
                ],
                "strengths": ["organização", "backlog", "rotina", "acompanhamento"],
                "default_mode": "operator",
                "communication_style": "Operacional, claro e disciplinado.",
            },
            "finance": {
                "label": "Finance Assistant",
                "role": "AI coworker para fluxo financeiro e controle",
                "mission": "Estruturar informação financeira de forma simples, rastreável e útil para decisão.",
                "decision_rules": [
                    "Preferir estrutura de controle clara antes de análises sofisticadas.",
                    "Separar resumo executivo de lançamentos operacionais.",
                ],
                "strengths": ["planilhas", "fluxo de caixa", "organização financeira", "visão resumida"],
                "default_mode": "builder",
                "communication_style": "Objetivo e orientado a controle.",
            },
        },
        "updated_at": datetime.now().isoformat(),
    }


def normalize_priority(priority: Optional[str]) -> str:
    value = (priority or "medium").strip().lower()
    if value in {"critical", "high", "medium", "low"}:
        return value
    return "medium"


def normalize_task_status(status: Optional[str]) -> str:
    value = (status or "pending").strip().lower()
    if value in {"pending", "running", "blocked", "completed", "failed", "cancelled"}:
        return value
    return "pending"


def priority_weight(priority: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(normalize_priority(priority), 2)


def create_coworker_project(
    session_id: str,
    name: str,
    summary: str,
    root_alias: str = "session",
    relative_path: Optional[str] = None,
) -> dict:
    project = {
        "id": str(uuid4()),
        "name": name.strip(),
        "summary": summary.strip(),
        "root_alias": root_alias,
        "relative_path": relative_path,
        "phase": "discovery",
        "health": "green",
        "next_action": "",
        "blockers": [],
        "risks": [],
        "preferences": [],
        "decisions": [],
        "facts": [],
        "working_style": "",
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "last_activity_at": datetime.now().isoformat(),
    }
    get_coworker_bucket("projects", session_id).append(project)
    persist_coworker_store()
    return project


def create_coworker_objective(
    session_id: str,
    objective: str,
    mode: str = "builder",
    priority: str = "high",
    project_id: Optional[str] = None,
    domain: Optional[str] = None,
) -> dict:
    item = {
        "id": str(uuid4()),
        "objective": objective.strip(),
        "mode": mode,
        "priority": normalize_priority(priority),
        "project_id": project_id,
        "domain": domain,
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "planned_at": None,
        "last_progress_at": None,
        "plan": [],
    }
    get_coworker_bucket("objectives", session_id).append(item)
    persist_coworker_store()
    return item


def list_coworker_objectives(session_id: str) -> list[dict]:
    return sorted(
        get_coworker_bucket("objectives", session_id),
        key=lambda item: (
            item.get("status") != "active",
            priority_weight(item.get("priority", "high")),
            item.get("created_at", ""),
        ),
    )


def get_coworker_objective(session_id: str, objective_id: str) -> Optional[dict]:
    for item in get_coworker_bucket("objectives", session_id):
        if item["id"] == objective_id:
            return item
    return None


def create_coworker_task(
    session_id: str,
    text: str,
    mode: str = "builder",
    priority: str = "medium",
    project_id: Optional[str] = None,
    task_type: str = "deliverable",
    source: str = "manual",
    objective_id: Optional[str] = None,
) -> dict:
    task = {
        "id": str(uuid4()),
        "text": text.strip(),
        "mode": mode,
        "priority": normalize_priority(priority),
        "project_id": project_id,
        "objective_id": objective_id,
        "task_type": task_type,
        "source": source,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
        "notes": None,
    }
    get_coworker_bucket("tasks", session_id).append(task)
    persist_coworker_store()
    return task


def list_coworker_projects(session_id: str) -> list[dict]:
    return get_coworker_bucket("projects", session_id)


def get_coworker_profile(session_id: str) -> dict:
    bucket = get_coworker_bucket("profiles", session_id)
    if not bucket:
        profile = default_coworker_profile()
        bucket.append(profile)
        persist_coworker_store()
        return profile
    profile = bucket[0]
    merged = default_coworker_profile()
    merged.update(profile)
    bucket[0] = merged
    persist_coworker_store()
    return merged


def update_coworker_profile(
    session_id: str,
    name: str,
    role: str,
    mission: str,
    decision_rules: list[str],
    strengths: list[str],
    default_mode: str,
    communication_style: str,
    replace: bool = False,
) -> dict:
    profile = get_coworker_profile(session_id)
    if replace:
        profile.update(default_coworker_profile())

    profile["name"] = (name or profile["name"]).strip()
    profile["role"] = (role or profile["role"]).strip()
    profile["mission"] = (mission or profile["mission"]).strip()
    profile["decision_rules"] = merge_unique_text(
        [] if replace else profile.get("decision_rules", []),
        decision_rules,
        20,
    ) or profile.get("decision_rules", [])
    profile["strengths"] = merge_unique_text(
        [] if replace else profile.get("strengths", []),
        strengths,
        20,
    ) or profile.get("strengths", [])
    profile["default_mode"] = "operator" if str(default_mode).strip().lower() == "operator" else "builder"
    profile["communication_style"] = (communication_style or profile["communication_style"]).strip()
    profile["updated_at"] = datetime.now().isoformat()
    bucket = get_coworker_bucket("profiles", session_id)
    if bucket:
        bucket[0] = profile
    else:
        bucket.append(profile)
    persist_coworker_store()
    return profile


def normalize_domain(domain: str) -> str:
    return slugify(domain).replace("-", "_")[:40] or "general"


def update_coworker_persona(
    session_id: str,
    domain: str,
    label: str,
    role: str,
    mission: str,
    decision_rules: list[str],
    strengths: list[str],
    default_mode: str,
    communication_style: str,
) -> dict:
    profile = get_coworker_profile(session_id)
    personas = profile.setdefault("personas", {})
    key = normalize_domain(domain)
    personas[key] = {
        "label": label.strip(),
        "role": role.strip(),
        "mission": mission.strip(),
        "decision_rules": merge_unique_text([], decision_rules, 20),
        "strengths": merge_unique_text([], strengths, 20),
        "default_mode": "operator" if str(default_mode).strip().lower() == "operator" else "builder",
        "communication_style": communication_style.strip(),
        "updated_at": datetime.now().isoformat(),
    }
    profile["updated_at"] = datetime.now().isoformat()
    bucket = get_coworker_bucket("profiles", session_id)
    if bucket:
        bucket[0] = profile
    else:
        bucket.append(profile)
    persist_coworker_store()
    return {"domain": key, **personas[key]}


def detect_persona_domain(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ["fluxo de caixa", "financeiro", "planilha", "receita", "despesa", "vendas"]):
        return "finance"
    if any(term in lowered for term in ["landing page", "site", "empresa", "comercial", "oferta", "cliente"]):
        return "business"
    if any(term in lowered for term in ["produto", "roadmap", "mvp", "funcionalidade", "ux", "experiência"]):
        return "product"
    if any(term in lowered for term in ["código", "codigo", "fastapi", "python", "app", "api", "frontend", "backend"]):
        return "code"
    if any(term in lowered for term in ["organize", "revisar", "pendência", "pendencia", "rotina", "operação", "operacao"]):
        return "operations"
    return "business"


def resolve_effective_persona(session_id: str, text: str, project_id: Optional[str] = None) -> tuple[str, dict]:
    profile = get_coworker_profile(session_id)
    personas = profile.get("personas", {})
    domain = detect_persona_domain(text)
    persona = personas.get(domain)
    if not persona:
        domain = "general"
        persona = {
            "label": profile.get("name", "Claude Coworker"),
            "role": profile.get("role", "Senior AI coworker"),
            "mission": profile.get("mission", ""),
            "decision_rules": profile.get("decision_rules", []),
            "strengths": profile.get("strengths", []),
            "default_mode": profile.get("default_mode", "builder"),
            "communication_style": profile.get("communication_style", ""),
        }
    if project_id:
        project = get_coworker_project(session_id, project_id)
        if project and project.get("working_style"):
            persona = {**persona, "communication_style": project["working_style"]}
    return domain, persona


def coworker_identity_text(session_id: str) -> str:
    profile = get_coworker_profile(session_id)
    lines = [
        f"Nome: {profile.get('name', '')}",
        f"Função: {profile.get('role', '')}",
        f"Missão: {profile.get('mission', '')}",
        f"Modo padrão: {profile.get('default_mode', 'builder')}",
        f"Estilo de comunicação: {profile.get('communication_style', '')}",
    ]
    rules = profile.get("decision_rules", [])
    strengths = profile.get("strengths", [])
    if rules:
        lines.append("Regras de decisão:")
        lines.extend(f"- {item}" for item in rules[:10])
    if strengths:
        lines.append("Forças:")
        lines.extend(f"- {item}" for item in strengths[:10])
    return "\n".join(lines)


def coworker_persona_text(session_id: str, text: str, project_id: Optional[str] = None) -> str:
    domain, persona = resolve_effective_persona(session_id, text, project_id)
    lines = [
        f"Persona ativa: {domain}",
        f"Label: {persona.get('label', '')}",
        f"Função: {persona.get('role', '')}",
        f"Missão: {persona.get('mission', '')}",
        f"Modo sugerido: {persona.get('default_mode', 'builder')}",
        f"Estilo: {persona.get('communication_style', '')}",
    ]
    if persona.get("decision_rules"):
        lines.append("Regras da persona:")
        lines.extend(f"- {item}" for item in persona["decision_rules"][:8])
    if persona.get("strengths"):
        lines.append("Forças da persona:")
        lines.extend(f"- {item}" for item in persona["strengths"][:8])
    return "\n".join(lines)


def get_coworker_project(session_id: str, project_id: str) -> Optional[dict]:
    for project in get_coworker_bucket("projects", session_id):
        if project["id"] == project_id:
            return project
    return None


def merge_unique_text(existing: list[str], incoming: list[str], limit: int) -> list[str]:
    ordered = []
    seen = set()
    for item in existing + incoming:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(text)
    return ordered[:limit]


def normalize_project_health(health: Optional[str]) -> str:
    value = (health or "green").strip().lower()
    if value in {"green", "yellow", "red"}:
        return value
    return "green"


def update_coworker_project_memory(
    session_id: str,
    project_id: str,
    preferences: list[str],
    decisions: list[str],
    facts: list[str],
    working_style: Optional[str],
    replace: bool = False,
) -> Optional[dict]:
    project = get_coworker_project(session_id, project_id)
    if not project:
        return None

    if replace:
        project["preferences"] = merge_unique_text([], preferences, 20)
        project["decisions"] = merge_unique_text([], decisions, 20)
        project["facts"] = merge_unique_text([], facts, 30)
        project["working_style"] = (working_style or "").strip()
    else:
        project["preferences"] = merge_unique_text(project.get("preferences", []), preferences, 20)
        project["decisions"] = merge_unique_text(project.get("decisions", []), decisions, 20)
        project["facts"] = merge_unique_text(project.get("facts", []), facts, 30)
        if working_style and working_style.strip():
            project["working_style"] = working_style.strip()

    project["updated_at"] = datetime.now().isoformat()
    project["last_activity_at"] = datetime.now().isoformat()
    persist_coworker_store()
    return project


def update_coworker_project_status(
    session_id: str,
    project_id: str,
    phase: Optional[str],
    health: Optional[str],
    next_action: Optional[str],
    blockers: list[str],
    risks: list[str],
    replace: bool = False,
) -> Optional[dict]:
    project = get_coworker_project(session_id, project_id)
    if not project:
        return None

    if phase and phase.strip():
        project["phase"] = phase.strip()
    if health is not None:
        project["health"] = normalize_project_health(health)
    if next_action is not None:
        project["next_action"] = next_action.strip()

    if replace:
        project["blockers"] = merge_unique_text([], blockers, 15)
        project["risks"] = merge_unique_text([], risks, 15)
    else:
        project["blockers"] = merge_unique_text(project.get("blockers", []), blockers, 15)
        project["risks"] = merge_unique_text(project.get("risks", []), risks, 15)

    project["updated_at"] = datetime.now().isoformat()
    project["last_activity_at"] = datetime.now().isoformat()
    persist_coworker_store()
    return project


def find_open_recovery_task(session_id: str, project_id: str) -> Optional[dict]:
    for task in get_coworker_bucket("tasks", session_id):
        if (
            task.get("project_id") == project_id
            and task.get("task_type") == "recovery"
            and task.get("status") in {"pending", "running", "blocked"}
        ):
            return task
    return None


def build_recovery_task_text(project: dict) -> str:
    parts = [f"Recuperar e estabilizar o projeto {project.get('name', 'sem nome')}."]
    if project.get("next_action"):
        parts.append(f"Próxima ação sugerida: {project['next_action']}")
    if project.get("blockers"):
        parts.append("Bloqueios: " + "; ".join(project["blockers"][:3]))
    if project.get("risks"):
        parts.append("Riscos: " + "; ".join(project["risks"][:3]))
    return " ".join(parts)


def ensure_recovery_task_for_project(session_id: str, project_id: str) -> Optional[dict]:
    project = get_coworker_project(session_id, project_id)
    if not project:
        return None
    if project.get("health") not in {"yellow", "red"}:
        return None

    existing = find_open_recovery_task(session_id, project_id)
    if existing:
        return existing

    related_objective = next(
        (
            item for item in list_coworker_objectives(session_id)
            if item.get("project_id") == project_id and item.get("status") == "active"
        ),
        None,
    )
    priority = "critical" if project.get("health") == "red" else "high"
    task = create_coworker_task(
        session_id,
        build_recovery_task_text(project),
        mode="operator",
        priority=priority,
        project_id=project_id,
        task_type="recovery",
        source="project_supervisor",
        objective_id=related_objective["id"] if related_objective else None,
    )
    if not find_open_inbox_item(session_id, "recovery", project_id):
        create_inbox_item(
            session_id,
            f"Atenção no projeto {project.get('name', 'sem nome')}",
            build_recovery_task_text(project),
            "recovery",
            priority=priority,
            related_id=project_id,
            related_kind="project",
            action_text=build_recovery_task_text(project),
            action_mode="operator",
        )
    record_coworker_decision(
        session_id,
        task["id"],
        "Projeto com saúde degradada gerou tarefa automática de recuperação.",
        {
            "project_id": project_id,
            "health": project.get("health"),
            "next_action": project.get("next_action"),
        },
    )
    return task


def coworker_project_memory_text(session_id: str, project_id: Optional[str]) -> str:
    if not project_id:
        return ""
    project = get_coworker_project(session_id, project_id)
    if not project:
        return ""

    lines = [
        f"Projeto: {project.get('name', '')}",
        f"Resumo: {project.get('summary', '')}",
    ]
    if project.get("working_style"):
        lines.append(f"Estilo de trabalho: {project['working_style']}")
    if project.get("preferences"):
        lines.append("Preferências:")
        lines.extend(f"- {item}" for item in project["preferences"][:10])
    if project.get("decisions"):
        lines.append("Decisões já tomadas:")
        lines.extend(f"- {item}" for item in project["decisions"][:10])
    if project.get("facts"):
        lines.append("Fatos do projeto:")
        lines.extend(f"- {item}" for item in project["facts"][:12])
    return "\n".join(lines)


def list_coworker_tasks(session_id: str) -> list[dict]:
    return sorted(
        get_coworker_bucket("tasks", session_id),
        key=lambda item: (
            item.get("status") not in {"running", "pending", "blocked"},
            priority_weight(item.get("priority", "medium")),
            item.get("created_at", ""),
        ),
    )


def update_coworker_task(session_id: str, task_id: str, **fields) -> Optional[dict]:
    for task in get_coworker_bucket("tasks", session_id):
        if task["id"] == task_id:
            if "priority" in fields and fields["priority"] is not None:
                fields["priority"] = normalize_priority(fields["priority"])
            if "status" in fields and fields["status"] is not None:
                fields["status"] = normalize_task_status(fields["status"])
            task.update(fields)
            task["updated_at"] = datetime.now().isoformat()
            if task.get("status") == "running" and not task.get("started_at"):
                task["started_at"] = datetime.now().isoformat()
            if task.get("status") in {"completed", "failed", "cancelled"}:
                task["completed_at"] = datetime.now().isoformat()
            persist_coworker_store()
            return task
    return None


def record_coworker_action(session_id: str, task_id: Optional[str], action_type: str, payload: dict) -> dict:
    action = {
        "id": str(uuid4()),
        "task_id": task_id,
        "action_type": action_type,
        "payload": payload,
        "created_at": datetime.now().isoformat(),
    }
    get_coworker_bucket("actions", session_id).append(action)
    persist_coworker_store()
    return action


def record_coworker_decision(session_id: str, task_id: Optional[str], summary: str, payload: dict) -> dict:
    decision = {
        "id": str(uuid4()),
        "task_id": task_id,
        "summary": summary,
        "payload": payload,
        "created_at": datetime.now().isoformat(),
    }
    get_coworker_bucket("decisions", session_id).append(decision)
    persist_coworker_store()
    return decision


def get_coworker_routines(session_id: str) -> list[dict]:
    return get_coworker_bucket("routines", session_id)


def create_coworker_routine(
    session_id: str,
    name: str,
    prompt: str,
    mode: str = "operator",
    priority: str = "medium",
    project_id: Optional[str] = None,
    trigger: str = "manual",
    enabled: bool = True,
) -> dict:
    routine = {
        "id": str(uuid4()),
        "name": name.strip(),
        "prompt": prompt.strip(),
        "mode": mode,
        "priority": normalize_priority(priority),
        "project_id": project_id,
        "trigger": trigger,
        "enabled": enabled,
        "last_run_at": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    get_coworker_bucket("routines", session_id).append(routine)
    persist_coworker_store()
    return routine


def run_coworker_routine(session_id: str, routine_id: str) -> dict:
    for routine in get_coworker_routines(session_id):
        if routine["id"] == routine_id:
            if not routine.get("enabled", True):
                raise HTTPException(status_code=400, detail="Rotina desabilitada.")
            routine["last_run_at"] = datetime.now().isoformat()
            routine["updated_at"] = datetime.now().isoformat()
            task = create_coworker_task(
                session_id,
                routine["prompt"],
                mode=routine.get("mode", "operator"),
                priority=routine.get("priority", "medium"),
                project_id=routine.get("project_id"),
                task_type="routine",
                source=f"routine:{routine['id']}",
            )
            persist_coworker_store()
            return {"routine": routine, "task": task}
    raise HTTPException(status_code=404, detail="Rotina não encontrada.")


def get_session_queue(session_id: str) -> list[dict]:
    return task_queue_store.setdefault(session_id, [])


def enqueue_task(session_id: str, mode: str, text: str) -> dict:
    queue = get_session_queue(session_id)
    task = {
        "id": str(uuid4()),
        "text": text,
        "mode": mode,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    queue.append(task)
    return task


def update_task(session_id: str, task_id: str, **fields) -> Optional[dict]:
    queue = get_session_queue(session_id)
    for task in queue:
        if task["id"] == task_id:
            task.update(fields)
            task["updated_at"] = datetime.now().isoformat()
            return task
    return None


def next_pending_task(session_id: str) -> Optional[dict]:
    for task in get_session_queue(session_id):
        if task["status"] == "pending":
            return task
    return None


def list_sessions_with_pending_tasks() -> list[str]:
    sessions = []
    for session_id, tasks in task_queue_store.items():
        if any(task.get("status") == "pending" for task in tasks):
            sessions.append(session_id)
    return sessions


def check_rate_limit(request: Request, authorization: str) -> None:
    token_fingerprint = authorization[-8:] if authorization else "anonymous"
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{token_fingerprint}"
    now = time.time()
    window_start = now - config.RATE_LIMIT_WINDOW_SECONDS
    entries = [timestamp for timestamp in rate_limit_store.get(key, []) if timestamp >= window_start]
    if len(entries) >= config.RATE_LIMIT_MAX_REQUESTS:
        audit_log(
            "rate_limit_block",
            request,
            {
                "key": key,
                "window_seconds": config.RATE_LIMIT_WINDOW_SECONDS,
                "max_requests": config.RATE_LIMIT_MAX_REQUESTS,
            },
        )
        raise HTTPException(status_code=429, detail="Rate limit excedido. Aguarde e tente novamente.")
    entries.append(now)
    rate_limit_store[key] = entries


def build_messages(system: str, user_text: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]


def run_local_script(script_name: str, timeout_seconds: int = 120) -> dict:
    script_path = Path(__file__).resolve().parents[1] / script_name
    if not script_path.exists():
        raise HTTPException(status_code=404, detail=f"Script não encontrado: {script_name}")

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return {
        "script": script_name,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
        "ok": completed.returncode == 0,
    }


def control_status_snapshot() -> dict:
    return {
        "supervisor": run_local_script("status-stoa-supervisor.ps1", timeout_seconds=30),
        "api": run_local_script("status-stoa-daemon.ps1", timeout_seconds=30),
        "voice": run_local_script("status-stoa-voice-daemon.ps1", timeout_seconds=30),
        "tray": run_local_script("status-stoa-tray.ps1", timeout_seconds=30),
    }


def get_or_create_session_id(session_id: Optional[str]) -> str:
    normalized = (session_id or "").strip()
    return normalized or str(uuid4())


def ensure_workspace_root() -> Path:
    config.WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return config.WORKSPACE_ROOT


def get_allowed_root(session_id: str, root_alias: str = "session") -> Path:
    normalized = (root_alias or "session").strip().lower()
    if normalized == "session":
        base = ensure_workspace_root() / session_id
        base.mkdir(parents=True, exist_ok=True)
        return base.resolve()

    if normalized not in {alias.lower() for alias in config.EXTERNAL_ALLOWED_ROOTS.keys()}:
        raise HTTPException(status_code=403, detail=f"Root alias '{root_alias}' não permitido.")

    for alias, path in config.EXTERNAL_ALLOWED_ROOTS.items():
        if alias.strip().lower() == normalized:
            resolved = path.resolve()
            resolved.mkdir(parents=True, exist_ok=True)
            return resolved

    raise HTTPException(status_code=403, detail=f"Root alias '{root_alias}' não permitido.")


def resolve_allowed_cwd(session_id: str, cwd: Optional[str], root_alias: str = "session") -> Path:
    base = get_allowed_root(session_id, root_alias=root_alias)
    if not cwd:
        return base

    candidate = (base / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).resolve()
    if not str(candidate).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="cwd fora da área permitida da sessão.")
    return candidate


def resolve_workspace_target(session_id: str, relative_path: str, root_alias: str = "session") -> Path:
    normalized = relative_path.replace("\\", "/").strip().lstrip("/")
    if not normalized or ".." in Path(normalized).parts:
        raise HTTPException(status_code=400, detail="relative_path inválido.")

    base = get_allowed_root(session_id, root_alias=root_alias)
    target = (base / normalized).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Caminho fora da área permitida da sessão.")
    return target


def get_editable_root(session_id: str) -> Path:
    editable_root = ensure_workspace_root() / session_id / "editable"
    editable_root.mkdir(parents=True, exist_ok=True)
    return editable_root


def resolve_editable_path(session_id: str, relative_path: str) -> Path:
    normalized = relative_path.replace("\\", "/").strip().lstrip("/")
    if not normalized or ".." in Path(normalized).parts:
        raise HTTPException(status_code=400, detail="relative_path inválido.")

    editable_root = get_editable_root(session_id).resolve()
    target_path = (editable_root / normalized).resolve()
    if not str(target_path).startswith(str(editable_root)):
        raise HTTPException(status_code=400, detail="Caminho fora da área editável.")

    if target_path.suffix.lower() not in config.EDITABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Extensão não permitida.")

    return target_path


def write_editable_file(session_id: str, relative_path: str, content: str, overwrite: bool = True) -> str:
    target_path = resolve_editable_path(session_id, relative_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not overwrite:
        raise HTTPException(status_code=409, detail="Arquivo já existe e overwrite=False.")
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def read_editable_file(session_id: str, relative_path: str) -> tuple[Path, str]:
    target_path = resolve_editable_path(session_id, relative_path)
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return target_path, target_path.read_text(encoding="utf-8")


def list_editable_tree(session_id: str) -> list[dict]:
    editable_root = get_editable_root(session_id)
    items: list[dict] = []
    for path in sorted(editable_root.rglob("*")):
        items.append(
            {
                "type": "file" if path.is_file() else "dir",
                "relative_path": str(path.relative_to(editable_root)),
            }
        )
    return items


def list_editable_files(session_id: str) -> list[str]:
    editable_root = get_editable_root(session_id)
    return [
        str(path.relative_to(editable_root))
        for path in sorted(editable_root.rglob("*"))
        if path.is_file()
    ]


def build_project_summary_prompt(files: list[dict], instruction: Optional[str]) -> str:
    rendered_files = []
    for item in files:
        rendered_files.append(
            f"Arquivo: {item['relative_path']}\nConteúdo:\n{item['content']}"
        )
    suffix = f"\n\nPedido adicional:\n{instruction}" if instruction else ""
    return "\n\n".join(rendered_files) + suffix


def build_project_patch_prompt(files: list[dict], instruction: str) -> str:
    rendered_files = []
    for item in files:
        rendered_files.append(
            f"Arquivo: {item['relative_path']}\nConteúdo atual:\n{item['content']}"
        )
    return "\n\n".join(rendered_files) + f"\n\nObjetivo de mudança:\n{instruction}"


def plan_project_patch(files: list[dict], instruction: str, session_id: str) -> ProjectPatchPlan:
    system = """
Você é um planejador de mudanças em projeto.
Retorne APENAS JSON válido no formato:
{
  "objective": "objetivo curto",
  "steps": [
    {"relative_path": "arquivo.ext", "instruction": "mudança exata a fazer nesse arquivo"}
  ]
}

Regras:
- Use apenas arquivos já fornecidos.
- Não invente caminhos novos.
- Seja específico e curto.
- Planeje só mudanças necessárias para cumprir o objetivo.
""".strip()
    data = model_json(system, build_project_patch_prompt(files, instruction), session_id=session_id)
    return ProjectPatchPlan(
        objective=str(data.get("objective") or instruction[:120]),
        steps=[ProjectPatchStep(**step) for step in (data.get("steps") or [])],
    )


def decide_autopilot(session_id: str, command: str, mode: str) -> AutopilotDecision:
    existing_files = list_editable_files(session_id)[: config.AUTOPILOT_MAX_FILES]
    system = f"""
Você decide como um agente autônomo deve agir.
Retorne APENAS JSON válido no formato:
{{
  "mode": "super_task" ou "project_patch",
  "objective": "objetivo curto",
  "relative_paths": ["arquivo/opcional.ext"],
  "prompt": "pedido final para super_task",
  "instruction": "pedido final para project_patch"
}}

Regras:
- Use "project_patch" apenas se já existirem arquivos relevantes para editar.
- Em "project_patch", escolha apenas arquivos existentes da lista fornecida.
- Em "super_task", preencha "prompt".
- Em "project_patch", preencha "instruction" e "relative_paths".
- Considere o modo operacional: {mode_preamble(mode)}
""".strip()
    user_text = json.dumps(
        {
            "request": command,
            "existing_files": existing_files,
        },
        ensure_ascii=False,
        indent=2,
    )
    data = model_json(system, user_text, model=config.MODEL_AUTOPILOT, session_id=session_id)
    decision = AutopilotDecision(**data)
    if decision.mode == "project_patch":
        allowed = set(existing_files)
        decision.relative_paths = [path for path in decision.relative_paths if path in allowed][: config.AUTOPILOT_MAX_FILES]
        if not decision.relative_paths:
            decision.mode = "super_task"
            decision.prompt = decision.prompt or command
    return decision


def decide_orchestrator(session_id: str, command: str, mode: str) -> OrchestratorDecision:
    existing_files = list_editable_files(session_id)[: config.AUTOPILOT_MAX_FILES]
    system = """
Você decide qual conector deve executar uma tarefa.
Retorne APENAS JSON válido no formato:
{
  "action": "autopilot|run_command|prepare_editor_task|create_spreadsheet|create_excel_workbook",
  "objective": "objetivo curto",
  "app": "cursor|code|excel",
  "relative_path": "opcional/arquivo.csv",
  "workspace_relative_path": "opcional/pasta",
  "command": "opcional comando permitido",
  "rows": [["col1","col2"],["a","b"]],
  "sheets": [{"name":"Resumo","rows":[["A","B"],["1","2"]]}],
  "prompt": "pedido final para autopilot/editor"
}

Regras:
- Use autopilot por padrão para criação/edição de projeto.
- Use prepare_editor_task quando o pedido claramente envolver trabalhar em editor.
- Use create_spreadsheet apenas para planilhas/tabelas.
- Use create_excel_workbook quando o usuário pedir explicitamente uma planilha Excel.
- Use run_command só para comandos simples e permitidos.
- Considere o modo operacional recebido.
""".strip()
    user_text = json.dumps(
        {"request": command, "mode": mode, "existing_files": existing_files},
        ensure_ascii=False,
        indent=2,
    )
    data = model_json(system, user_text, model=config.MODEL_AUTOPILOT, session_id=session_id)
    return OrchestratorDecision(**data)


async def execute_orchestrator(session_id: str, mode: str, text: str, request: Optional[Request] = None) -> OrchestratorResult:
    decision = decide_orchestrator(session_id, text, mode)

    if decision.action == "run_command":
        if not decision.command:
            raise HTTPException(status_code=400, detail="Orquestrador retornou run_command sem command.")
        result = await run_command_endpoint(
            TerminalCommandRequest(session_id=session_id, command=decision.command),
            request or Request(scope={"type": "http", "headers": []}),
        )
    elif decision.action == "prepare_editor_task":
        if not decision.app or not decision.workspace_relative_path:
            raise HTTPException(status_code=400, detail="Orquestrador retornou prepare_editor_task incompleto.")
        result = await prepare_editor_task_endpoint(
            EditorTaskRequest(
                session_id=session_id,
                app=decision.app,
                workspace_relative_path=decision.workspace_relative_path,
                task=decision.prompt or text,
            ),
            request or Request(scope={"type": "http", "headers": []}),
        )
    elif decision.action == "create_spreadsheet":
        if not decision.relative_path or not decision.rows:
            raise HTTPException(status_code=400, detail="Orquestrador retornou create_spreadsheet incompleto.")
        result = await create_spreadsheet_endpoint(
            SpreadsheetCreateRequest(
                session_id=session_id,
                relative_path=decision.relative_path,
                rows=decision.rows,
                open_in_excel=(decision.app or "").lower() == "excel",
            ),
            request or Request(scope={"type": "http", "headers": []}),
        )
    elif decision.action == "create_excel_workbook":
        workbook_data = {
            "relative_path": decision.relative_path,
            "sheets": decision.sheets,
            "open_in_excel": (decision.app or "").lower() == "excel",
        }
        if not workbook_data["relative_path"] or not workbook_data["sheets"]:
            workbook_data = generate_excel_workbook_plan(text, session_id)
        result = await create_excel_workbook_endpoint(
            ExcelWorkbookRequest(
                session_id=session_id,
                relative_path=workbook_data["relative_path"],
                sheets=[ExcelSheetRequest(**sheet) for sheet in workbook_data["sheets"]],
                open_in_excel=bool(workbook_data.get("open_in_excel", False)),
            ),
            request or Request(scope={"type": "http", "headers": []}),
        )
    else:
        auto = await autopilot_endpoint(
            VoiceCommand(
                text=decision.prompt or text,
                session_id=session_id,
                mode=mode,
            ),
            request or Request(scope={"type": "http", "headers": []}),
        )
        result = auto.model_dump()
        decision.action = "autopilot"

    if request:
        audit_log(
            "orchestrate",
            request,
            {"session_id": session_id, "action": decision.action, "objective": decision.objective},
        )
    return OrchestratorResult(
        session_id=session_id,
        action=decision.action,
        objective=decision.objective,
        result=result,
    )


def slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "artifact"


def parse_command_tokens(command: str) -> list[str]:
    stripped = command.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="Comando vazio.")
    return stripped.split()


def command_is_allowed(tokens: list[str]) -> bool:
    lowered = [token.lower() for token in tokens]
    for prefix in config.ALLOWED_COMMAND_PREFIXES:
        prefix_lower = [part.lower() for part in prefix]
        if lowered[: len(prefix_lower)] == prefix_lower:
            return True
    return False


def resolve_app_command(app: str) -> list[str]:
    normalized = app.strip().lower()
    if normalized not in config.ALLOWED_APPS:
        raise HTTPException(status_code=403, detail=f"App '{app}' não permitido.")

    mapping = {
        "notepad": ["notepad.exe"],
        "code": ["code"],
        "cursor": ["cursor"],
        "excel": ["excel"],
    }
    if normalized not in mapping:
        raise HTTPException(status_code=400, detail=f"App '{app}' sem resolução configurada.")
    return mapping[normalized]


def resolve_browser_command(browser: str) -> list[str]:
    normalized = browser.strip().lower()
    if normalized not in config.ALLOWED_BROWSERS:
        raise HTTPException(status_code=403, detail=f"Browser '{browser}' não permitido.")

    mapping = {
        "msedge": ["msedge"],
        "chrome": ["chrome"],
        "firefox": ["firefox"],
    }
    if normalized not in mapping:
        raise HTTPException(status_code=400, detail=f"Browser '{browser}' sem resolução configurada.")
    return mapping[normalized]


def validate_allowed_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="URL deve usar http ou https.")
    hostname = (parsed.hostname or "").lower()
    if hostname not in config.ALLOWED_BROWSER_DOMAINS:
        raise HTTPException(status_code=403, detail=f"Domínio '{hostname}' não permitido.")
    return url.strip()


def create_csv_spreadsheet(session_id: str, relative_path: str, rows: list[list[str]], root_alias: str = "session") -> str:
    target_path = resolve_workspace_target(session_id, relative_path, root_alias=root_alias)
    if target_path.suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="A planilha controlada deve usar extensão .csv.")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
    return str(target_path)


def create_excel_workbook(session_id: str, relative_path: str, sheets: list[ExcelSheetRequest], open_in_excel: bool, root_alias: str = "session") -> str:
    target_path = resolve_workspace_target(session_id, relative_path, root_alias=root_alias)
    if target_path.suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="A planilha do Excel deve usar extensão .xlsx.")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "sheets": [
            {
                "name": sheet.name,
                "rows": sheet.rows,
            }
            for sheet in sheets
        ]
    }

    script = r"""
param([string]$JsonPath, [string]$WorkbookPath, [string]$VisibleFlag)
$visible = $VisibleFlag -eq 'true'
$data = Get-Content -Path $JsonPath -Raw | ConvertFrom-Json
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $visible
$excel.DisplayAlerts = $false
$workbook = $excel.Workbooks.Add()
try {
    while ($workbook.Worksheets.Count -lt $data.sheets.Count) {
        $null = $workbook.Worksheets.Add()
    }
    while ($workbook.Worksheets.Count -gt $data.sheets.Count) {
        $workbook.Worksheets.Item($workbook.Worksheets.Count).Delete()
    }

    for ($sheetIndex = 0; $sheetIndex -lt $data.sheets.Count; $sheetIndex++) {
        $sheetData = $data.sheets[$sheetIndex]
        $sheet = $workbook.Worksheets.Item($sheetIndex + 1)
        $sheet.Name = $sheetData.name
        for ($rowIndex = 0; $rowIndex -lt $sheetData.rows.Count; $rowIndex++) {
            $row = $sheetData.rows[$rowIndex]
            for ($colIndex = 0; $colIndex -lt $row.Count; $colIndex++) {
                $sheet.Cells.Item($rowIndex + 1, $colIndex + 1) = [string]$row[$colIndex]
            }
        }
        $null = $sheet.UsedRange.Columns.AutoFit()
    }

    $workbook.SaveAs($WorkbookPath, 51)
    if (-not $visible) {
        $workbook.Close($true)
        $excel.Quit()
    }
}
finally {
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) | Out-Null
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
"""

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        json_path = handle.name
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".ps1") as handle:
        handle.write(script)
        script_path = handle.name

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-File",
                script_path,
                json_path,
                str(target_path),
                "true" if open_in_excel else "false",
            ],
            capture_output=True,
            text=True,
            timeout=max(config.TERMINAL_TIMEOUT_SECONDS, 60),
            shell=False,
        )
    finally:
        try:
            Path(json_path).unlink(missing_ok=True)
        except Exception:
            pass
        try:
            Path(script_path).unlink(missing_ok=True)
        except Exception:
            pass

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Falha ao automatizar Excel: {result.stderr or result.stdout}")

    return str(target_path)


def update_excel_cell(
    session_id: str,
    relative_path: str,
    sheet_name: str,
    cell: str,
    value: str,
    open_in_excel: bool,
    root_alias: str = "session",
) -> str:
    target_path = resolve_workspace_target(session_id, relative_path, root_alias=root_alias)
    if target_path.suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Atualização de Excel requer arquivo .xlsx.")
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Workbook .xlsx não encontrado.")

    script = r"""
param([string]$WorkbookPath, [string]$SheetName, [string]$CellRef, [string]$CellValue, [string]$VisibleFlag)
$visible = $VisibleFlag -eq 'true'
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $visible
$excel.DisplayAlerts = $false
$workbook = $excel.Workbooks.Open($WorkbookPath)
try {
    $sheet = $workbook.Worksheets.Item($SheetName)
    $sheet.Range($CellRef).Value2 = $CellValue
    $null = $sheet.UsedRange.Columns.AutoFit()
    $workbook.Save()
    if (-not $visible) {
        $workbook.Close($true)
        $excel.Quit()
    }
}
finally {
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) | Out-Null
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
"""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".ps1") as handle:
        handle.write(script)
        script_path = handle.name

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-File",
                script_path,
                str(target_path),
                sheet_name,
                cell,
                value,
                "true" if open_in_excel else "false",
            ],
            capture_output=True,
            text=True,
            timeout=max(config.TERMINAL_TIMEOUT_SECONDS, 60),
            shell=False,
        )
    finally:
        try:
            Path(script_path).unlink(missing_ok=True)
        except Exception:
            pass

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Falha ao atualizar Excel: {result.stderr or result.stdout}")

    return str(target_path)


def generate_excel_workbook_plan(command: str, session_id: str) -> dict:
    system = """
Você gera uma estrutura de planilha Excel a partir de um pedido em linguagem natural.
Retorne APENAS JSON válido no formato:
{
  "relative_path": "editable/planilhas/nome.xlsx",
  "open_in_excel": true,
  "sheets": [
    {
      "name": "Resumo",
      "rows": [
        ["Coluna 1", "Coluna 2"],
        ["Valor A", "Valor B"]
      ]
    }
  ]
}

Regras:
- Use extensão .xlsx.
- Gere entre 1 e 5 abas.
- Gere conteúdo inicial útil e simples.
- Não exceda 100 linhas por aba.
""".strip()
    return model_json(system, command, model=config.MODEL_AUTOPILOT, session_id=session_id)


def generate_browser_execution_plan(session_id: str, url: str, task: str) -> dict:
    system = """
Você gera um plano de navegação web.
Retorne APENAS JSON válido no formato:
{
  "objective": "objetivo curto",
  "steps": [
    "Abrir a página correta",
    "Verificar o contexto visível",
    "Executar a próxima ação"
  ],
  "warnings": [
    "riscos ou dependências"
  ]
}

Regras:
- Não invente elementos específicos se não houver contexto suficiente.
- Seja objetivo.
- Liste entre 3 e 8 passos.
""".strip()
    return model_json(
        system,
        json.dumps({"url": url, "task": task}, ensure_ascii=False, indent=2),
        model=config.MODEL_AUTOPILOT,
        session_id=session_id,
    )


def write_workspace_file(session_id: str, relative_path: str, content: str, overwrite: bool = True, root_alias: str = "session") -> str:
    target_path = resolve_workspace_target(session_id, relative_path, root_alias=root_alias)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not overwrite:
        raise HTTPException(status_code=409, detail="Arquivo já existe e overwrite=False.")
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def build_editor_task_markdown(task: str, workspace_path: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""# Editor Task Brief

Timestamp: {timestamp}
Workspace: {workspace_path}

## Objetivo
{task}

## Instruções
- Entenda o objetivo antes de editar.
- Priorize mudanças pequenas e verificáveis.
- Registre os arquivos principais afetados.
- Se existir ambiguidade, faça a menor suposição razoável.
"""


def build_browser_task_markdown(task: str, url: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""# Browser Task Brief

Timestamp: {timestamp}
URL: {url}

## Objetivo
{task}

## Instruções
- Verifique a página correta antes de agir.
- Siga o objetivo com o menor número de passos possível.
- Evite ações destrutivas sem confirmação explícita.
"""


def artifact_extension(module: str) -> str:
    return {
        "web": ".html",
        "code": ".md",
        "planning": ".md",
        "strategy": ".md",
        "education": ".md",
        "info": ".md",
        "weather": ".md",
        "time": ".md",
    }.get(module, ".txt")


def save_artifact(session_id: str, module: str, content: str, goal: Optional[str] = None) -> str:
    root = ensure_workspace_root()
    session_dir = root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = slugify(goal or module)[:50]
    file_path = session_dir / f"{timestamp}-{module}-{base_name}{artifact_extension(module)}"
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)


def build_file_edit_prompt(existing_content: str, instruction: str, relative_path: str) -> str:
    return (
        f"Arquivo alvo: {relative_path}\n\n"
        f"Instrução de edição:\n{instruction}\n\n"
        "Conteúdo atual do arquivo:\n"
        f"{existing_content}"
    )


def build_file_review_prompt(existing_content: str, instruction: str, relative_path: str) -> str:
    return (
        f"Arquivo alvo: {relative_path}\n\n"
        f"Pedido do usuário:\n{instruction}\n\n"
        "Conteúdo atual do arquivo:\n"
        f"{existing_content}"
    )


def get_session_history(session_id: str) -> list[dict]:
    return session_store.setdefault(session_id, [])


def append_session_message(session_id: str, role: str, content: str) -> None:
    history = get_session_history(session_id)
    history.append({"role": role, "content": content, "timestamp": datetime.now().isoformat()})
    if len(history) > config.MAX_SESSION_MESSAGES:
        session_store[session_id] = history[-config.MAX_SESSION_MESSAGES :]
    persist_session_store()


def summarize_session_history(session_id: str) -> str:
    history = get_session_history(session_id)
    if not history:
        return ""

    lines = []
    for item in history[-config.MAX_SESSION_MESSAGES :]:
        role = "usuário" if item["role"] == "user" else "agente"
        lines.append(f"{role}: {truncate_text(item['content'], 300)}")
    return "\n".join(lines)


def get_anthropic_client() -> anthropic.Anthropic:
    global client

    if not config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEY == "COLE_SUA_ANTHROPIC_API_KEY_AQUI":
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY não configurada no .env.safe.")

    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    return client


def model_text(
    system: str,
    user_text: str,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    if session_id:
        history_text = summarize_session_history(session_id)
        if history_text:
            system = f"{system}\n\nContexto recente da sessão:\n{history_text}"

    response = get_anthropic_client().messages.create(
        model=model or config.MODEL_DEFAULT,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    text = (response.content[0].text if response.content else "").strip()
    if not text:
        raise RuntimeError("A resposta do modelo veio vazia.")
    return text


def model_json(
    system: str,
    user_text: str,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict:
    raw = model_text(system, user_text, model=model, session_id=session_id)

    # 1) Try to pull JSON out of a ```json ... ``` block.
    match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL)
    if match:
        cleaned = match.group(1)
    else:
        # 2) Find the first { ... } or [ ... ] in the raw text.
        match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        cleaned = match.group(1) if match else raw.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"O modelo retornou JSON inválido: {exc}\nResposta bruta: {raw[:300]}") from exc


def parse_coworker_intake(session_id: str, text: str, mode: str) -> dict:
    identity_text = coworker_identity_text(session_id)
    persona_text = coworker_persona_text(session_id, text)
    domain, persona = resolve_effective_persona(session_id, text)
    existing_projects = [
        {
            "id": project["id"],
            "name": project["name"],
            "summary": truncate_text(project["summary"], 180),
            "memory": truncate_text(coworker_project_memory_text(session_id, project["id"]), 500),
        }
        for project in list_coworker_projects(session_id)[:8]
    ]
    system = (
        "Você é o intake de um AI coworker. "
        "Transforme um pedido livre em estrutura operacional para um colega de trabalho digital.\n"
        "Responda JSON com: "
        "objective, priority, task_type, mode, project_name, project_summary, existing_project_id, next_step.\n"
        "priority: critical|high|medium|low.\n"
        "task_type: deliverable|review|research|routine|operation.\n"
        "mode: builder|operator.\n"
        "Se o pedido encaixar claramente em um projeto existente, use existing_project_id. "
        "Se não, retorne project_name e project_summary para abrir um novo projeto."
    )
    user_text = (
        f"Identidade operacional do coworker:\n{identity_text}\n\n"
        f"Persona ativa sugerida:\n{persona_text}\n\n"
        f"Modo preferido: {mode}\n"
        f"Projetos existentes: {json.dumps(existing_projects, ensure_ascii=False)}\n"
        f"Pedido: {text}"
    )
    data = model_json(system, user_text, model=config.MODEL_PLANNER, session_id=session_id)
    data["priority"] = normalize_priority(data.get("priority"))
    data["mode"] = "operator" if str(data.get("mode", persona.get("default_mode", mode))).strip().lower() == "operator" else "builder"
    data["domain"] = str(data.get("domain", domain)).strip() or domain
    return data


def plan_coworker_objective(session_id: str, objective: str, mode: str, project_id: Optional[str] = None) -> dict:
    project_context = get_coworker_project(session_id, project_id) if project_id else None
    memory_text = coworker_project_memory_text(session_id, project_id)
    identity_text = coworker_identity_text(session_id)
    persona_text = coworker_persona_text(session_id, objective, project_id)

    system = (
        "Você é o planner de um AI coworker. "
        "Quebre um objetivo de trabalho em um plano curto e executável.\n"
        "Responda JSON com: objective_summary, success_criteria, milestones.\n"
        "milestones deve ser uma lista de até 5 itens com: title, priority, mode, task_type, task.\n"
        "priority: critical|high|medium|low. mode: builder|operator. "
        "task_type: deliverable|review|research|routine|operation."
    )
    user_text = (
        f"Identidade operacional do coworker:\n{identity_text}\n"
        f"Persona ativa:\n{persona_text}\n"
        f"Projeto: {json.dumps(project_context, ensure_ascii=False) if project_context else 'nenhum'}\n"
        f"Memória estratégica do projeto:\n{memory_text or 'nenhuma'}\n"
        f"Modo preferido: {mode}\n"
        f"Objetivo: {objective}"
    )
    data = model_json(system, user_text, model=config.MODEL_PLANNER, session_id=session_id)
    milestones = data.get("milestones", [])
    normalized = []
    for item in milestones[:5]:
        if not isinstance(item, dict):
            continue
        task_text = str(item.get("task", "")).strip()
        if not task_text:
            continue
        normalized.append(
            {
                "title": str(item.get("title", "Etapa")).strip() or "Etapa",
                "priority": normalize_priority(item.get("priority")),
                "mode": "operator" if str(item.get("mode", mode)).strip().lower() == "operator" else "builder",
                "task_type": str(item.get("task_type", "deliverable")).strip() or "deliverable",
                "task": task_text,
            }
        )
    data["milestones"] = normalized
    return data


def infer_project_memory_update(session_id: str, project_id: str, task_text: str, result: dict) -> dict:
    system = (
        "Você extrai memória estratégica de projeto a partir de uma tarefa concluída.\n"
        "Responda JSON com: preferences, decisions, facts, working_style.\n"
        "Cada campo, exceto working_style, deve ser uma lista curta. "
        "Inclua só itens úteis para trabalho futuro."
    )
    user_text = (
        f"Identidade operacional do coworker:\n{coworker_identity_text(session_id)}\n\n"
        f"Memória atual:\n{coworker_project_memory_text(session_id, project_id) or 'nenhuma'}\n\n"
        f"Tarefa concluída:\n{task_text}\n\n"
        f"Resultado:\n{json.dumps(result, ensure_ascii=False)}"
    )
    data = model_json(system, user_text, model=config.MODEL_PLANNER, session_id=session_id)
    return {
        "preferences": data.get("preferences", []) if isinstance(data.get("preferences"), list) else [],
        "decisions": data.get("decisions", []) if isinstance(data.get("decisions"), list) else [],
        "facts": data.get("facts", []) if isinstance(data.get("facts"), list) else [],
        "working_style": str(data.get("working_style", "")).strip(),
    }


def infer_project_status_update(session_id: str, project_id: str) -> dict:
    project = get_coworker_project(session_id, project_id)
    if not project:
        return {}

    related_tasks = [item for item in get_coworker_bucket("tasks", session_id) if item.get("project_id") == project_id]
    related_objectives = [item for item in get_coworker_bucket("objectives", session_id) if item.get("project_id") == project_id]
    system = (
        "Você é um supervisor operacional de projeto.\n"
        "A partir do estado atual, produza um diagnóstico curto.\n"
        "Responda JSON com: phase, health, next_action, blockers, risks.\n"
        "health: green|yellow|red."
    )
    user_text = (
        f"Identidade operacional do coworker:\n{coworker_identity_text(session_id)}\n\n"
        f"Persona ativa de referência:\n{coworker_persona_text(session_id, project.get('summary', ''), project_id)}\n\n"
        f"Projeto:\n{json.dumps(project, ensure_ascii=False)}\n\n"
        f"Objetivos:\n{json.dumps(related_objectives[-8:], ensure_ascii=False)}\n\n"
        f"Tarefas:\n{json.dumps(related_tasks[-12:], ensure_ascii=False)}"
    )
    data = model_json(system, user_text, model=config.MODEL_PLANNER, session_id=session_id)
    return {
        "phase": str(data.get("phase", project.get("phase", "delivery"))).strip() or project.get("phase", "delivery"),
        "health": normalize_project_health(data.get("health")),
        "next_action": str(data.get("next_action", "")).strip(),
        "blockers": data.get("blockers", []) if isinstance(data.get("blockers"), list) else [],
        "risks": data.get("risks", []) if isinstance(data.get("risks"), list) else [],
    }


def run_project_supervisor(session_id: str, project_id: str) -> dict:
    project = get_coworker_project(session_id, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    status_update = infer_project_status_update(session_id, project_id)
    project = update_coworker_project_status(
        session_id,
        project_id,
        status_update.get("phase"),
        status_update.get("health"),
        status_update.get("next_action"),
        status_update.get("blockers", []),
        status_update.get("risks", []),
        replace=True,
    )
    recovery_task = ensure_recovery_task_for_project(session_id, project_id)
    return {"project": project, "status_update": status_update, "recovery_task": recovery_task}


def list_active_project_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for session_id, projects in coworker_store.get("projects", {}).items():
        if not isinstance(projects, list):
            continue
        for project in projects:
            if isinstance(project, dict) and project.get("status", "active") == "active" and project.get("id"):
                pairs.append((session_id, project["id"]))
    return pairs


def list_sessions_with_active_projects() -> list[str]:
    return sorted({session_id for session_id, _project_id in list_active_project_pairs()})


def latest_briefing_for_session(session_id: str) -> Optional[dict]:
    briefings = get_coworker_bucket("briefings", session_id)
    return briefings[-1] if briefings else None


def list_inbox_items(session_id: str) -> list[dict]:
    items = get_coworker_bucket("inbox", session_id)
    return sorted(
        items,
        key=lambda item: (
            item.get("status") != "open",
            priority_weight(item.get("priority", "medium")),
            item.get("created_at", ""),
        ),
    )


def create_inbox_item(
    session_id: str,
    title: str,
    body: str,
    item_type: str,
    priority: str = "medium",
    related_id: Optional[str] = None,
    related_kind: Optional[str] = None,
    action_text: Optional[str] = None,
    action_mode: str = "operator",
) -> dict:
    item = {
        "id": str(uuid4()),
        "title": title.strip(),
        "body": body.strip(),
        "item_type": item_type,
        "priority": normalize_priority(priority),
        "status": "open",
        "related_id": related_id,
        "related_kind": related_kind,
        "action_text": (action_text or body).strip(),
        "action_mode": "operator" if str(action_mode).strip().lower() == "operator" else "builder",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    get_coworker_bucket("inbox", session_id).append(item)
    persist_coworker_store()
    return item


def find_open_inbox_item(session_id: str, item_type: str, related_id: Optional[str] = None) -> Optional[dict]:
    for item in get_coworker_bucket("inbox", session_id):
        if item.get("item_type") == item_type and item.get("status") == "open":
            if related_id is None or item.get("related_id") == related_id:
                return item
    return None


def update_inbox_item_status(session_id: str, item_id: str, status: str) -> Optional[dict]:
    normalized = status.strip().lower()
    if normalized not in {"open", "done", "dismissed"}:
        normalized = "open"
    for item in get_coworker_bucket("inbox", session_id):
        if item["id"] == item_id:
            item["status"] = normalized
            item["updated_at"] = datetime.now().isoformat()
            persist_coworker_store()
            return item
    return None


def get_inbox_item(session_id: str, item_id: str) -> Optional[dict]:
    for item in get_coworker_bucket("inbox", session_id):
        if item["id"] == item_id:
            return item
    return None


def generate_daily_briefing_text(session_id: str) -> str:
    projects = list_coworker_projects(session_id)
    objectives = list_coworker_objectives(session_id)
    tasks = list_coworker_tasks(session_id)
    actions = get_coworker_bucket("actions", session_id)[-10:]
    system = (
        "Você é um chefe de gabinete operacional.\n"
        "Gere um briefing diário curto e claro em português.\n"
        "Estruture com: foco do dia, progresso recente, riscos/bloqueios, próxima ação recomendada."
    )
    user_text = (
        f"Identidade operacional:\n{coworker_identity_text(session_id)}\n\n"
        f"Relatório atual:\n{coworker_daily_report_text(session_id)}\n\n"
        f"Projetos:\n{json.dumps(projects[-8:], ensure_ascii=False)}\n\n"
        f"Objetivos:\n{json.dumps(objectives[-8:], ensure_ascii=False)}\n\n"
        f"Tarefas:\n{json.dumps(tasks[:12], ensure_ascii=False)}\n\n"
        f"Ações recentes:\n{json.dumps(actions, ensure_ascii=False)}"
    )
    return model_text(system, user_text, model=config.MODEL_SYNTHESIS, session_id=session_id)


def create_daily_briefing(session_id: str, source: str = "manual") -> dict:
    text = generate_daily_briefing_text(session_id)
    briefing = {
        "id": str(uuid4()),
        "source": source,
        "text": text,
        "created_at": datetime.now().isoformat(),
    }
    get_coworker_bucket("briefings", session_id).append(briefing)
    if not find_open_inbox_item(session_id, "briefing", briefing["id"]):
        create_inbox_item(
            session_id,
            "Briefing diário disponível",
            text,
            "briefing",
            priority="medium",
            related_id=briefing["id"],
            related_kind="briefing",
            action_text=f"Leia o briefing abaixo e execute a próxima ação recomendada com prioridade adequada.\n\n{text}",
            action_mode="operator",
        )
    persist_coworker_store()
    return briefing


def coworker_daily_report_text(session_id: str) -> str:
    tasks = list_coworker_tasks(session_id)
    projects = list_coworker_projects(session_id)
    objectives = list_coworker_objectives(session_id)
    actions = get_coworker_bucket("actions", session_id)
    today = datetime.now().date().isoformat()

    completed_today = [task for task in tasks if str(task.get("completed_at") or "").startswith(today)]
    failed_today = [task for task in tasks if task.get("status") == "failed" and str(task.get("updated_at") or "").startswith(today)]
    open_tasks = [task for task in tasks if task.get("status") in {"pending", "running", "blocked"}]
    high_priority = [task for task in open_tasks if task.get("priority") in {"critical", "high"}][:5]
    recent_actions = actions[-5:]

    lines = [
        f"Relatório do coworker para a sessão {session_id}",
        "",
        f"Projetos ativos: {len(projects)}",
        f"Objetivos ativos: {len([item for item in objectives if item.get('status') == 'active'])}",
        f"Tarefas em aberto: {len(open_tasks)}",
        f"Concluídas hoje: {len(completed_today)}",
        f"Falhas hoje: {len(failed_today)}",
        "",
        "Foco imediato:",
    ]
    if high_priority:
        for task in high_priority:
            lines.append(f"- [{task['priority']}] {task['text']}")
    else:
        lines.append("- Nenhuma tarefa crítica ou alta no momento.")

    lines.append("")
    lines.append("Últimas entregas:")
    if completed_today:
        for task in completed_today[-5:]:
            lines.append(f"- {task['text']}")
    else:
        lines.append("- Nenhuma entrega concluída hoje.")

    lines.append("")
    lines.append("Ações recentes:")
    if recent_actions:
        for action in recent_actions:
            lines.append(f"- {action['action_type']}")
    else:
        lines.append("- Nenhuma ação registrada.")

    lines.append("")
    lines.append("Próximo passo sugerido:")
    if open_tasks:
        next_task = sorted(
            open_tasks,
            key=lambda item: (priority_weight(item.get("priority", "medium")), item.get("created_at", "")),
        )[0]
        lines.append(f"- Executar: {next_task['text']}")
    else:
        lines.append("- Capturar novas tarefas ou rodar uma rotina.")
    return "\n".join(lines)


def route_command(command: str) -> str:  # noqa: PLR0911
    lowered = command.lower()

    # ── Clima ──────────────────────────────────────────────────────────────
    if any(term in lowered for term in [
        "clima", "tempo", "temperatura", "chuva", "umidade",
        "previsão", "previsao", "vento", "chove", "vai chover",
        "frio", "quente", "graus", "céu", "ceu", "nublado",
    ]):
        return "weather"

    # ── Hora / Data ────────────────────────────────────────────────────────
    if any(term in lowered for term in [
        "que horas", "que hora", "horário", "horario", "hora atual",
        "data de hoje", "data atual", "dia de hoje", "hoje é", "hoje e",
        "que dia é", "que dia e", "amanhã é", "amanha e",
    ]):
        return "time"

    # ── Frontend / Web ─────────────────────────────────────────────────────
    if any(term in lowered for term in [
        "website", "landing page", "html", "css", "site", "frontend",
        "react", "vue", "angular", "bootstrap", "tailwind",
        "interface web", "página web", "pagina web", "ui component",
    ]):
        return "web"

    # ── Código / Programação ───────────────────────────────────────────────
    if any(term in lowered for term in [
        "python", "javascript", "typescript", "fastapi", "node", "nodejs",
        "código", "codigo", "program", "script",
        "função", "funcao", "classe", "método", "metodo",
        "bug", "debug", "erro no código", "refactor", "otimize",
        "banco de dados", "database", "sql", "query", "algoritmo",
        "docker", "deploy", "git ", "endpoint", "api rest",
        "teste unitário", "teste automatizado",
    ]):
        return "code"

    # ── Planejamento / Gestão ──────────────────────────────────────────────
    if any(term in lowered for term in [
        "planeje", "planejar", "agenda", "cronograma", "organize", "roteiro", "roadmap",
        "sprint", "tarefa", "tarefas", "deadline", "backlog",
        "reunião", "reuniao", "entrega", "milestone",
        "gestão de", "gestao de", "prioridade das", "prioridades",
    ]):
        return "planning"

    # ── Estratégia / Negócio ───────────────────────────────────────────────
    if any(term in lowered for term in [
        "estratégia", "estrategia", "analise", "análise", "swot",
        "plano de negócio", "plano de negocio",
        "negócio", "negocio", "empresa", "mercado", "produto", "startup",
        "concorrência", "concorrencia", "decisão", "decisao",
        "investimento", "kpi", "métricas", "metricas", "okr", "priorizar",
    ]):
        return "strategy"

    # ── Educação / Explicação ──────────────────────────────────────────────
    if any(term in lowered for term in [
        "explique", "como funciona", "tutorial", "ensine", "o que é", "o que e",
        "aprenda", "aprender", "me ensine", "me explique",
        "definição", "definicao", "o que são", "o que sao",
        "diferença entre", "diferenca entre", "como usar",
        "resumo de", "documentação", "documentacao",
    ]):
        return "education"

    return "info"


def mode_preamble(mode: str) -> str:
    normalized = (mode or "builder").strip().lower()
    if normalized == "operator":
        return (
            "Modo operator ativo. "
            "Priorize análise, revisão, organização, evolução incremental, riscos e próximos passos pragmáticos."
        )
    return (
        "Modo builder ativo. "
        "Priorize criação de entregáveis, implementação, estrutura inicial e material utilizável."
    )


def ensure_module_enabled(module: str) -> None:
    if module not in config.ENABLED_MODULES:
        raise HTTPException(status_code=403, detail=f"Módulo '{module}' desabilitado.")


class WeatherAgent:
    @staticmethod
    async def get_info() -> dict:
        if not config.OPENWEATHER_API_KEY:
            return {
                "fallback": True,
                "temperature": 26,
                "humidity": 65,
                "description": "Dados reais indisponíveis sem OPENWEATHER_API_KEY",
                "location": config.LOCATION,
            }

        try:
            async with aiohttp.ClientSession() as session:
                url = (
                    "https://api.openweathermap.org/data/2.5/weather"
                    f"?lat={config.LAT}&lon={config.LON}&lang=pt_br&units=metric"
                    f"&appid={config.OPENWEATHER_API_KEY}"
                )
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return {
                        "temperature": data["main"]["temp"],
                        "humidity": data["main"]["humidity"],
                        "description": data["weather"][0]["description"],
                        "wind_speed": data["wind"]["speed"],
                        "pressure": data["main"]["pressure"],
                        "location": data["name"],
                        "timestamp": datetime.now().isoformat(),
                    }
        except Exception as exc:
            logger.warning("Falha ao consultar clima: %s", exc)
            return {
                "fallback": True,
                "temperature": 26,
                "humidity": 65,
                "description": "Falha ao consultar OpenWeather",
                "location": config.LOCATION,
            }


class CodeAgent:
    @staticmethod
    async def generate(prompt: str, session_id: Optional[str] = None) -> dict:
        system = (
            "Você é um engenheiro de software sênior. Sempre responda em português. "
            "Ao gerar código: use blocos markdown com a linguagem indicada, adicione comentários "
            "nas partes não óbvias, e explique brevemente o que o código faz e como usar. "
            "Se houver um bug, identifique a causa raiz antes de propor a correção. "
            "Prefira soluções simples e legíveis a soluções clevres demais."
        )
        return {"code": model_text(system, prompt, model=config.MODEL_PLANNER, session_id=session_id), "generated_at": datetime.now().isoformat()}


class PlanningAgent:
    @staticmethod
    async def create_schedule(requirements: str, session_id: Optional[str] = None) -> dict:
        system = (
            "Você é um gerente de projetos experiente. Sempre responda em português. "
            "Monte um plano estruturado com: objetivo claro, fases ou sprints, tarefas concretas "
            "por fase, estimativas de tempo, dependências, riscos e mitigações, e definição de "
            "pronto (done) para cada entrega. Seja específico e acionável."
        )
        return {"schedule": model_text(system, requirements, session_id=session_id), "created_at": datetime.now().isoformat()}


class WebAgent:
    @staticmethod
    async def create_website(requirements: str, session_id: Optional[str] = None) -> dict:
        system = (
            "Você é um desenvolvedor frontend sênior. Sempre responda em português. "
            "Entregue uma única página HTML completa, auto-contida, com CSS e JavaScript inline. "
            "Use design moderno, responsivo e acessível. Prefira variáveis CSS para cores e tipografia. "
            "Se o pedido for mais de código/estrutura, entregue também uma breve explicação das escolhas."
        )
        return {"html": model_text(system, requirements, model=config.MODEL_PLANNER, session_id=session_id), "created_at": datetime.now().isoformat()}


class EducationAgent:
    @staticmethod
    async def explain(topic: str, session_id: Optional[str] = None) -> dict:
        system = (
            "Você é um educador técnico experiente. Sempre responda em português. "
            "Estruture a explicação em: 1) Definição simples (1-2 frases), 2) Como funciona "
            "(mecanismo interno), 3) Exemplo prático com código ou analogia, "
            "4) Quando usar e quando NÃO usar, 5) Erros e armadilhas comuns. "
            "Adapte a profundidade ao nível de detalhe implícito na pergunta."
        )
        return {"explanation": model_text(system, topic, session_id=session_id), "created_at": datetime.now().isoformat()}


class StrategyAgent:
    @staticmethod
    async def analyze(context: str, session_id: Optional[str] = None) -> dict:
        system = (
            "Você é um estrategista de negócios e tecnologia. Sempre responda em português. "
            "Estruture a análise em: Diagnóstico (o que está acontecendo e por quê), "
            "Oportunidades e riscos principais, Opções estratégicas com trade-offs, "
            "Recomendação clara com justificativa, e Próximos 3 passos concretos. "
            "Seja direto, evite buzzwords e entregue insights acionáveis."
        )
        return {"strategy": model_text(system, context, model=config.MODEL_SYNTHESIS, session_id=session_id), "created_at": datetime.now().isoformat()}


class InfoAgent:
    @staticmethod
    async def answer(text: str, session_id: Optional[str] = None) -> str:
        system = (
            "Você é STOA, um assistente de trabalho inteligente. "
            "Responda de forma direta, clara e sempre em português. "
            "Quando a resposta tiver etapas, use uma lista numerada. "
            "Ao final, sugira um próximo passo prático quando isso agregar valor."
        )
        return model_text(system, text, session_id=session_id)


async def run_module(module: str, command: str, session_id: Optional[str] = None) -> AgentResponse:
    ensure_module_enabled(module)

    if module == "weather":
        weather_data = await WeatherAgent.get_info()
        response_text = format_weather(weather_data)
        return AgentResponse(
            response=response_text,
            action_type="info",
            module="weather",
            session_id=session_id,
            data=weather_data,
            artifact_path=save_artifact(session_id, module, response_text) if session_id and config.AUTO_SAVE_ARTIFACTS else None,
        )

    if module == "time":
        now = datetime.now()
        response_text = f"Hora: {now.strftime('%H:%M:%S')}\nData: {now.strftime('%Y-%m-%d')}"
        return AgentResponse(
            response=response_text,
            action_type="info",
            module="time",
            session_id=session_id,
            artifact_path=save_artifact(session_id, module, response_text) if session_id and config.AUTO_SAVE_ARTIFACTS else None,
        )

    if module == "code":
        code_data = await CodeAgent.generate(command, session_id=session_id)
        artifact_path = save_artifact(session_id, module, code_data["code"], command) if session_id and config.AUTO_SAVE_ARTIFACTS else None
        return AgentResponse(response=code_data["code"], action_type="code", module="code", session_id=session_id, data=code_data, artifact_path=artifact_path)

    if module == "planning":
        planning_data = await PlanningAgent.create_schedule(command, session_id=session_id)
        return AgentResponse(
            response=planning_data["schedule"],
            action_type="planning",
            module="planning",
            session_id=session_id,
            data=planning_data,
            artifact_path=save_artifact(session_id, module, planning_data["schedule"], command) if session_id and config.AUTO_SAVE_ARTIFACTS else None,
        )

    if module == "web":
        web_data = await WebAgent.create_website(command, session_id=session_id)
        return AgentResponse(
            response=web_data["html"],
            action_type="web",
            module="web",
            session_id=session_id,
            data=web_data,
            artifact_path=save_artifact(session_id, module, web_data["html"], command) if session_id and config.AUTO_SAVE_ARTIFACTS else None,
        )

    if module == "education":
        edu_data = await EducationAgent.explain(command, session_id=session_id)
        return AgentResponse(
            response=edu_data["explanation"],
            action_type="info",
            module="education",
            session_id=session_id,
            data=edu_data,
            artifact_path=save_artifact(session_id, module, edu_data["explanation"], command) if session_id and config.AUTO_SAVE_ARTIFACTS else None,
        )

    if module == "strategy":
        strategy_data = await StrategyAgent.analyze(command, session_id=session_id)
        return AgentResponse(
            response=strategy_data["strategy"],
            action_type="planning",
            module="strategy",
            session_id=session_id,
            data=strategy_data,
            artifact_path=save_artifact(session_id, module, strategy_data["strategy"], command) if session_id and config.AUTO_SAVE_ARTIFACTS else None,
        )

    response = await InfoAgent.answer(command, session_id=session_id)
    return AgentResponse(
        response=response,
        action_type="info",
        module="info",
        session_id=session_id,
        artifact_path=save_artifact(session_id, module, response, command) if session_id and config.AUTO_SAVE_ARTIFACTS else None,
    )


async def process_text(command: str, session_id: Optional[str] = None) -> AgentResponse:
    resolved_session_id = get_or_create_session_id(session_id)
    append_session_message(resolved_session_id, "user", command)
    module = route_command(command)
    response = await run_module(module, command, session_id=resolved_session_id)
    append_session_message(resolved_session_id, "assistant", response.response)
    return response


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def plan_super_task(command: str, session_id: Optional[str] = None, mode: str = "builder") -> SuperTaskPlan:
    system = f"""
Você é um planejador de execução de um super agente.
Crie um plano curto, seguro e útil.
Retorne APENAS JSON válido.

Formato obrigatório:
{{
  "mode": "single" ou "multi",
  "objective": "objetivo curto",
  "steps": [
    {{"module": "code|planning|web|education|strategy|weather|time|info", "prompt": "instrução da etapa", "goal": "resultado esperado", "output_file": "opcional/caminho.ext"}}
  ],
  "final_files": ["opcional/caminho.ext"]
}}

Regras:
- Use no máximo {config.MAX_PLAN_STEPS} etapas.
- Use apenas módulos permitidos.
- Se o pedido for simples, use uma etapa.
- Prefira planejamento antes de geração quando o pedido for amplo.
- Não invente ferramentas externas.
- Só sugira output_file ou final_files quando houver entregável final claro.
- {mode_preamble(mode)}
""".strip()

    data = model_json(system, command, model=config.MODEL_PLANNER, session_id=session_id)
    steps = data.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise RuntimeError("Plano vazio retornado pelo modelo.")

    normalized_steps: list[SuperTaskStep] = []
    for raw_step in steps[: config.MAX_PLAN_STEPS]:
        step = SuperTaskStep(**raw_step)
        ensure_module_enabled(step.module)
        normalized_steps.append(step)

    mode = "multi" if len(normalized_steps) > 1 else "single"
    return SuperTaskPlan(
        mode=mode,
        objective=str(data.get("objective") or command[:120]),
        steps=normalized_steps,
        final_files=[str(path) for path in (data.get("final_files") or []) if str(path).strip()],
    )


def maybe_save_step_output(session_id: str, step: SuperTaskStep, content: str) -> Optional[str]:
    if not step.output_file:
        return None
    return write_editable_file(session_id, step.output_file, content, overwrite=True)


def derive_final_file_content(plan: SuperTaskPlan, final_response: str, step_results: list[dict], target_file: str) -> str:
    lower_name = target_file.lower()
    if lower_name.endswith(".html"):
        for step in reversed(step_results):
            if step["module"] == "web":
                return step["full_response"]
    if lower_name.endswith(".py") or lower_name.endswith(".js"):
        for step in reversed(step_results):
            if step["module"] == "code":
                return step["full_response"]
    return final_response


async def execute_super_task(command: str, session_id: Optional[str] = None, mode: str = "builder") -> SuperTaskResult:
    resolved_session_id = get_or_create_session_id(session_id)
    append_session_message(resolved_session_id, "user", command)
    plan = plan_super_task(command, session_id=resolved_session_id, mode=mode)
    step_results: list[dict] = []
    artifact_paths: list[str] = []
    prior_context = ""

    for index, step in enumerate(plan.steps, start=1):
        step_prompt = step.prompt
        if prior_context:
            step_prompt = (
                f"Contexto anterior resumido:\n{prior_context}\n\n"
                f"Tarefa atual:\n{step.prompt}"
            )

        result = await run_module(step.module, step_prompt, session_id=resolved_session_id)
        compact_response = truncate_text(result.response, config.MAX_STEP_OUTPUT_CHARS)
        step_results.append(
            {
                "index": index,
                "module": step.module,
                "goal": step.goal,
                "response": compact_response,
                "artifact_path": result.artifact_path,
                "output_file": step.output_file,
                "full_response": result.response,
            }
        )
        if result.artifact_path:
            artifact_paths.append(result.artifact_path)
        step_file_path = maybe_save_step_output(resolved_session_id, step, result.response)
        if step_file_path:
            artifact_paths.append(step_file_path)
        prior_context += f"\nEtapa {index} ({step.module}) - {step.goal}:\n{compact_response}\n"

    synthesis_system = """
Você é o sintetizador final de um super agente.
Receba os resultados parciais e devolva uma resposta final coesa em português.
Se houver código ou HTML relevante, preserve em markdown.
Inclua um resumo executivo curto no início.
""".strip()
    synthesis_system = f"{synthesis_system}\n\n{mode_preamble(mode)}"
    synthesis_input = json.dumps(
        {
            "objective": plan.objective,
            "original_request": command,
            "steps": step_results,
        },
        ensure_ascii=False,
        indent=2,
    )
    final_response = model_text(
        synthesis_system,
        synthesis_input,
        model=config.MODEL_SYNTHESIS,
        session_id=resolved_session_id,
    )
    append_session_message(resolved_session_id, "assistant", final_response)
    final_artifact_path = save_artifact(resolved_session_id, "info", final_response, plan.objective)
    artifact_paths.append(final_artifact_path)
    for target_file in plan.final_files:
        saved_path = write_editable_file(
            resolved_session_id,
            target_file,
            derive_final_file_content(plan, final_response, step_results, target_file),
            overwrite=True,
        )
        artifact_paths.append(saved_path)
    return SuperTaskResult(
        objective=plan.objective,
        session_id=resolved_session_id,
        plan=[step.model_dump() for step in plan.steps],
        steps=[
            {key: value for key, value in step.items() if key != "full_response"}
            for step in step_results
        ],
        final_response=final_response,
        artifact_paths=list(dict.fromkeys(artifact_paths)),
    )


def format_weather(data: dict) -> str:
    return (
        f"Clima em {data.get('location', config.LOCATION)}\n"
        f"Temperatura: {data.get('temperature')}°C\n"
        f"Umidade: {data.get('humidity')}%\n"
        f"Condição: {data.get('description')}\n"
        f"Vento: {data.get('wind_speed', 'N/A')}\n"
        f"Pressão: {data.get('pressure', 'N/A')}"
    )


load_session_store()
load_preview_store()
load_coworker_store()


app = FastAPI(
    title="Safe STOA Agent",
    description="Versão endurecida do STOA Agent com Anthropic Claude API",
    version="2.0.0",
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS or ["127.0.0.1", "localhost"])
app.mount("/static", StaticFiles(directory="."), name="static")


async def register_websocket(websocket: WebSocket, session_id: Optional[str]) -> None:
    await websocket.accept()
    websocket_connections.append({"websocket": websocket, "session_id": session_id})


def unregister_websocket(websocket: WebSocket) -> None:
    websocket_connections[:] = [
        connection for connection in websocket_connections if connection["websocket"] is not websocket
    ]


async def broadcast_ws_event(event: dict, session_id: Optional[str] = None) -> None:
    stale_connections = []
    for connection in websocket_connections:
        if session_id and connection.get("session_id") not in {None, "", session_id}:
            continue
        try:
            await connection["websocket"].send_json(event)
        except Exception:
            stale_connections.append(connection["websocket"])

    for websocket in stale_connections:
        unregister_websocket(websocket)


async def broadcast_avatar_state(
    state: str,
    session_id: Optional[str] = None,
    detail: Optional[str] = None,
    source: str = "server",
) -> None:
    payload = {
        "type": "avatar_state",
        "state": state,
        "session_id": session_id,
        "source": source,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if detail:
        payload["detail"] = detail
    await broadcast_ws_event(payload, session_id=session_id)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = (websocket.query_params.get("token") or "").strip()
    session_id = (websocket.query_params.get("session_id") or "").strip() or None
    if token != config.ACCESS_TOKEN:
        await websocket.close(code=1008)
        return

    await register_websocket(websocket, session_id)
    await websocket.send_json(
        {
            "type": "avatar_state",
            "state": "idle",
            "session_id": session_id,
            "source": "server",
            "timestamp": datetime.utcnow().isoformat(),
            "detail": "Canal em tempo real conectado.",
        }
    )
    await websocket.send_json(
        {
            "type": "avatar_metrics",
            "session_id": session_id,
            "source": "server",
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {
                "connected": True,
                "active_connections": len(websocket_connections),
            },
        }
    )

    try:
        while True:
            message = await websocket.receive_json()
            event_type = (message or {}).get("type")
            if event_type == "avatar_state":
                requested_state = (message.get("state") or "idle").strip() or "idle"
                await broadcast_avatar_state(
                    requested_state,
                    session_id=session_id,
                    detail=message.get("detail"),
                    source="client",
                )
            elif event_type == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "session_id": session_id,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
    except WebSocketDisconnect:
        unregister_websocket(websocket)
    except Exception:
        unregister_websocket(websocket)


def next_pending_coworker_task(session_id: str) -> Optional[dict]:
    pending = [
        task
        for task in get_coworker_bucket("tasks", session_id)
        if task.get("status") in {"pending", "blocked"}
    ]
    if not pending:
        return None
    return sorted(
        pending,
        key=lambda item: (
            item.get("status") != "pending",
            priority_weight(item.get("priority", "medium")),
            item.get("created_at", ""),
        ),
    )[0]


def list_sessions_with_pending_coworker_tasks() -> list[str]:
    sessions = []
    for session_id, tasks in coworker_store.get("tasks", {}).items():
        if any(task.get("status") in {"pending", "blocked"} for task in tasks):
            sessions.append(session_id)
    return sessions


async def process_next_coworker_task_for_session(session_id: str) -> Optional[dict]:
    task = next_pending_coworker_task(session_id)
    if not task:
        return None

    update_coworker_task(session_id, task["id"], status="running", error=None)
    domain, persona = resolve_effective_persona(session_id, task["text"], task.get("project_id"))
    record_coworker_decision(
        session_id,
        task["id"],
        "Coworker selecionou a próxima tarefa com base em prioridade e ordem de chegada.",
        {"priority": task.get("priority"), "task_type": task.get("task_type"), "domain": domain, "persona": persona.get("label")},
    )
    try:
        result = await execute_orchestrator(session_id, task.get("mode", "builder"), task["text"])
        updated = update_coworker_task(
            session_id,
            task["id"],
            status="completed",
            result=result.model_dump(),
            notes=f"Ação executada: {result.action}",
        )
        if task.get("objective_id"):
            objective = get_coworker_objective(session_id, task["objective_id"])
            if objective:
                objective["last_progress_at"] = datetime.now().isoformat()
                related = [
                    item for item in get_coworker_bucket("tasks", session_id)
                    if item.get("objective_id") == objective["id"]
                ]
                if related and all(item.get("status") == "completed" for item in related):
                    objective["status"] = "completed"
                objective["updated_at"] = datetime.now().isoformat()
                persist_coworker_store()
        record_coworker_action(
            session_id,
            task["id"],
            "task_completed",
            {"action": result.action, "objective": result.objective},
        )
        if task.get("project_id"):
            for project in get_coworker_bucket("projects", session_id):
                if project["id"] == task["project_id"]:
                    project["last_activity_at"] = datetime.now().isoformat()
                    project["updated_at"] = datetime.now().isoformat()
                    persist_coworker_store()
                    break
            try:
                memory_update = infer_project_memory_update(
                    session_id,
                    task["project_id"],
                    task["text"],
                    result.model_dump(),
                )
                update_coworker_project_memory(
                    session_id,
                    task["project_id"],
                    memory_update.get("preferences", []),
                    memory_update.get("decisions", []),
                    memory_update.get("facts", []),
                    memory_update.get("working_style"),
                    replace=False,
                )
                record_coworker_action(
                    session_id,
                    task["id"],
                    "project_memory_updated",
                    {"project_id": task["project_id"]},
                )
            except Exception as exc:
                logger.warning("Falha ao atualizar memória do projeto %s: %s", task["project_id"], exc)
            try:
                status_update = infer_project_status_update(session_id, task["project_id"])
                update_coworker_project_status(
                    session_id,
                    task["project_id"],
                    status_update.get("phase"),
                    status_update.get("health"),
                    status_update.get("next_action"),
                    status_update.get("blockers", []),
                    status_update.get("risks", []),
                    replace=True,
                )
                recovery_task = ensure_recovery_task_for_project(session_id, task["project_id"])
                record_coworker_action(
                    session_id,
                    task["id"],
                    "project_status_updated",
                    {
                        "project_id": task["project_id"],
                        "recovery_task_id": recovery_task["id"] if recovery_task else None,
                    },
                )
            except Exception as exc:
                logger.warning("Falha ao atualizar status do projeto %s: %s", task["project_id"], exc)
        return updated
    except Exception as exc:
        updated = update_coworker_task(session_id, task["id"], status="failed", error=str(exc))
        record_coworker_action(session_id, task["id"], "task_failed", {"error": str(exc)})
        if task.get("project_id"):
            try:
                status_update = infer_project_status_update(session_id, task["project_id"])
                update_coworker_project_status(
                    session_id,
                    task["project_id"],
                    status_update.get("phase"),
                    status_update.get("health", "yellow"),
                    status_update.get("next_action"),
                    status_update.get("blockers", []),
                    merge_unique_text(status_update.get("risks", []), [f"Falha recente na tarefa: {task['text']}"], 15),
                    replace=True,
                )
                ensure_recovery_task_for_project(session_id, task["project_id"])
            except Exception as status_exc:
                logger.warning("Falha ao atualizar status após erro no projeto %s: %s", task["project_id"], status_exc)
        return updated


async def process_next_task_for_session(session_id: str) -> Optional[dict]:
    task = next_pending_task(session_id)
    if not task:
        return None

    update_task(session_id, task["id"], status="running")
    try:
        result = await execute_orchestrator(session_id, task["mode"], task["text"])
        updated = update_task(session_id, task["id"], status="completed", result=result.model_dump())
        return updated
    except Exception as exc:
        updated = update_task(session_id, task["id"], status="failed", error=str(exc))
        return updated


async def queue_worker_loop() -> None:
    global queue_worker_enabled
    while True:
        if queue_worker_enabled:
            for session_id in list_sessions_with_pending_coworker_tasks():
                try:
                    await process_next_coworker_task_for_session(session_id)
                except Exception as exc:
                    logger.warning("Coworker worker falhou para %s: %s", session_id, exc)
            for session_id in list_sessions_with_pending_tasks():
                try:
                    await process_next_task_for_session(session_id)
                except Exception as exc:
                    logger.warning("Queue worker falhou para %s: %s", session_id, exc)
        await asyncio.sleep(config.QUEUE_WORKER_INTERVAL_SECONDS)


async def project_supervisor_loop() -> None:
    global project_supervisor_enabled
    while True:
        if project_supervisor_enabled:
            for session_id, project_id in list_active_project_pairs():
                try:
                    result = run_project_supervisor(session_id, project_id)
                    project_supervisor_last_run[project_id] = datetime.now().isoformat()
                    if result.get("recovery_task"):
                        logger.info(
                            "Supervisor abriu/confirmou recovery task para projeto %s da sessão %s",
                            project_id,
                            session_id,
                        )
                except Exception as exc:
                    logger.warning("Project supervisor falhou para %s/%s: %s", session_id, project_id, exc)
        await asyncio.sleep(config.PROJECT_SUPERVISOR_INTERVAL_SECONDS)


async def daily_briefing_loop() -> None:
    global daily_briefing_enabled
    while True:
        if daily_briefing_enabled:
            today = datetime.now().date().isoformat()
            for session_id in list_sessions_with_active_projects():
                try:
                    latest = latest_briefing_for_session(session_id)
                    if latest and str(latest.get("created_at", "")).startswith(today):
                        continue
                    briefing = create_daily_briefing(session_id, source="worker")
                    daily_briefing_last_run[session_id] = briefing["created_at"]
                except Exception as exc:
                    logger.warning("Daily briefing falhou para %s: %s", session_id, exc)
        await asyncio.sleep(config.DAILY_BRIEFING_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(queue_worker_loop())
    asyncio.create_task(project_supervisor_loop())
    asyncio.create_task(daily_briefing_loop())


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    authorization = request.headers.get("Authorization", "")
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        try:
            check_rate_limit(request, authorization)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    external_csp = (
        "default-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com https://fonts.gstatic.com; "
        "connect-src 'self' https: http://127.0.0.1:18000 ws: wss:; "
        "img-src 'self' data: https:; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com;"
    )
    if request.url.path in {"/", "/stoa_remote.html", "/stoa_alive.html", "/static/stoa_mobile.html"}:
        response.headers["Content-Security-Policy"] = external_csp
    else:
        response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; img-src 'self' data:;"
    return response


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    injection = f'<script>window.__STOA_TOKEN__="{config.ACCESS_TOKEN}";</script>'
    return FRONTEND_HTML.replace("</head>", injection + "\n</head>", 1)


@app.get("/manifest.webmanifest")
async def manifest() -> JSONResponse:
    return JSONResponse(
        {
            "name": "STOA Agent",
            "short_name": "STOA",
            "description": "Interface operacional do STOA Agent para uso local e móvel.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#020812",
            "theme_color": "#06111d",
            "lang": "pt-BR",
            "icons": [
                {
                    "src": "/static/pwa-icons/icon-any.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any",
                },
                {
                    "src": "/static/pwa-icons/icon-maskable.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "maskable",
                },
            ],
        }
    )


@app.get("/sw.js")
async def service_worker() -> Response:
    return Response(
        content="""
const STOA_SHELL_CACHE = 'stoa-shell-v1';
const STOA_SHELL_ASSETS = [
  '/',
  '/manifest.webmanifest',
  '/static/pwa-icons/icon-any.svg',
  '/static/pwa-icons/icon-maskable.svg'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STOA_SHELL_CACHE).then(cache => cache.addAll(STOA_SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== STOA_SHELL_CACHE)
          .map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') {
    return;
  }

  const requestUrl = new URL(event.request.url);
  if (requestUrl.origin !== self.location.origin) {
    return;
  }

  if (requestUrl.pathname.startsWith('/api/') && requestUrl.pathname !== '/api/avatar-reference') {
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/') || Response.error())
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cachedResponse => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(event.request).then(networkResponse => {
        if (networkResponse && networkResponse.ok) {
          const responseClone = networkResponse.clone();
          caches.open(STOA_SHELL_CACHE).then(cache => cache.put(event.request, responseClone));
        }
        return networkResponse;
      });
    })
  );
});
""".strip(),
        media_type="application/javascript",
    )


@app.get("/stoa_remote.html")
async def stoa_remote() -> FileResponse:
    if not config.REMOTE_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="stoa_remote.html não encontrado.")
    return FileResponse(config.REMOTE_HTML_PATH)


@app.get("/stoa_alive.html")
async def stoa_alive() -> FileResponse:
    if not config.ALIVE_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="stoa_alive.html não encontrado.")
    return FileResponse(config.ALIVE_HTML_PATH)


@app.get("/control", response_class=HTMLResponse)
async def control_panel() -> str:
    return """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>STOA Control</title>
  <style>
    body { font-family: Segoe UI, Arial, sans-serif; background:#0f1720; color:#e6edf3; margin:0; padding:24px; }
    h1 { margin:0 0 8px; }
    p { color:#9fb3c8; margin:0 0 16px; }
    .grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:16px; }
    button { background:#1f6feb; color:white; border:none; padding:12px; border-radius:10px; cursor:pointer; font-weight:600; }
    button.alt { background:#238636; }
    button.warn { background:#b54708; }
    pre { white-space:pre-wrap; background:#0b1220; border:1px solid #2f3d4f; border-radius:12px; padding:16px; min-height:260px; }
  </style>
</head>
<body>
  <h1>STOA Control</h1>
  <p>Painel web simples para controlar o STOA local sem depender de HTA.</p>
  <input id="token" type="password" placeholder="Cole o STOA_ACCESS_TOKEN" style="width:100%;padding:12px;border-radius:10px;border:1px solid #2f3d4f;background:#111927;color:#e6edf3;margin-bottom:12px;">
  <div class="grid">
    <button onclick="runAction('status')">Atualizar Status</button>
    <button class="alt" onclick="window.open('/', '_blank')">Abrir Interface</button>
    <button onclick="runAction('start_supervisor')">Iniciar Supervisor</button>
    <button class="warn" onclick="runAction('stop_supervisor')">Parar Supervisor</button>
    <button onclick="runAction('start_voice')">Iniciar Voz</button>
    <button class="warn" onclick="runAction('stop_voice')">Parar Voz</button>
    <button onclick="runAction('enable_autostart')">Ativar no Logon</button>
    <button class="warn" onclick="runAction('disable_autostart')">Remover do Logon</button>
    <button onclick="runAction('create_web_shortcuts')">Criar Atalhos</button>
    <button class="warn" onclick="runAction('remove_web_shortcuts')">Remover Atalhos</button>
    <button onclick="runAction('refresh_workers')">Refresh Workers</button>
    <button onclick="runAction('install_status_bundle')">Instalar STOA</button>
  </div>
  <pre id="output">Aguardando ação.</pre>
  <script>
    const tokenInput = document.getElementById('token');
    const output = document.getElementById('output');
    tokenInput.value = sessionStorage.getItem('stoa_token') || '';
    async function api(url, options = {}) {
      const token = tokenInput.value.trim();
      if (!token) throw new Error('Informe o STOA_ACCESS_TOKEN.');
      sessionStorage.setItem('stoa_token', token);
      const response = await fetch(url, {
        ...options,
        headers: { ...(options.headers || {}), 'Authorization': `Bearer ${token}` }
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || JSON.stringify(data));
      return data;
    }
    async function runAction(action) {
      output.textContent = 'Processando...';
      try {
        const data = action === 'status'
          ? await api('/api/control/status')
          : await api('/api/control/action', {
              method:'POST',
              headers:{'Content-Type':'application/json'},
              body: JSON.stringify({ action })
            });
        output.textContent = JSON.stringify(data, null, 2);
      } catch (error) {
        output.textContent = String(error);
      }
    }
  </script>
</body>
</html>
"""


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "online",
        "agent": "Safe STOA Agent",
        "timestamp": datetime.now().isoformat(),
        "location": config.LOCATION,
    }


@app.get("/api/control/status", dependencies=[Depends(require_bearer_token)])
async def control_status_endpoint() -> dict:
    return control_status_snapshot()


@app.post("/api/control/action", dependencies=[Depends(require_bearer_token)])
async def control_action_endpoint(payload: SystemActionRequest, request: Request) -> dict:
    action_map = {
        "start_supervisor": "run-stoa-supervisor.ps1",
        "stop_supervisor": "stop-stoa-supervisor.ps1",
        "start_voice": "run-stoa-voice-daemon.ps1",
        "stop_voice": "stop-stoa-voice-daemon.ps1",
        "enable_autostart": "enable-stoa-autostart.ps1",
        "disable_autostart": "disable-stoa-autostart.ps1",
        "create_web_shortcuts": "install-stoa-web-shortcuts.ps1",
        "remove_web_shortcuts": "remove-stoa-web-shortcuts.ps1",
        "refresh_workers": "run-stoa-supervisor.ps1",
        "install_status_bundle": "install-stoa.ps1",
    }
    script_name = action_map.get(payload.action)
    if not script_name:
        raise HTTPException(status_code=400, detail="Ação de controle não permitida.")

    result = run_local_script(script_name)
    audit_log("control_action", request, {"action": payload.action, "script": script_name, "ok": result["ok"]})
    return {
        "action": payload.action,
        "result": result,
        "status": control_status_snapshot(),
    }


@app.post("/api/command", response_model=AgentResponse, dependencies=[Depends(require_bearer_token)])
async def command_endpoint(command: VoiceCommand, request: Request) -> AgentResponse:
    resolved_session_id = get_or_create_session_id(command.session_id)
    append_session_message(resolved_session_id, "user", command.text)
    control_action = classify_preview_control(command.text)

    async with get_preview_lock(resolved_session_id):
        pending_preview = get_pending_preview(resolved_session_id)

        if control_action == "apply":
            if not pending_preview:
                raise HTTPException(status_code=409, detail="Nenhum preview pendente para aplicar.")

            await broadcast_avatar_state("executing", session_id=resolved_session_id, detail="Aplicando preview pendente.")
            try:
                response = await run_module(
                    pending_preview.module,
                    pending_preview.prompt,
                    session_id=resolved_session_id,
                )
            except Exception as exc:
                clear_pending_preview(resolved_session_id)
                append_timeline_event(
                    resolved_session_id,
                    "preview_apply_failed",
                    {"preview_id": pending_preview.id, "error": str(exc)},
                )
                audit_log(
                    "command_preview_apply_failed",
                    request,
                    {"session_id": resolved_session_id, "preview_id": pending_preview.id, "module": pending_preview.module},
                )
                raise

            clear_pending_preview(resolved_session_id)
            append_session_message(resolved_session_id, "assistant", response.response)
            append_timeline_event(
                resolved_session_id,
                "preview_applied",
                {"preview_id": pending_preview.id, "module": pending_preview.module},
            )
            audit_log(
                "command_preview_applied",
                request,
                {"session_id": resolved_session_id, "preview_id": pending_preview.id, "module": pending_preview.module, "mode": pending_preview.mode},
            )
            await broadcast_avatar_state("responding", session_id=response.session_id, detail="Preview aplicado com sucesso.")
            response.action_type = "applied"
            response.data = {
                **(response.data or {}),
                "applied_preview": preview_public_payload(pending_preview),
            }
            return response

        if control_action == "cancel":
            if not pending_preview:
                raise HTTPException(status_code=409, detail="Nenhum preview pendente para cancelar.")

            cancelled_preview = clear_pending_preview(resolved_session_id)
            append_timeline_event(
                resolved_session_id,
                "preview_cancelled",
                {"preview_id": cancelled_preview.id, "module": cancelled_preview.module},
            )
            audit_log(
                "command_preview_cancelled",
                request,
                {"session_id": resolved_session_id, "preview_id": cancelled_preview.id, "module": cancelled_preview.module, "mode": cancelled_preview.mode},
            )
            await broadcast_avatar_state("responding", session_id=resolved_session_id, detail="Preview cancelado.")
            response_text = "Preview cancelado. Nenhuma ação foi aplicada."
            append_session_message(resolved_session_id, "assistant", response_text)
            return AgentResponse(
                response=response_text,
                action_type="cancelled",
                module=cancelled_preview.module,
                session_id=resolved_session_id,
                data={"cancelled_preview": preview_public_payload(cancelled_preview)},
            )

        if pending_preview:
            await broadcast_avatar_state("confirming", session_id=resolved_session_id, detail="Existe um preview pendente aguardando apply ou cancel.")
            response_text = (
                "Já existe um preview pendente para esta sessão. "
                "Use apply para executar exatamente a prévia atual ou cancel para descartá-la."
            )
            append_timeline_event(
                resolved_session_id,
                "preview_reused",
                {"preview_id": pending_preview.id, "module": pending_preview.module},
            )
            append_session_message(resolved_session_id, "assistant", response_text)
            audit_log(
                "command_preview_reused",
                request,
                {"session_id": resolved_session_id, "preview_id": pending_preview.id, "module": pending_preview.module, "mode": pending_preview.mode},
            )
            return AgentResponse(
                response=response_text,
                action_type="preview",
                module=pending_preview.module,
                session_id=resolved_session_id,
                data={"pending_preview": preview_public_payload(pending_preview)},
            )

        preview = build_command_preview(command, resolved_session_id)
        save_pending_preview(preview)
        append_timeline_event(
            resolved_session_id,
            "preview_created",
            {"preview_id": preview.id, "module": preview.module, "mode": preview.mode},
        )
        audit_log(
            "command_preview_created",
            request,
            {"session_id": resolved_session_id, "preview_id": preview.id, "module": preview.module, "mode": preview.mode},
        )
        await broadcast_avatar_state("confirming", session_id=resolved_session_id, detail="Preview pronto para apply ou cancel.")
        response_text = (
            f"Preview pronto.\n"
            f"Módulo orquestrado: {preview.module}\n"
            f"Pedido original: {preview.original_text}\n"
            "Responda com apply para executar exatamente esta prévia ou cancel para descartá-la."
        )
        append_session_message(resolved_session_id, "assistant", response_text)
        return AgentResponse(
            response=response_text,
            action_type="preview",
            module=preview.module,
            session_id=resolved_session_id,
            data={"pending_preview": preview_public_payload(preview)},
        )


@app.get("/api/pending-preview/{session_id}", dependencies=[Depends(require_bearer_token)])
async def pending_preview_endpoint(session_id: str) -> dict:
    preview = get_pending_preview(session_id)
    return {
        "session_id": session_id,
        "pending_preview": preview_public_payload(preview) if preview else None,
    }


@app.post("/api/super-command", response_model=SuperTaskResult, dependencies=[Depends(require_bearer_token)])
async def super_command_endpoint(command: VoiceCommand, request: Request) -> SuperTaskResult:
    resolved_session_id = get_or_create_session_id(command.session_id)
    await broadcast_avatar_state("executing", session_id=resolved_session_id, detail="Executando tarefa composta.")
    response = await execute_super_task(command.text, session_id=resolved_session_id, mode=command.mode)
    await broadcast_avatar_state("responding", session_id=response.session_id, detail="Plano e resposta consolidados.")
    audit_log("super_command", request, {"session_id": response.session_id, "steps": len(response.steps), "mode": command.mode})
    return response


@app.get("/api/session/{session_id}", dependencies=[Depends(require_bearer_token)])
async def session_endpoint(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "messages": get_session_history(session_id),
    }


@app.get("/api/files/{session_id}", dependencies=[Depends(require_bearer_token)])
async def files_endpoint(session_id: str) -> dict:
    session_dir = ensure_workspace_root() / session_id
    if not session_dir.exists():
        return {"session_id": session_id, "files": []}

    files = []
    for file_path in sorted(session_dir.iterdir()):
        if file_path.is_file():
            files.append(
                {
                    "name": file_path.name,
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                }
            )
    return {"session_id": session_id, "files": files}


@app.get("/api/file/{session_id}/{file_name}", dependencies=[Depends(require_bearer_token)])
async def file_content_endpoint(session_id: str, file_name: str) -> dict:
    session_dir = ensure_workspace_root() / session_id
    file_path = (session_dir / file_name).resolve()
    if not str(file_path).startswith(str(session_dir.resolve())):
        raise HTTPException(status_code=400, detail="Caminho inválido.")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return {
        "session_id": session_id,
        "name": file_path.name,
        "path": str(file_path),
        "content": file_path.read_text(encoding="utf-8"),
    }


@app.get("/api/editable-files/{session_id}", dependencies=[Depends(require_bearer_token)])
async def editable_files_endpoint(session_id: str) -> dict:
    editable_root = get_editable_root(session_id)
    files = []
    for file_path in editable_root.rglob("*"):
        if file_path.is_file():
            files.append(
                {
                    "name": file_path.name,
                    "relative_path": str(file_path.relative_to(editable_root)),
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                }
            )
    return {"session_id": session_id, "files": sorted(files, key=lambda item: item["relative_path"])}


@app.get("/api/project-tree/{session_id}", dependencies=[Depends(require_bearer_token)])
async def project_tree_endpoint(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "items": list_editable_tree(session_id),
    }


@app.post("/api/read-file", dependencies=[Depends(require_bearer_token)])
async def read_file_endpoint(request: FileReadRequest) -> dict:
    file_path, content = read_editable_file(request.session_id, request.relative_path)
    return {
        "session_id": request.session_id,
        "relative_path": request.relative_path,
        "path": str(file_path),
        "content": content,
    }


@app.post("/api/write-file", dependencies=[Depends(require_bearer_token)])
async def write_file_endpoint(payload: FileWriteRequest, request: Request) -> dict:
    file_path = write_editable_file(
        payload.session_id,
        payload.relative_path,
        payload.content,
        overwrite=payload.overwrite,
    )
    append_session_message(payload.session_id, "assistant", f"Arquivo salvo: {file_path}")
    audit_log("write_file", request, {"session_id": payload.session_id, "relative_path": payload.relative_path})
    return {
        "session_id": payload.session_id,
        "relative_path": payload.relative_path,
        "path": file_path,
    }


@app.post("/api/edit-file", dependencies=[Depends(require_bearer_token)])
async def edit_file_endpoint(payload: FileEditInstructionRequest, request: Request) -> dict:
    target_path = resolve_editable_path(payload.session_id, payload.relative_path)
    existing_content = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    system = (
        "Você é um editor de arquivos preciso. "
        "Retorne APENAS o conteúdo final completo do arquivo, sem explicações extras."
    )
    edited_content = model_text(
        system,
        build_file_edit_prompt(existing_content, payload.instruction, payload.relative_path),
        session_id=payload.session_id,
    )
    file_path = write_editable_file(
        payload.session_id,
        payload.relative_path,
        edited_content,
        overwrite=payload.overwrite,
    )
    append_session_message(payload.session_id, "assistant", f"Arquivo editado: {file_path}")
    audit_log("edit_file", request, {"session_id": payload.session_id, "relative_path": payload.relative_path})
    return {
        "session_id": payload.session_id,
        "relative_path": payload.relative_path,
        "path": file_path,
        "content": edited_content,
    }


@app.post("/api/review-file", dependencies=[Depends(require_bearer_token)])
async def review_file_endpoint(request: FileReviewInstructionRequest) -> dict:
    file_path, existing_content = read_editable_file(request.session_id, request.relative_path)
    system = (
        "Você é um revisor técnico e editor pragmático. "
        "Analise o arquivo com base no pedido do usuário. "
        "Responda em português com: problemas encontrados, melhorias sugeridas e uma proposta objetiva de próximo passo."
    )
    review = model_text(
        system,
        build_file_review_prompt(existing_content, request.instruction, request.relative_path),
        session_id=request.session_id,
    )
    append_session_message(request.session_id, "assistant", f"Arquivo revisado: {file_path}")
    return {
        "session_id": request.session_id,
        "relative_path": request.relative_path,
        "path": str(file_path),
        "review": review,
    }


@app.post("/api/project-summary", dependencies=[Depends(require_bearer_token)])
async def project_summary_endpoint(request: ProjectReadRequest) -> dict:
    files = []
    for relative_path in request.relative_paths[:20]:
        file_path, content = read_editable_file(request.session_id, relative_path)
        files.append(
            {
                "relative_path": relative_path,
                "path": str(file_path),
                "content": content,
            }
        )

    system = (
        "Você é um arquiteto e revisor técnico. "
        "Analise o conjunto de arquivos como um mini projeto. "
        "Explique estrutura, responsabilidades, lacunas, riscos e próximos passos em português."
    )
    summary = model_text(
        system,
        build_project_summary_prompt(files, request.instruction),
        session_id=request.session_id,
    )
    append_session_message(request.session_id, "assistant", "Resumo de projeto gerado.")
    return {
        "session_id": request.session_id,
        "files": [{"relative_path": item["relative_path"], "path": item["path"]} for item in files],
        "summary": summary,
    }


@app.post("/api/project-patch", dependencies=[Depends(require_bearer_token)])
async def project_patch_endpoint(request: ProjectPatchRequest, http_request: Request) -> dict:
    files = []
    allowed_paths = set()
    for relative_path in request.relative_paths[:20]:
        file_path, content = read_editable_file(request.session_id, relative_path)
        files.append(
            {
                "relative_path": relative_path,
                "path": str(file_path),
                "content": content,
            }
        )
        allowed_paths.add(relative_path)

    plan = plan_project_patch(files, request.instruction, request.session_id)
    results = []

    for step in plan.steps:
        if step.relative_path not in allowed_paths:
            raise HTTPException(status_code=400, detail=f"Plano tentou editar arquivo não permitido: {step.relative_path}")

        target_path, existing_content = read_editable_file(request.session_id, step.relative_path)
        system = (
            "Você é um editor de arquivos preciso. "
            "Retorne APENAS o conteúdo final completo do arquivo, sem explicações extras."
        )
        edited_content = model_text(
            system,
            build_file_edit_prompt(existing_content, step.instruction, step.relative_path),
            session_id=request.session_id,
        )
        saved_path = write_editable_file(
            request.session_id,
            step.relative_path,
            edited_content,
            overwrite=request.overwrite,
        )
        results.append(
            {
                "relative_path": step.relative_path,
                "path": saved_path,
                "instruction": step.instruction,
            }
        )

    append_session_message(request.session_id, "assistant", f"Project patch aplicado: {plan.objective}")
    audit_log(
        "project_patch",
        http_request,
        {"session_id": request.session_id, "steps": len(plan.steps), "files": request.relative_paths},
    )
    return {
        "session_id": request.session_id,
        "objective": plan.objective,
        "steps": [step.model_dump() for step in plan.steps],
        "results": results,
    }


@app.post("/api/autopilot", response_model=AutopilotResult, dependencies=[Depends(require_bearer_token)])
async def autopilot_endpoint(command: VoiceCommand, request: Request) -> AutopilotResult:
    resolved_session_id = get_or_create_session_id(command.session_id)
    await broadcast_avatar_state("executing", session_id=resolved_session_id, detail="Autopilot em execução.")
    decision = decide_autopilot(resolved_session_id, command.text, command.mode)

    if decision.mode == "project_patch":
        patch_request = ProjectPatchRequest(
            session_id=resolved_session_id,
            relative_paths=decision.relative_paths,
            instruction=decision.instruction or command.text,
            overwrite=True,
        )
        result = await project_patch_endpoint(patch_request, request)
    else:
        super_result = await execute_super_task(
            decision.prompt or command.text,
            session_id=resolved_session_id,
            mode=command.mode,
        )
        result = super_result.model_dump()

    audit_log(
        "autopilot",
        request,
        {"session_id": resolved_session_id, "mode": decision.mode, "objective": decision.objective},
    )
    await broadcast_avatar_state("responding", session_id=resolved_session_id, detail="Autopilot concluiu a resposta.")
    return AutopilotResult(
        session_id=resolved_session_id,
        mode=decision.mode,
        objective=decision.objective,
        result=result,
    )


@app.post("/api/orchestrate", response_model=OrchestratorResult, dependencies=[Depends(require_bearer_token)])
async def orchestrate_endpoint(payload: OrchestratorRequest, request: Request) -> OrchestratorResult:
    session_id = get_or_create_session_id(payload.session_id)
    await broadcast_avatar_state("executing", session_id=session_id, detail="Orchestrator em execução.")
    result = await execute_orchestrator(session_id, payload.mode, payload.text, request=request)
    await broadcast_avatar_state("responding", session_id=session_id, detail="Orchestrator concluiu o ciclo.")
    return result


@app.post("/api/coworker/intake", dependencies=[Depends(require_bearer_token)])
async def coworker_intake_endpoint(payload: CoworkerIntakeRequest, request: Request) -> dict:
    session_id = get_or_create_session_id(payload.session_id)
    await broadcast_avatar_state("executing", session_id=session_id, detail="Convertendo pedido em tarefa operacional.")
    intake = parse_coworker_intake(session_id, payload.text, payload.mode)
    project_id = intake.get("existing_project_id")

    if not project_id and intake.get("project_name") and intake.get("project_summary"):
        project = create_coworker_project(
            session_id,
            intake["project_name"],
            intake["project_summary"],
        )
        project_id = project["id"]
    else:
        project = next((item for item in list_coworker_projects(session_id) if item["id"] == project_id), None)

    objective = create_coworker_objective(
        session_id,
        intake.get("objective") or payload.text,
        mode=intake.get("mode", payload.mode),
        priority=intake.get("priority", "medium"),
        project_id=project_id,
        domain=intake.get("domain"),
    )
    task = create_coworker_task(
        session_id,
        intake.get("next_step") or intake.get("objective") or payload.text,
        mode=intake.get("mode", payload.mode),
        priority=intake.get("priority", "medium"),
        project_id=project_id,
        task_type=intake.get("task_type", "deliverable"),
        source="intake",
        objective_id=objective["id"],
    )
    record_coworker_decision(
        session_id,
        task["id"],
        "Pedido convertido em tarefa operacional do coworker.",
        intake,
    )
    audit_log(
        "coworker_intake",
        request,
        {"session_id": session_id, "task_id": task["id"], "project_id": project_id},
    )
    await broadcast_avatar_state("responding", session_id=session_id, detail="Coworker registrou a próxima ação.")
    return {
        "session_id": session_id,
        "project": project,
        "objective": objective,
        "persona_domain": intake.get("domain"),
        "task": task,
        "intake": intake,
    }


@app.post("/api/coworker/objective", dependencies=[Depends(require_bearer_token)])
async def coworker_objective_endpoint(payload: CoworkerObjectiveRequest, request: Request) -> dict:
    session_id = get_or_create_session_id(payload.session_id)
    domain, _persona = resolve_effective_persona(session_id, payload.objective, payload.project_id)
    objective = create_coworker_objective(
        session_id,
        payload.objective,
        mode=payload.mode,
        priority=payload.priority,
        project_id=payload.project_id,
        domain=domain,
    )
    audit_log("coworker_objective_create", request, {"session_id": session_id, "objective_id": objective["id"]})
    return {"session_id": session_id, "objective": objective}


@app.post("/api/coworker/objective/plan", dependencies=[Depends(require_bearer_token)])
async def coworker_objective_plan_endpoint(payload: CoworkerObjectivePlanRequest, request: Request) -> dict:
    objective = get_coworker_objective(payload.session_id, payload.objective_id)
    if not objective:
        raise HTTPException(status_code=404, detail="Objetivo não encontrado.")

    if payload.replace_pending:
        for task in get_coworker_bucket("tasks", payload.session_id):
            if task.get("objective_id") == payload.objective_id and task.get("status") == "pending":
                task["status"] = "cancelled"
                task["updated_at"] = datetime.now().isoformat()

    plan = plan_coworker_objective(
        payload.session_id,
        objective["objective"],
        objective.get("mode", "builder"),
        objective.get("project_id"),
    )
    created_tasks = []
    for milestone in plan.get("milestones", []):
        created_tasks.append(
            create_coworker_task(
                payload.session_id,
                milestone["task"],
                mode=milestone["mode"],
                priority=milestone["priority"],
                project_id=objective.get("project_id"),
                task_type=milestone["task_type"],
                source=f"objective:{objective['id']}",
                objective_id=objective["id"],
            )
        )

    objective["plan"] = plan.get("milestones", [])
    objective["planned_at"] = datetime.now().isoformat()
    objective["updated_at"] = datetime.now().isoformat()
    persist_coworker_store()
    record_coworker_decision(
        payload.session_id,
        None,
        "Objetivo de longo prazo quebrado em subtarefas executáveis.",
        {"objective_id": objective["id"], "milestones": objective["plan"]},
    )
    audit_log(
        "coworker_objective_plan",
        request,
        {"session_id": payload.session_id, "objective_id": objective["id"], "tasks_created": len(created_tasks)},
    )
    return {"session_id": payload.session_id, "objective": objective, "tasks": created_tasks, "plan": plan}


@app.get("/api/coworker/{session_id}/overview", dependencies=[Depends(require_bearer_token)])
async def coworker_overview_endpoint(session_id: str) -> dict:
    profile = get_coworker_profile(session_id)
    tasks = list_coworker_tasks(session_id)
    projects = list_coworker_projects(session_id)
    objectives = list_coworker_objectives(session_id)
    routines = get_coworker_routines(session_id)
    return {
        "session_id": session_id,
        "profile": profile,
        "personas": profile.get("personas", {}),
        "latest_briefing": latest_briefing_for_session(session_id),
        "inbox": list_inbox_items(session_id),
        "projects": [
            {
                **project,
                "status_snapshot": {
                    "phase": project.get("phase", "discovery"),
                    "health": project.get("health", "green"),
                    "next_action": project.get("next_action", ""),
                    "blockers": project.get("blockers", []),
                    "risks": project.get("risks", []),
                    "recovery_task_id": (
                        find_open_recovery_task(session_id, project["id"])["id"]
                        if find_open_recovery_task(session_id, project["id"])
                        else None
                    ),
                },
            }
            for project in projects
        ],
        "objectives": objectives,
        "tasks": tasks,
        "routines": routines,
        "report": coworker_daily_report_text(session_id),
    }


@app.get("/api/coworker/tasks/{session_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_tasks_endpoint(session_id: str) -> dict:
    return {"session_id": session_id, "tasks": list_coworker_tasks(session_id)}


@app.get("/api/coworker/inbox/{session_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_inbox_endpoint(session_id: str) -> dict:
    return {"session_id": session_id, "items": list_inbox_items(session_id)}


@app.post("/api/coworker/inbox/status", dependencies=[Depends(require_bearer_token)])
async def coworker_inbox_status_endpoint(payload: InboxItemUpdateRequest, request: Request) -> dict:
    item = update_inbox_item_status(payload.session_id, payload.item_id, payload.status)
    if not item:
        raise HTTPException(status_code=404, detail="Item da inbox não encontrado.")
    audit_log("coworker_inbox_status", request, {"session_id": payload.session_id, "item_id": payload.item_id, "status": item["status"]})
    return {"session_id": payload.session_id, "item": item}


@app.post("/api/coworker/inbox/execute", dependencies=[Depends(require_bearer_token)])
async def coworker_inbox_execute_endpoint(payload: InboxItemExecuteRequest, request: Request) -> dict:
    item = get_inbox_item(payload.session_id, payload.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item da inbox não encontrado.")

    command_text = item.get("action_text", "").strip() or item.get("body", "").strip()
    if not command_text:
        raise HTTPException(status_code=400, detail="Item da inbox sem ação executável.")

    task = create_coworker_task(
        payload.session_id,
        command_text,
        mode=item.get("action_mode", "operator"),
        priority=item.get("priority", "medium"),
        project_id=item.get("related_id") if item.get("related_kind") == "project" else None,
        task_type=f"inbox_{item.get('item_type', 'item')}",
        source=f"inbox:{item['id']}",
    )
    result = await process_next_coworker_task_for_session(payload.session_id)
    updated_item = update_inbox_item_status(payload.session_id, payload.item_id, "done")
    audit_log(
        "coworker_inbox_execute",
        request,
        {"session_id": payload.session_id, "item_id": payload.item_id, "task_id": task["id"]},
    )
    return {"session_id": payload.session_id, "item": updated_item, "task": task, "result": result}


@app.post("/api/coworker/project", dependencies=[Depends(require_bearer_token)])
async def coworker_project_endpoint(payload: CoworkerProjectRequest, request: Request) -> dict:
    session_id = get_or_create_session_id(payload.session_id)
    project = create_coworker_project(
        session_id,
        payload.name,
        payload.summary,
        root_alias=payload.root_alias,
        relative_path=payload.relative_path,
    )
    audit_log("coworker_project_create", request, {"session_id": session_id, "project_id": project["id"]})
    return {"session_id": session_id, "project": project}


@app.get("/api/coworker/profile/{session_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_profile_get_endpoint(session_id: str) -> dict:
    profile = get_coworker_profile(session_id)
    return {"session_id": session_id, "profile": profile, "identity_text": coworker_identity_text(session_id)}


@app.post("/api/coworker/profile", dependencies=[Depends(require_bearer_token)])
async def coworker_profile_update_endpoint(payload: CoworkerProfileRequest, request: Request) -> dict:
    profile = update_coworker_profile(
        payload.session_id,
        payload.name,
        payload.role,
        payload.mission,
        payload.decision_rules,
        payload.strengths,
        payload.default_mode,
        payload.communication_style,
        replace=payload.replace,
    )
    audit_log("coworker_profile_update", request, {"session_id": payload.session_id})
    return {
        "session_id": payload.session_id,
        "profile": profile,
        "identity_text": coworker_identity_text(payload.session_id),
    }


@app.post("/api/coworker/persona", dependencies=[Depends(require_bearer_token)])
async def coworker_persona_update_endpoint(payload: CoworkerPersonaRequest, request: Request) -> dict:
    persona = update_coworker_persona(
        payload.session_id,
        payload.domain,
        payload.label,
        payload.role,
        payload.mission,
        payload.decision_rules,
        payload.strengths,
        payload.default_mode,
        payload.communication_style,
    )
    audit_log("coworker_persona_update", request, {"session_id": payload.session_id, "domain": persona["domain"]})
    return {
        "session_id": payload.session_id,
        "persona": persona,
        "persona_text": coworker_persona_text(payload.session_id, payload.domain),
    }


@app.get("/api/coworker/project-memory/{session_id}/{project_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_project_memory_get_endpoint(session_id: str, project_id: str) -> dict:
    project = get_coworker_project(session_id, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    return {
        "session_id": session_id,
        "project_id": project_id,
        "memory_text": coworker_project_memory_text(session_id, project_id),
        "memory": {
            "preferences": project.get("preferences", []),
            "decisions": project.get("decisions", []),
            "facts": project.get("facts", []),
            "working_style": project.get("working_style", ""),
        },
    }


@app.get("/api/coworker/project-status/{session_id}/{project_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_project_status_get_endpoint(session_id: str, project_id: str) -> dict:
    project = get_coworker_project(session_id, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    return {
        "session_id": session_id,
        "project_id": project_id,
        "status": {
            "phase": project.get("phase", "discovery"),
            "health": project.get("health", "green"),
            "next_action": project.get("next_action", ""),
            "blockers": project.get("blockers", []),
            "risks": project.get("risks", []),
            "last_activity_at": project.get("last_activity_at"),
        },
    }


@app.post("/api/coworker/supervisor/{session_id}/{project_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_project_supervisor_endpoint(session_id: str, project_id: str, request: Request) -> dict:
    data = run_project_supervisor(session_id, project_id)
    audit_log("coworker_project_supervisor", request, {"session_id": session_id, "project_id": project_id})
    return {"session_id": session_id, "project_id": project_id, **data}


@app.post("/api/coworker/project-status", dependencies=[Depends(require_bearer_token)])
async def coworker_project_status_update_endpoint(payload: CoworkerProjectStatusRequest, request: Request) -> dict:
    project = update_coworker_project_status(
        payload.session_id,
        payload.project_id,
        payload.phase,
        payload.health,
        payload.next_action,
        payload.blockers,
        payload.risks,
        replace=payload.replace,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    recovery_task = ensure_recovery_task_for_project(payload.session_id, payload.project_id)
    audit_log(
        "coworker_project_status_update",
        request,
        {"session_id": payload.session_id, "project_id": payload.project_id},
    )
    return {"session_id": payload.session_id, "project": project, "recovery_task": recovery_task}


@app.post("/api/coworker/project-memory", dependencies=[Depends(require_bearer_token)])
async def coworker_project_memory_update_endpoint(payload: CoworkerProjectMemoryRequest, request: Request) -> dict:
    project = update_coworker_project_memory(
        payload.session_id,
        payload.project_id,
        payload.preferences,
        payload.decisions,
        payload.facts,
        payload.working_style,
        replace=payload.replace,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    audit_log(
        "coworker_project_memory_update",
        request,
        {"session_id": payload.session_id, "project_id": payload.project_id},
    )
    return {
        "session_id": payload.session_id,
        "project": project,
        "memory_text": coworker_project_memory_text(payload.session_id, payload.project_id),
    }


@app.post("/api/coworker/task", dependencies=[Depends(require_bearer_token)])
async def coworker_task_endpoint(payload: CoworkerTaskRequest, request: Request) -> dict:
    session_id = get_or_create_session_id(payload.session_id)
    task = create_coworker_task(
        session_id,
        payload.text,
        mode=payload.mode,
        priority=payload.priority,
        project_id=payload.project_id,
        task_type=payload.task_type,
    )
    audit_log("coworker_task_create", request, {"session_id": session_id, "task_id": task["id"]})
    return {"session_id": session_id, "task": task}


@app.post("/api/coworker/task/update", dependencies=[Depends(require_bearer_token)])
async def coworker_task_update_endpoint(payload: CoworkerTaskUpdateRequest, request: Request) -> dict:
    task = update_coworker_task(
        payload.session_id,
        payload.task_id,
        status=payload.status,
        priority=payload.priority,
        notes=payload.notes,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa do coworker não encontrada.")
    audit_log("coworker_task_update", request, {"session_id": payload.session_id, "task_id": payload.task_id})
    return {"session_id": payload.session_id, "task": task}


@app.post("/api/coworker/routine", dependencies=[Depends(require_bearer_token)])
async def coworker_routine_endpoint(payload: CoworkerRoutineRequest, request: Request) -> dict:
    session_id = get_or_create_session_id(payload.session_id)
    routine = create_coworker_routine(
        session_id,
        payload.name,
        payload.prompt,
        mode=payload.mode,
        priority=payload.priority,
        project_id=payload.project_id,
        trigger=payload.trigger,
        enabled=payload.enabled,
    )
    audit_log("coworker_routine_create", request, {"session_id": session_id, "routine_id": routine["id"]})
    return {"session_id": session_id, "routine": routine}


@app.post("/api/coworker/routine/run/{session_id}/{routine_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_routine_run_endpoint(session_id: str, routine_id: str, request: Request) -> dict:
    data = run_coworker_routine(session_id, routine_id)
    audit_log("coworker_routine_run", request, {"session_id": session_id, "routine_id": routine_id})
    return {"session_id": session_id, **data}


@app.post("/api/coworker/run-next/{session_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_run_next_endpoint(session_id: str, request: Request) -> dict:
    task = await process_next_coworker_task_for_session(session_id)
    if not task:
        return {"session_id": session_id, "message": "Nenhuma tarefa pendente do coworker.", "task": None}
    audit_log("coworker_run_next", request, {"session_id": session_id, "task_id": task["id"], "status": task["status"]})
    return {"session_id": session_id, "task": task}


@app.get("/api/coworker/daily-report/{session_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_daily_report_endpoint(session_id: str) -> dict:
    return {"session_id": session_id, "report": coworker_daily_report_text(session_id)}


@app.get("/api/coworker/briefing/{session_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_latest_briefing_endpoint(session_id: str) -> dict:
    return {"session_id": session_id, "briefing": latest_briefing_for_session(session_id)}


@app.post("/api/coworker/briefing/{session_id}", dependencies=[Depends(require_bearer_token)])
async def coworker_create_briefing_endpoint(session_id: str, request: Request) -> dict:
    briefing = create_daily_briefing(session_id, source="manual")
    audit_log("coworker_briefing_create", request, {"session_id": session_id, "briefing_id": briefing["id"]})
    return {"session_id": session_id, "briefing": briefing}


@app.post("/api/queue-task", dependencies=[Depends(require_bearer_token)])
async def queue_task_endpoint(payload: QueueTaskRequest, request: Request) -> dict:
    session_id = get_or_create_session_id(payload.session_id)
    task = enqueue_task(session_id, payload.mode, payload.text)
    audit_log("queue_task", request, {"session_id": session_id, "task_id": task["id"]})
    return {"session_id": session_id, "task": task}


@app.get("/api/queue/{session_id}", dependencies=[Depends(require_bearer_token)])
async def queue_list_endpoint(session_id: str) -> dict:
    return {"session_id": session_id, "tasks": get_session_queue(session_id)}


@app.post("/api/queue-run-next/{session_id}", dependencies=[Depends(require_bearer_token)])
async def queue_run_next_endpoint(session_id: str, request: Request) -> dict:
    task = next_pending_task(session_id)
    if not task:
        return {"session_id": session_id, "message": "Nenhuma tarefa pendente.", "task": None}

    update_task(session_id, task["id"], status="running")
    try:
        result = await orchestrate_endpoint(
            OrchestratorRequest(session_id=session_id, mode=task["mode"], text=task["text"]),
            request,
        )
        update_task(session_id, task["id"], status="completed", result=result.model_dump())
        audit_log("queue_run_next", request, {"session_id": session_id, "task_id": task["id"], "status": "completed"})
        return {"session_id": session_id, "task": update_task(session_id, task["id"])}
    except Exception as exc:
        update_task(session_id, task["id"], status="failed", error=str(exc))
        audit_log("queue_run_next", request, {"session_id": session_id, "task_id": task["id"], "status": "failed"})
        raise


@app.get("/api/queue-worker", dependencies=[Depends(require_bearer_token)])
async def queue_worker_status_endpoint() -> dict:
    return {
        "enabled": queue_worker_enabled,
        "interval_seconds": config.QUEUE_WORKER_INTERVAL_SECONDS,
    }


@app.get("/api/project-supervisor-worker", dependencies=[Depends(require_bearer_token)])
async def project_supervisor_worker_status_endpoint() -> dict:
    return {
        "enabled": project_supervisor_enabled,
        "interval_seconds": config.PROJECT_SUPERVISOR_INTERVAL_SECONDS,
        "active_projects": len(list_active_project_pairs()),
        "last_run": project_supervisor_last_run,
    }


@app.post("/api/queue-worker/start", dependencies=[Depends(require_bearer_token)])
async def queue_worker_start_endpoint(request: Request) -> dict:
    global queue_worker_enabled
    queue_worker_enabled = True
    audit_log("queue_worker_start", request, {})
    return {"enabled": queue_worker_enabled}


@app.post("/api/queue-worker/stop", dependencies=[Depends(require_bearer_token)])
async def queue_worker_stop_endpoint(request: Request) -> dict:
    global queue_worker_enabled
    queue_worker_enabled = False
    audit_log("queue_worker_stop", request, {})
    return {"enabled": queue_worker_enabled}


@app.post("/api/project-supervisor-worker/start", dependencies=[Depends(require_bearer_token)])
async def project_supervisor_worker_start_endpoint(request: Request) -> dict:
    global project_supervisor_enabled
    project_supervisor_enabled = True
    audit_log("project_supervisor_worker_start", request, {})
    return {"enabled": project_supervisor_enabled}


@app.post("/api/project-supervisor-worker/stop", dependencies=[Depends(require_bearer_token)])
async def project_supervisor_worker_stop_endpoint(request: Request) -> dict:
    global project_supervisor_enabled
    project_supervisor_enabled = False
    audit_log("project_supervisor_worker_stop", request, {})
    return {"enabled": project_supervisor_enabled}


@app.get("/api/daily-briefing-worker", dependencies=[Depends(require_bearer_token)])
async def daily_briefing_worker_status_endpoint() -> dict:
    return {
        "enabled": daily_briefing_enabled,
        "interval_seconds": config.DAILY_BRIEFING_INTERVAL_SECONDS,
        "active_sessions": len(list_sessions_with_active_projects()),
        "last_run": daily_briefing_last_run,
    }


@app.post("/api/daily-briefing-worker/start", dependencies=[Depends(require_bearer_token)])
async def daily_briefing_worker_start_endpoint(request: Request) -> dict:
    global daily_briefing_enabled
    daily_briefing_enabled = True
    audit_log("daily_briefing_worker_start", request, {})
    return {"enabled": daily_briefing_enabled}


@app.post("/api/daily-briefing-worker/stop", dependencies=[Depends(require_bearer_token)])
async def daily_briefing_worker_stop_endpoint(request: Request) -> dict:
    global daily_briefing_enabled
    daily_briefing_enabled = False
    audit_log("daily_briefing_worker_stop", request, {})
    return {"enabled": daily_briefing_enabled}


@app.post("/api/run-command", dependencies=[Depends(require_bearer_token)])
async def run_command_endpoint(payload: TerminalCommandRequest, request: Request) -> dict:
    tokens = parse_command_tokens(payload.command)
    if not command_is_allowed(tokens):
        raise HTTPException(status_code=403, detail="Comando não permitido pela allowlist.")

    cwd = resolve_allowed_cwd(payload.session_id, payload.cwd)
    try:
        result = subprocess.run(
            tokens,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=config.TERMINAL_TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        audit_log("run_command_timeout", request, {"session_id": payload.session_id, "command": tokens})
        raise HTTPException(status_code=408, detail="Comando excedeu o tempo limite.")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Executável não encontrado.")

    append_session_message(payload.session_id, "assistant", f"Comando executado: {' '.join(tokens)}")
    audit_log(
        "run_command",
        request,
        {"session_id": payload.session_id, "command": tokens, "returncode": result.returncode, "cwd": str(cwd)},
    )
    return {
        "session_id": payload.session_id,
        "command": tokens,
        "cwd": str(cwd),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.post("/api/launch-app", dependencies=[Depends(require_bearer_token)])
async def launch_app_endpoint(payload: AppLaunchRequest, request: Request) -> dict:
    base_command = resolve_app_command(payload.app)
    command = base_command + payload.args
    try:
        process = subprocess.Popen(command)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="App permitido, mas executável não foi encontrado no sistema.")

    append_session_message(payload.session_id, "assistant", f"App iniciado: {payload.app}")
    audit_log(
        "launch_app",
        request,
        {"session_id": payload.session_id, "app": payload.app, "args": payload.args, "pid": process.pid},
    )
    return {
        "session_id": payload.session_id,
        "app": payload.app,
        "args": payload.args,
        "pid": process.pid,
    }


@app.post("/api/open-workspace", dependencies=[Depends(require_bearer_token)])
async def open_workspace_endpoint(payload: WorkspaceOpenRequest, request: Request) -> dict:
    normalized_app = payload.app.strip().lower()
    if normalized_app not in {"code", "cursor"}:
        raise HTTPException(status_code=403, detail="Abertura de workspace permitida apenas para 'code' ou 'cursor'.")

    target_path = resolve_workspace_target(payload.session_id, payload.relative_path, root_alias=payload.root_alias)
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Workspace/caminho não encontrado.")

    command = resolve_app_command(normalized_app) + [str(target_path)]
    try:
        process = subprocess.Popen(command)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Editor permitido, mas executável não foi encontrado no sistema.")

    append_session_message(payload.session_id, "assistant", f"Workspace aberto no {normalized_app}: {target_path}")
    audit_log(
        "open_workspace",
        request,
        {"session_id": payload.session_id, "app": normalized_app, "target_path": str(target_path), "root_alias": payload.root_alias, "pid": process.pid},
    )
    return {
        "session_id": payload.session_id,
        "app": normalized_app,
        "target_path": str(target_path),
        "pid": process.pid,
    }


@app.post("/api/create-spreadsheet", dependencies=[Depends(require_bearer_token)])
async def create_spreadsheet_endpoint(payload: SpreadsheetCreateRequest, request: Request) -> dict:
    csv_path = create_csv_spreadsheet(payload.session_id, payload.relative_path, payload.rows, root_alias=payload.root_alias)
    excel_pid = None

    if payload.open_in_excel:
        command = resolve_app_command("excel") + [csv_path]
        try:
            process = subprocess.Popen(command)
            excel_pid = process.pid
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Excel permitido, mas executável não foi encontrado no sistema.")

    append_session_message(payload.session_id, "assistant", f"Planilha criada: {csv_path}")
    audit_log(
        "create_spreadsheet",
        request,
        {
            "session_id": payload.session_id,
            "path": csv_path,
            "rows": len(payload.rows),
            "open_in_excel": payload.open_in_excel,
            "root_alias": payload.root_alias,
            "excel_pid": excel_pid,
        },
    )
    return {
        "session_id": payload.session_id,
        "path": csv_path,
        "rows": len(payload.rows),
        "excel_pid": excel_pid,
    }


@app.post("/api/create-excel-workbook", dependencies=[Depends(require_bearer_token)])
async def create_excel_workbook_endpoint(payload: ExcelWorkbookRequest, request: Request) -> dict:
    workbook_path = create_excel_workbook(
        payload.session_id,
        payload.relative_path,
        payload.sheets,
        payload.open_in_excel,
        root_alias=payload.root_alias,
    )
    append_session_message(payload.session_id, "assistant", f"Workbook Excel criado: {workbook_path}")
    audit_log(
        "create_excel_workbook",
        request,
        {
            "session_id": payload.session_id,
            "path": workbook_path,
            "sheets": len(payload.sheets),
            "open_in_excel": payload.open_in_excel,
            "root_alias": payload.root_alias,
        },
    )
    return {
        "session_id": payload.session_id,
        "path": workbook_path,
        "sheets": len(payload.sheets),
    }


@app.post("/api/update-excel-cell", dependencies=[Depends(require_bearer_token)])
async def update_excel_cell_endpoint(payload: ExcelCellUpdateRequest, request: Request) -> dict:
    workbook_path = update_excel_cell(
        payload.session_id,
        payload.relative_path,
        payload.sheet_name,
        payload.cell,
        payload.value,
        payload.open_in_excel,
        root_alias=payload.root_alias,
    )
    append_session_message(payload.session_id, "assistant", f"Célula atualizada em workbook Excel: {workbook_path}")
    audit_log(
        "update_excel_cell",
        request,
        {
            "session_id": payload.session_id,
            "path": workbook_path,
            "sheet_name": payload.sheet_name,
            "cell": payload.cell,
            "root_alias": payload.root_alias,
        },
    )
    return {
        "session_id": payload.session_id,
        "path": workbook_path,
        "sheet_name": payload.sheet_name,
        "cell": payload.cell,
    }


@app.post("/api/open-file-in-editor", dependencies=[Depends(require_bearer_token)])
async def open_file_in_editor_endpoint(payload: EditorOpenFileRequest, request: Request) -> dict:
    normalized_app = payload.app.strip().lower()
    if normalized_app not in {"code", "cursor"}:
        raise HTTPException(status_code=403, detail="Abertura de arquivo permitida apenas para 'code' ou 'cursor'.")

    target_path = resolve_workspace_target(payload.session_id, payload.relative_path, root_alias=payload.root_alias)
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    command = resolve_app_command(normalized_app) + [str(target_path)]
    try:
        process = subprocess.Popen(command)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Editor permitido, mas executável não foi encontrado no sistema.")

    append_session_message(payload.session_id, "assistant", f"Arquivo aberto no {normalized_app}: {target_path}")
    audit_log(
        "open_file_in_editor",
        request,
        {"session_id": payload.session_id, "app": normalized_app, "target_path": str(target_path), "root_alias": payload.root_alias, "pid": process.pid},
    )
    return {
        "session_id": payload.session_id,
        "app": normalized_app,
        "target_path": str(target_path),
        "pid": process.pid,
    }


@app.post("/api/prepare-editor-task", dependencies=[Depends(require_bearer_token)])
async def prepare_editor_task_endpoint(payload: EditorTaskRequest, request: Request) -> dict:
    normalized_app = payload.app.strip().lower()
    if normalized_app not in {"code", "cursor"}:
        raise HTTPException(status_code=403, detail="Preparação de tarefa permitida apenas para 'code' ou 'cursor'.")

    workspace_path = resolve_workspace_target(payload.session_id, payload.workspace_relative_path, root_alias=payload.root_alias)
    workspace_path.mkdir(parents=True, exist_ok=True)

    brief_relative_path = str(Path(payload.workspace_relative_path) / "JARVIS_TASK.md").replace("\\", "/")
    brief_content = build_editor_task_markdown(payload.task, str(workspace_path))
    brief_path = write_workspace_file(payload.session_id, brief_relative_path, brief_content, overwrite=True, root_alias=payload.root_alias)

    command = resolve_app_command(normalized_app) + [str(workspace_path)]
    try:
        process = subprocess.Popen(command)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Editor permitido, mas executável não foi encontrado no sistema.")

    append_session_message(payload.session_id, "assistant", f"Tarefa preparada para editor: {brief_path}")
    audit_log(
        "prepare_editor_task",
        request,
        {
            "session_id": payload.session_id,
            "app": normalized_app,
            "workspace_path": str(workspace_path),
            "brief_path": brief_path,
            "root_alias": payload.root_alias,
            "pid": process.pid,
        },
    )
    return {
        "session_id": payload.session_id,
        "app": normalized_app,
        "workspace_path": str(workspace_path),
        "brief_path": brief_path,
        "pid": process.pid,
    }


@app.post("/api/open-url", dependencies=[Depends(require_bearer_token)])
async def open_url_endpoint(payload: BrowserOpenUrlRequest, request: Request) -> dict:
    url = validate_allowed_url(payload.url)
    command = resolve_browser_command(payload.browser) + [url]
    try:
        process = subprocess.Popen(command)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Browser permitido, mas executável não foi encontrado no sistema.")

    append_session_message(payload.session_id, "assistant", f"URL aberta no browser: {url}")
    audit_log(
        "open_url",
        request,
        {"session_id": payload.session_id, "browser": payload.browser, "url": url, "pid": process.pid},
    )
    return {
        "session_id": payload.session_id,
        "browser": payload.browser,
        "url": url,
        "pid": process.pid,
    }


@app.post("/api/prepare-browser-task", dependencies=[Depends(require_bearer_token)])
async def prepare_browser_task_endpoint(payload: BrowserTaskRequest, request: Request) -> dict:
    url = validate_allowed_url(payload.url)
    brief_relative_path = "browser/JARVIS_BROWSER_TASK.md"
    brief_content = build_browser_task_markdown(payload.task, url)
    brief_path = write_workspace_file(payload.session_id, brief_relative_path, brief_content, overwrite=True)

    command = resolve_browser_command(payload.browser) + [url]
    try:
        process = subprocess.Popen(command)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Browser permitido, mas executável não foi encontrado no sistema.")

    append_session_message(payload.session_id, "assistant", f"Tarefa web preparada: {brief_path}")
    audit_log(
        "prepare_browser_task",
        request,
        {
            "session_id": payload.session_id,
            "browser": payload.browser,
            "url": url,
            "brief_path": brief_path,
            "pid": process.pid,
        },
    )
    return {
        "session_id": payload.session_id,
        "browser": payload.browser,
        "url": url,
        "brief_path": brief_path,
        "pid": process.pid,
    }


@app.post("/api/browser-plan", dependencies=[Depends(require_bearer_token)])
async def browser_plan_endpoint(payload: BrowserExecutionPlanRequest, request: Request) -> dict:
    url = validate_allowed_url(payload.url)
    plan = generate_browser_execution_plan(payload.session_id, url, payload.task)
    append_session_message(payload.session_id, "assistant", f"Plano web gerado para: {url}")
    audit_log(
        "browser_plan",
        request,
        {"session_id": payload.session_id, "url": url},
    )
    return {
        "session_id": payload.session_id,
        "url": url,
        "plan": plan,
    }


@app.get("/api/time", dependencies=[Depends(require_bearer_token)])
async def time_endpoint() -> dict:
    now = datetime.now()
    return {
        "timestamp": now.isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
    }


@app.get("/api/weather", dependencies=[Depends(require_bearer_token)])
async def weather_endpoint() -> dict:
    return await WeatherAgent.get_info()


@app.get("/api/avatar-reference")
async def avatar_reference_endpoint() -> FileResponse:
    avatar_path = Config.AVATAR_REFERENCE_PATH
    if not avatar_path.exists():
        raise HTTPException(status_code=404, detail="Imagem de referência do STOA não encontrada.")
    return FileResponse(avatar_path)



FRONTEND_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>STOA</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
*  { margin:0; padding:0; box-sizing:border-box; }
:root {
  --blue : #4fc3f7;
  --red  : #ef5350;
  --teal : #80cbc4;
  --dim  : #37474f;
  --bg   : #060c14;
}
body {
  width:100vw; height:100vh; background:var(--bg);
  overflow:hidden; font-family:'Share Tech Mono',monospace; color:#e8f4fd;
}
#gl { position:fixed; inset:0; z-index:0; }
.ui {
  position:fixed; inset:0; z-index:10;
  display:flex; flex-direction:column; align-items:center;
  pointer-events:none;
}
.header {
  width:100%; display:flex; align-items:center; justify-content:space-between;
  padding:24px 28px; pointer-events:auto;
}
.logo {
  font-family:'Orbitron',sans-serif; font-size:18px;
  font-weight:900; letter-spacing:6px;
  text-shadow:0 0 20px rgba(79,195,247,.55);
}
.pill {
  font-size:9px; letter-spacing:3px; padding:5px 14px;
  border:1px solid var(--dim); border-radius:20px; color:var(--dim);
  transition:all .4s;
}
.pill.on  { color:var(--blue); border-color:var(--blue); box-shadow:0 0 12px rgba(79,195,247,.2); }
.pill.mic { color:var(--red);  border-color:var(--red);  box-shadow:0 0 12px rgba(239,83,80,.25); }
.pill.say { color:var(--teal); border-color:var(--teal); box-shadow:0 0 12px rgba(128,203,196,.2); }
.push { flex:1; }
.chat {
  width:min(560px,90vw); max-height:210px;
  overflow-y:auto; scrollbar-width:none;
  display:flex; flex-direction:column; gap:10px;
  padding:0 4px 8px; pointer-events:auto;
}
.chat::-webkit-scrollbar { display:none; }
.msg { font-size:13px; line-height:1.65; animation:up .35s ease forwards; opacity:0; }
@keyframes up { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
.msg.u { color:var(--dim); text-align:right; }
.msg.u::before  { content:"› "; color:var(--blue); }
.msg.a::before  { content:"STOA  "; color:var(--blue); font-weight:bold; }
.think { display:none; align-items:center; gap:6px; font-size:10px; color:var(--dim); letter-spacing:2px; }
.think.on { display:flex; }
.d { width:4px; height:4px; border-radius:50%; background:var(--blue); animation:bk 1.2s infinite; }
.d:nth-child(2){animation-delay:.2s} .d:nth-child(3){animation-delay:.4s}
@keyframes bk { 0%,80%,100%{opacity:.15} 40%{opacity:1} }
.mic-wrap {
  display:flex; flex-direction:column; align-items:center; gap:14px;
  padding:28px 0 44px; pointer-events:auto;
}
.ring {
  width:80px; height:80px; border-radius:50%;
  border:1px solid rgba(79,195,247,.18);
  display:flex; align-items:center; justify-content:center; position:relative;
}
.ring::before {
  content:''; position:absolute; inset:-10px; border-radius:50%;
  border:1px solid rgba(79,195,247,.07); animation:rp 3s infinite ease-out;
}
@keyframes rp { 0%{transform:scale(1);opacity:.5} 100%{transform:scale(1.4);opacity:0} }
.ring.mic { border-color:rgba(239,83,80,.45); animation:rb .7s infinite alternate; }
.ring.mic::before { border-color:rgba(239,83,80,.15); }
@keyframes rb { from{box-shadow:0 0 0 0 rgba(239,83,80,.3)} to{box-shadow:0 0 0 14px rgba(239,83,80,0)} }
.btn {
  width:64px; height:64px; border-radius:50%;
  background:rgba(79,195,247,.06); border:1.5px solid rgba(79,195,247,.32);
  cursor:pointer; display:flex; align-items:center; justify-content:center;
  transition:all .25s; -webkit-tap-highlight-color:transparent; color:#e8f4fd;
}
.btn:hover,.btn:active { background:rgba(79,195,247,.14); border-color:var(--blue); box-shadow:0 0 24px rgba(79,195,247,.3); }
.btn.mic { background:rgba(239,83,80,.1); border-color:var(--red); box-shadow:0 0 22px rgba(239,83,80,.3); }
.btn:disabled { opacity:.3; cursor:not-allowed; }
.hint { font-size:9px; letter-spacing:3px; color:var(--dim); transition:color .3s; }
.hint.mic { color:var(--red); }
</style>
</head>
<body>

<canvas id="gl"></canvas>

<div class="ui">
  <div class="header">
    <div class="logo">STOA</div>
    <div class="pill" id="pill">OFFLINE</div>
  </div>
  <div class="push"></div>
  <div class="chat" id="chat">
    <div class="think" id="think">
      <div class="d"></div><div class="d"></div><div class="d"></div>
      <span style="margin-left:6px">processando</span>
    </div>
  </div>
  <div class="mic-wrap">
    <div class="ring" id="ring">
      <button class="btn" id="mbtn">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="2" width="6" height="12" rx="3"/>
          <path d="M5 10a7 7 0 0 0 14 0M12 19v3M8 22h8"/>
        </svg>
      </button>
    </div>
    <div class="hint" id="hint">TOQUE PARA FALAR</div>
  </div>
</div>

<script>
/* ════════════════════════════════════
   BACKEND — usa mesma origem (relativo)
════════════════════════════════════ */
const BACKEND = '';
const TOKEN   = window.__STOA_TOKEN__ || '';

/* ════════════════════════════════════
   THREE.JS
════════════════════════════════════ */
const glCanvas = document.getElementById('gl');
const renderer = new THREE.WebGLRenderer({ canvas:glCanvas, antialias:true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x060c14, 1);

const scene  = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
camera.position.z = 3.0;

function onResize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
onResize();
window.addEventListener('resize', onResize);

function glowTex() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const cx = c.getContext('2d');
  const g  = cx.createRadialGradient(64,64,0,64,64,64);
  g.addColorStop(0,    'rgba(255,255,255,1)');
  g.addColorStop(0.3,  'rgba(255,255,255,0.8)');
  g.addColorStop(0.65, 'rgba(255,255,255,0.15)');
  g.addColorStop(1,    'rgba(255,255,255,0)');
  cx.fillStyle = g; cx.fillRect(0,0,128,128);
  return new THREE.CanvasTexture(c);
}
const ptex = glowTex();

function haloTex() {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const cx = c.getContext('2d');
  const g  = cx.createRadialGradient(128,128,30,128,128,128);
  g.addColorStop(0,   'rgba(79,195,247,0.22)');
  g.addColorStop(0.5, 'rgba(79,195,247,0.07)');
  g.addColorStop(1,   'rgba(79,195,247,0)');
  cx.fillStyle = g; cx.fillRect(0,0,256,256);
  return new THREE.CanvasTexture(c);
}

const N = 220, PHI = Math.PI*(3-Math.sqrt(5));
const pos=[], col=[], types=[];
const BLUE=new THREE.Color(0x4fc3f7), RED=new THREE.Color(0xef5350);

for (let i=0;i<N;i++) {
  const y=1-(i/(N-1))*2, r=Math.sqrt(Math.max(0,1-y*y)), t=PHI*i;
  pos.push(Math.cos(t)*r, y, Math.sin(t)*r);
  const isRed = Math.random()<0.28;
  types.push(isRed?1:0);
  const c=isRed?RED:BLUE; col.push(c.r,c.g,c.b);
}

const pgeo = new THREE.BufferGeometry();
pgeo.setAttribute('position', new THREE.Float32BufferAttribute(pos,3));
pgeo.setAttribute('color',    new THREE.Float32BufferAttribute(col,3));
const pmat = new THREE.PointsMaterial({
  size:0.055, map:ptex, vertexColors:true,
  transparent:true, depthWrite:false, blending:THREE.AdditiveBlending,
});
const pts = new THREE.Points(pgeo, pmat);

const lpos=[], lcol=[];
const CONN=0.52;
for (let i=0;i<N;i++) for (let j=i+1;j<N;j++) {
  const dx=pos[i*3]-pos[j*3], dy=pos[i*3+1]-pos[j*3+1], dz=pos[i*3+2]-pos[j*3+2];
  if (dx*dx+dy*dy+dz*dz>CONN*CONN) continue;
  lpos.push(pos[i*3],pos[i*3+1],pos[i*3+2], pos[j*3],pos[j*3+1],pos[j*3+2]);
  const ci=types[i]===1?RED:BLUE, cj=types[j]===1?RED:BLUE;
  lcol.push(ci.r,ci.g,ci.b, cj.r,cj.g,cj.b);
}
const lgeo = new THREE.BufferGeometry();
lgeo.setAttribute('position', new THREE.Float32BufferAttribute(lpos,3));
lgeo.setAttribute('color',    new THREE.Float32BufferAttribute(lcol,3));
const lmat = new THREE.LineBasicMaterial({
  vertexColors:true, transparent:true, opacity:0.15,
  blending:THREE.AdditiveBlending, depthWrite:false,
});
const lines = new THREE.LineSegments(lgeo, lmat);

const halo = new THREE.Mesh(
  new THREE.PlaneGeometry(3.4,3.4),
  new THREE.MeshBasicMaterial({
    map:haloTex(), transparent:true, depthWrite:false,
    blending:THREE.AdditiveBlending, side:THREE.DoubleSide,
  })
);

const group = new THREE.Group();
group.add(pts, lines, halo);
scene.add(group);

let rotSpd=0.003, rotTarget=0.003;
let opTarget=0.15, szTarget=0.055;
let clk=0;

function setVis(s) {
  if(s==='idle')      {rotTarget=0.003;opTarget=0.15;szTarget=0.055;}
  if(s==='listening') {rotTarget=0.012;opTarget=0.32;szTarget=0.068;}
  if(s==='thinking')  {rotTarget=0.018;opTarget=0.24;szTarget=0.058;}
  if(s==='speaking')  {rotTarget=0.007;opTarget=0.28;szTarget=0.062;}
}

(function tick(){
  requestAnimationFrame(tick);
  clk += 0.016;
  rotSpd += (rotTarget-rotSpd)*0.04;
  group.rotation.y += rotSpd;
  group.rotation.x  = Math.sin(clk*0.22)*0.10;
  const sz = appState==='speaking' ? szTarget+Math.sin(clk*5.5)*0.009 : szTarget;
  pmat.size    += (sz-pmat.size)*0.07;
  lmat.opacity += (opTarget-lmat.opacity)*0.06;
  renderer.render(scene, camera);
})();

/* ════════════════════════════════════
   STATE
════════════════════════════════════ */
let appState='idle', online=false;

function setState(s) {
  appState=s; setVis(s);
  const pill=document.getElementById('pill');
  const ring=document.getElementById('ring');
  const btn =document.getElementById('mbtn');
  const hint=document.getElementById('hint');
  pill.className='pill'; ring.className='ring';
  btn.className='btn';   hint.className='hint';
  const m={
    idle:     {label:online?'ONLINE':'OFFLINE',pc:online?'on':'',        hint:'TOQUE PARA FALAR'},
    listening:{label:'OUVINDO', pc:'mic',rc:'mic',bc:'mic',hc:'mic',     hint:'OUVINDO...'},
    thinking: {label:'PENSANDO',pc:'on',                                  hint:'PROCESSANDO...'},
    speaking: {label:'FALANDO', pc:'say',                                 hint:'FALANDO...'},
  }[s];
  pill.textContent=m.label;
  if(m.pc) pill.classList.add(m.pc);
  if(m.rc) ring.classList.add(m.rc);
  if(m.bc) btn.classList.add(m.bc);
  if(m.hc) hint.classList.add(m.hc);
  hint.textContent=m.hint;
  btn.disabled=(s==='thinking'||s==='speaking');
}

/* ════════════════════════════════════
   CHAT
════════════════════════════════════ */
const chatEl=document.getElementById('chat');
const thinkEl=document.getElementById('think');
function addMsg(text,who){
  const d=document.createElement('div');
  d.className='msg '+who; d.textContent=text;
  chatEl.insertBefore(d,thinkEl);
  chatEl.scrollTop=chatEl.scrollHeight;
}
function showThink(v){thinkEl.className=v?'think on':'think';}

/* ════════════════════════════════════
   BACKEND
════════════════════════════════════ */
async function ping(){
  try{
    const r=await fetch(BACKEND+'/api/health');
    online=r.ok;
  }catch{online=false;}
  if(appState==='idle') setState('idle');
}

async function ask(text){
  setState('thinking'); showThink(true);
  try{
    const r=await fetch(BACKEND+'/api/orchestrate',{
      method:'POST',
      headers:{'Content-Type':'application/json',Authorization:'Bearer '+TOKEN},
      body:JSON.stringify({text:text, mode:'builder'}),
    });
    const d=await r.json();
    showThink(false);
    const reply=d.result?.final_response||d.response||d.message||d.text||d.content||JSON.stringify(d);
    addMsg(reply,'a'); speak(reply);
  }catch(e){
    showThink(false);
    addMsg('[Erro: '+e.message+']','a');
    setState('idle');
  }
}

/* ════════════════════════════════════
   TTS
════════════════════════════════════ */
function speak(text){
  if(!window.speechSynthesis){setState('idle');return;}
  window.speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(text);
  u.lang='pt-BR'; u.rate=1.0;
  const applyVoice=()=>{
    const vs=window.speechSynthesis.getVoices();
    const v=vs.find(x=>x.lang==='pt-BR')||vs.find(x=>x.lang.startsWith('pt'));
    if(v) u.voice=v;
  };
  applyVoice();
  if('onvoiceschanged' in window.speechSynthesis)
    window.speechSynthesis.onvoiceschanged=applyVoice;
  u.onstart=()=>setState('speaking');
  u.onend=()=>setState('idle');
  u.onerror=()=>setState('idle');
  setState('speaking');
  window.speechSynthesis.speak(u);
}

/* ════════════════════════════════════
   SPEECH RECOGNITION
════════════════════════════════════ */
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
let rec=null, listening=false;
if(SR){
  rec=new SR();
  rec.lang='pt-BR'; rec.interimResults=false; rec.maxAlternatives=1;
  rec.onresult=e=>{
    const t=e.results[0][0].transcript.trim();
    listening=false;
    if(t){addMsg(t,'u');ask(t);}else setState('idle');
  };
  rec.onerror=()=>{setState('idle');listening=false;};
  rec.onend=()=>{if(appState==='listening')setState('idle');listening=false;};
}

function toggleMic(){
  if(appState==='thinking'||appState==='speaking') return;
  if(!rec){addMsg('[Reconhecimento de voz indisponível neste browser]','a');return;}
  if(listening){rec.stop();setState('idle');listening=false;return;}
  if(window.speechSynthesis) window.speechSynthesis.cancel();
  listening=true; setState('listening');
  try{rec.start();}catch{setState('idle');listening=false;}
}

const mbtn=document.getElementById('mbtn');
mbtn.addEventListener('click',toggleMic);
mbtn.addEventListener('touchend',e=>{e.preventDefault();toggleMic();},{passive:false});

/* ════════════════════════════════════
   INIT
════════════════════════════════════ */
setState('idle');
ping();
setInterval(ping,30000);
</script>
</body>
</html>
"""



if __name__ == "__main__":
    logger.info("Iniciando Safe STOA Agent na porta %s", config.PORT)
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=config.DEBUG, log_level="info")
