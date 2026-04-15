from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from device_control_models import ActionRequest, ActionResult, DeviceHeartbeat, DeviceRegistration


def make_device_router(brain) -> APIRouter:
    router = APIRouter(prefix="/api/devices", tags=["devices"])

    @router.get("")
    async def list_registered_devices():
        items = brain.device_control.list_devices()
        return {
            "items": items,
            "count": len(items),
            "timestamp": datetime.now().isoformat(),
        }

    @router.get("/actions")
    async def list_device_actions(device_id: Optional[str] = None, limit: int = 20):
        items = brain.device_control.list_actions(device_id=device_id, limit=limit)
        return {
            "items": items,
            "count": len(items),
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
        }

    @router.post("/register")
    async def register_device(registration: DeviceRegistration):
        try:
            record = brain.device_control.register_device(registration)
            return {
                "device": record,
                "status": "registered",
                "message": f"Dispositivo {record.get('device_name', record.get('device_id'))} registrado no STOA Core.",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/actions")
    async def create_device_action(request: ActionRequest):
        try:
            request.parameters = dict(request.parameters or {})
            request.parameters.setdefault("session_id", "default")
            request.parameters.setdefault("requested_by", request.requested_by or "stoa_pwa")
            if not request.requested_by or request.requested_by == "stoa_core":
                request.requested_by = request.parameters["requested_by"]
            action = brain.device_control.request_action(request)
            awaiting_confirmation = action.get("status") == "waiting_confirmation"
            return {
                "action": action,
                "requires_confirmation": awaiting_confirmation,
                "message": (
                    "Ação sensível aguardando confirmação explícita."
                    if awaiting_confirmation
                    else "Ação enfileirada para o dispositivo."
                ),
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/actions/{action_id}/confirm")
    async def confirm_device_action(action_id: str, confirmation):
        try:
            action = brain.device_control.confirm_action(action_id, reason=confirmation.reason)
            return {
                "action": action,
                "message": "Ação confirmada e liberada para execução no agente local.",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/{device_id}")
    async def get_registered_device(device_id: str):
        item = brain.device_control.get_device(device_id)
        if not item:
            raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")
        return item

    @router.post("/{device_id}/heartbeat")
    async def heartbeat_device(device_id: str, heartbeat: DeviceHeartbeat):
        try:
            if heartbeat.device_id != device_id:
                raise ValueError("device_id do heartbeat difere da rota.")
            device = brain.device_control.heartbeat(heartbeat)
            return {
                "device": device,
                "message": "Heartbeat recebido.",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/{device_id}/actions/next")
    async def get_next_device_action(device_id: str):
        try:
            action = brain.device_control.get_next_action(device_id)
            return {
                "action": action,
                "has_action": bool(action),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/{device_id}/actions/{action_id}/result")
    async def submit_device_action_result(device_id: str, action_id: str, result: ActionResult):
        try:
            if result.action_id != action_id:
                raise ValueError("action_id do payload difere da rota.")
            if result.device_id != device_id:
                raise ValueError("device_id do payload difere da rota.")
            action = brain.device_control.submit_action_result(device_id, action_id, result)
            return {
                "action": action,
                "message": "Resultado da ação registrado no STOA Core.",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    return router
