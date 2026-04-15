from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from planner_symbol import Planner, Executor
from state_store import StateStore
from pathlib import Path
import os

router = APIRouter(tags=["planner"])

# Instância única por processo, reutilizada entre requisições.
_runtime_state_db = os.getenv("STOA_STATE_DB", str(Path(__file__).with_name(".stoa_state.db")))
_state_store = StateStore(_runtime_state_db)
_planner = Planner(_state_store)


def get_planner() -> Planner:
    """Dependency para obter instância singleton do Planner"""
    return _planner

@router.get("/api/planner/health")
async def planner_health():
    return {"status": "ok", "service": "planner"}

@router.post("/api/planner/preview")
async def create_preview(
    command: str,
    project_index: Optional[dict] = None,
    working_context: Optional[dict] = None,
    planner: Planner = Depends(get_planner)
):
    """Cria um preview de mudanças"""
    try:
        response, details = planner.plan_and_preview(command, project_index, working_context)
        return {
            "response": response,
            "details": details,
            "status": "success" if details.get('operation') != 'create_preview_failed' else "error"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao criar preview: {e}")

@router.post("/api/planner/apply")
async def apply_preview(planner: Planner = Depends(get_planner)):
    """Aplica o preview pendente"""
    try:
        response, details = planner.apply_pending_preview()
        return {
            "response": response,
            "details": details,
            "status": "success" if details.get('operation') == 'apply_preview_change_set' else "error"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao aplicar preview: {e}")

@router.post("/api/planner/cancel")
async def cancel_preview(planner: Planner = Depends(get_planner)):
    """Cancela o preview pendente"""
    try:
        response, details = planner.cancel_pending_preview()
        return {
            "response": response,
            "details": details,
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao cancelar preview: {e}")

@router.get("/api/planner/status")
async def get_preview_status(planner: Planner = Depends(get_planner)):
    """Obtém o status do preview pendente"""
    status = planner._get_pending_preview_status()
    return {
        "preview_status": status,
        "has_pending": status.get('valid', False)
    }

@router.post("/api/executor/execute")
async def execute_command(
    command: str,
    project_index: Optional[dict] = None,
    working_context: Optional[dict] = None,
    executor: Executor = Depends(lambda: Executor),
):
    """Executa comandos básicos de desenvolvimento"""
    try:
        response, details = executor.execute_command(command, project_index, working_context)
        return {
            "response": response,
            "details": details,
            "status": "success" if details.get('operation') != 'execution_error' else "error"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao executar comando: {e}")
