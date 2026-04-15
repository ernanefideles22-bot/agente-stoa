from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from uuid import uuid4

from device_control_models import (
    ActionEnvelope,
    ActionRequest,
    ActionResult,
    ActionStatus,
    CapabilityRisk,
    DeviceCapability,
    DeviceHeartbeat,
    DeviceRecord,
    DeviceRegistration,
    DeviceStatus,
)
from device_state_store import DeviceStateStore
from operation_log import OperationLogger


class DeviceControlCore:
    STALE_AFTER_SECONDS = 90
    OFFLINE_AFTER_SECONDS = 240
    FORGET_OFFLINE_AFTER_SECONDS = 86400
    CONFIRMATION_TTL_MINUTES = 10
    SAFE_ACTIONS = {"open_app", "open_url", "take_screenshot"}
    SENSITIVE_ACTIONS = {"run_shell_command"}

    def __init__(
        self,
        event_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        state_store: Optional[DeviceStateStore] = None,
    ) -> None:
        self.devices: dict[str, DeviceRecord] = {}
        self.device_queues: dict[str, list[str]] = {}
        self.actions: dict[str, ActionEnvelope] = {}
        self.event_callback = event_callback
        self.device_preferences: dict[str, str] = {}
        self.contextual_device_preferences: dict[str, str] = {}
        self.state_store = state_store or DeviceStateStore()
        self._rehydrate_state()

    def _now_iso(self) -> str:
        return datetime.now().isoformat()

    def _generate_action_id(self) -> str:
        return f"device-action-{uuid4().hex[:10]}"

    def _action_timeout_seconds(self, action_type: str) -> int:
        return {
            "open_app": 20,
            "open_url": 20,
            "take_screenshot": 30,
            "run_shell_command": 60,
        }.get(action_type, 30)

    def _retry_policy(self, action_type: str) -> tuple[bool, int]:
        if action_type in {"open_app", "open_url", "take_screenshot"}:
            return True, 1
        return False, 0

    def _classify_action_error(self, action: ActionEnvelope, error_text: Optional[str], error_code: Optional[str] = None) -> str:
        if error_code:
            return error_code
        text = (error_text or "").lower()
        if "timeout" in text:
            return "timeout_transient"
        if "não declarou suporte" in text or "nao declarou suporte" in text:
            return "capability_missing"
        if "não registrado" in text or "nao registrado" in text:
            return "device_not_registered"
        if "não encontrado" in text or "nao encontrado" in text:
            return "target_not_found"
        if "falha ao capturar screenshot" in text:
            return "screenshot_failed"
        if "comando falhou" in text or "exit code" in text:
            return "command_failed"
        if action.action_type == "open_app":
            return "app_not_found"
        return "unknown_error"

    def _error_aware_retry_policy(self, action: ActionEnvelope, error_code: str) -> tuple[bool, str]:
        if error_code in {"timeout_transient", "device_offline_transient"} and action.retry_count < action.max_retries:
            return True, "transient_retry"
        if error_code in {"capability_missing", "app_not_found", "target_not_found", "command_failed", "screenshot_failed"}:
            return False, "terminal_capability_or_target_failure"
        if not action.retryable or action.retry_count >= action.max_retries:
            return False, "retry_budget_exhausted"
        return False, "terminal_unknown_failure"

    def _context_preference_key(
        self,
        *,
        goal_id: Optional[str] = None,
        action_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        return "|".join(
            [
                f"session:{session_id or 'default'}",
                f"goal:{goal_id or '-'}",
                f"action:{action_type or '-'}",
            ]
        )

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_callback:
            self.event_callback(
                {
                    "event_type": event_type,
                    "timestamp": self._now_iso(),
                    "payload": payload,
                }
            )

    def _persist_device(self, device_id: str) -> None:
        device = self.devices.get(device_id)
        if device:
            self.state_store.save_device(device.model_dump())

    def _persist_action(self, action_id: str) -> None:
        action = self.actions.get(action_id)
        if action:
            self.state_store.save_action(action.model_dump())

    def _persist_queue(self, device_id: str) -> None:
        self.state_store.replace_queue(device_id, list(self.device_queues.get(device_id, [])))

    def _persist_preferences(self) -> None:
        for scope_key, device_id in self.device_preferences.items():
            self.state_store.save_preference(f"default:{scope_key}", device_id)
        for scope_key, device_id in self.contextual_device_preferences.items():
            self.state_store.save_preference(scope_key, device_id)

    def _action_context_matches(
        self,
        action: ActionEnvelope,
        *,
        session_id: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> bool:
        parameters = action.parameters or {}
        action_session = parameters.get("session_id")
        action_requested_by = action.requested_by or parameters.get("requested_by")
        if session_id and action_session != session_id:
            return False
        if requested_by and action_requested_by != requested_by:
            return False
        return True

    def _has_pending_confirmation_for_device(self, device_id: str) -> bool:
        for action in self.actions.values():
            if action.device_id != device_id:
                continue
            if action.status == ActionStatus.AWAITING_CONFIRMATION:
                return True
        return False

    def _prune_offline_devices(self) -> None:
        now = datetime.now()
        removable: list[str] = []
        for device_id, device in self.devices.items():
            self._refresh_device_status(device)
            if device.status != DeviceStatus.OFFLINE:
                continue
            if self.device_queues.get(device_id):
                continue
            if device.current_action_id:
                continue
            if self._has_pending_confirmation_for_device(device_id):
                continue
            try:
                heartbeat_raw = device.last_heartbeat_at or device.last_seen_at
                last_seen = datetime.fromisoformat(heartbeat_raw)
            except Exception:
                last_seen = datetime.min
            if now - last_seen <= timedelta(seconds=self.FORGET_OFFLINE_AFTER_SECONDS):
                continue
            removable.append(device_id)

        for device_id in removable:
            self.devices.pop(device_id, None)
            self.device_queues.pop(device_id, None)
            if self.device_preferences.get("default") == device_id:
                self.device_preferences.pop("default", None)
            self.contextual_device_preferences = {
                scope_key: preferred_id
                for scope_key, preferred_id in self.contextual_device_preferences.items()
                if preferred_id != device_id
            }
            self.state_store.delete_device(device_id)
            self.state_store.delete_queue(device_id)
            self.state_store.delete_preferences_for_device(device_id)

    def _rehydrate_state(self) -> None:
        for device_id, payload in self.state_store.load_devices().items():
            try:
                self.devices[device_id] = DeviceRecord(**payload)
            except Exception:
                continue

        for action_id, payload in self.state_store.load_actions().items():
            try:
                action = ActionEnvelope(**payload)
            except Exception:
                continue
            if action.status in {ActionStatus.DISPATCHED, ActionStatus.RUNNING}:
                action.status = ActionStatus.QUEUED
                action.dispatched_at = None
                action.updated_at = self._now_iso()
            self.actions[action_id] = action

        self.device_queues = self.state_store.load_queues()
        for device_id in list(self.devices.keys()):
            self.device_queues.setdefault(device_id, [])

        preferences = self.state_store.load_preferences()
        self.device_preferences = {
            key.split("default:", 1)[1]: value
            for key, value in preferences.items()
            if key.startswith("default:")
        }
        self.contextual_device_preferences = {
            key: value
            for key, value in preferences.items()
            if not key.startswith("default:")
        }

        for action in self.actions.values():
            if action.status == ActionStatus.QUEUED:
                queue = self.device_queues.setdefault(action.device_id, [])
                if action.action_id not in queue:
                    queue.append(action.action_id)

        for device_id, device in self.devices.items():
            device.current_action_id = None
            device.queue_depth = len(self.device_queues.get(device_id, []))
            self._refresh_device_status(device)
            self._persist_device(device_id)
        for action_id in list(self.actions.keys()):
            self._persist_action(action_id)
        for device_id in list(self.device_queues.keys()):
            self._persist_queue(device_id)

    def _mark_device_seen(self, device_id: str) -> None:
        device = self.devices.get(device_id)
        if not device:
            return
        now = self._now_iso()
        device.last_seen_at = now
        device.last_heartbeat_at = now
        if device.current_action_id:
            device.status = DeviceStatus.BUSY
        elif device.status == DeviceStatus.OFFLINE:
            device.status = DeviceStatus.ONLINE

    def _refresh_device_status(self, device: DeviceRecord) -> DeviceRecord:
        try:
            heartbeat_raw = device.last_heartbeat_at or device.last_seen_at
            last_seen = datetime.fromisoformat(heartbeat_raw)
        except Exception:
            device.status = DeviceStatus.STALE
            return device
        age = datetime.now() - last_seen
        if age > timedelta(seconds=self.OFFLINE_AFTER_SECONDS):
            device.status = DeviceStatus.OFFLINE
        elif age > timedelta(seconds=self.STALE_AFTER_SECONDS):
            device.status = DeviceStatus.STALE
        elif device.current_action_id:
            device.status = DeviceStatus.BUSY
        else:
            device.status = DeviceStatus.ONLINE
        device.queue_depth = len(self.device_queues.get(device.device_id, []))
        return device

    def _find_capability(self, device: DeviceRecord, action_type: str) -> Optional[DeviceCapability]:
        for capability in device.capabilities:
            if capability.action_type == action_type:
                return capability
        return None

    def _assess_risk(self, device: DeviceRecord, action_type: str) -> tuple[CapabilityRisk, bool, str]:
        capability = self._find_capability(device, action_type)
        if capability:
            risk = capability.risk
            requires_confirmation = capability.requires_confirmation or risk == CapabilityRisk.SENSITIVE
            reason = capability.description or f"Capacidade declarada para {action_type}."
            return risk, requires_confirmation, reason
        if action_type in self.SENSITIVE_ACTIONS:
            return CapabilityRisk.SENSITIVE, True, "Ação sensível por política do Core."
        return CapabilityRisk.SAFE, False, "Ação segura por política do Core."

    def register_device(self, registration: DeviceRegistration) -> dict:
        now = self._now_iso()
        existing = self.devices.get(registration.device_id)
        record = DeviceRecord(
            **registration.model_dump(),
            registered_at=(existing.registered_at if existing else now),
            last_seen_at=now,
            last_heartbeat_at=now,
            status=DeviceStatus.ONLINE,
            queue_depth=len(self.device_queues.get(registration.device_id, [])),
            last_action_id=(existing.last_action_id if existing else None),
            current_action_id=(existing.current_action_id if existing else None),
            last_result=(existing.last_result if existing else None),
        )
        self.devices[registration.device_id] = record
        self.device_queues.setdefault(registration.device_id, [])
        self._persist_device(registration.device_id)
        self._persist_queue(registration.device_id)
        OperationLogger.log_event(
            "device_registered",
            "ok",
            f"Dispositivo {record.device_name} registrado/atualizado.",
            device_id=record.device_id,
            platform=record.platform.value if hasattr(record.platform, "value") else str(record.platform),
            hostname=record.hostname,
            capabilities=[cap.action_type for cap in record.capabilities],
        )
        return self._refresh_device_status(record).model_dump()

    def remember_preferred_device(self, device_id: str) -> None:
        if device_id in self.devices:
            self.device_preferences["default"] = device_id
            self._persist_preferences()

    def remember_contextual_device_preference(
        self,
        *,
        device_id: str,
        goal_id: Optional[str] = None,
        action_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        if device_id not in self.devices:
            return
        self.remember_preferred_device(device_id)
        self.contextual_device_preferences[
            self._context_preference_key(goal_id=goal_id, action_type=action_type, session_id=session_id)
        ] = device_id
        self._persist_preferences()

    def get_preferred_device(self) -> Optional[dict]:
        preferred_id = self.device_preferences.get("default")
        if not preferred_id:
            return None
        return self.get_device(preferred_id)

    def get_contextual_preferred_device(
        self,
        *,
        goal_id: Optional[str] = None,
        action_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[dict]:
        keys = [
            self._context_preference_key(goal_id=goal_id, action_type=action_type, session_id=session_id),
            self._context_preference_key(goal_id=goal_id, action_type=None, session_id=session_id),
            self._context_preference_key(goal_id=None, action_type=action_type, session_id=session_id),
        ]
        for key in keys:
            preferred_id = self.contextual_device_preferences.get(key)
            if preferred_id:
                device = self.get_device(preferred_id)
                if device and device.get("status") in {"online", "busy"}:
                    return device
        return self.get_preferred_device()

    def list_devices(self) -> list[dict]:
        self.sweep_action_timeouts()
        self._prune_offline_devices()
        items = []
        for device_id in sorted(self.devices.keys()):
            items.append(self._refresh_device_status(self.devices[device_id]).model_dump())
        return items

    def get_device(self, device_id: str) -> Optional[dict]:
        self._prune_offline_devices()
        device = self.devices.get(device_id)
        if not device:
            return None
        return self._refresh_device_status(device).model_dump()

    def resolve_device(self, raw_target: Optional[str] = None) -> Optional[dict]:
        resolution = self.resolve_device_detailed(raw_target)
        return resolution.get("device")

    def resolve_device_detailed(
        self,
        raw_target: Optional[str] = None,
        *,
        goal_id: Optional[str] = None,
        action_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        self._prune_offline_devices()
        devices = [self._refresh_device_status(device) for device in self.devices.values()]
        online_devices = [device for device in devices if device.status in {DeviceStatus.ONLINE, DeviceStatus.BUSY}]
        target = (raw_target or "").strip().lower()
        if not devices:
            return {"status": "not_found", "reason": "Nenhum dispositivo registrado.", "device": None, "candidates": []}
        if not online_devices:
            return {
                "status": "offline",
                "reason": "Há dispositivos registrados, mas nenhum está online.",
                "device": None,
                "candidates": [device.model_dump() for device in devices],
            }

        def aliases_for(device: DeviceRecord) -> list[str]:
            values = [device.device_id, device.device_name, device.hostname or ""]
            values.extend(device.aliases or [])
            values.extend((device.metadata or {}).get("aliases", []))
            return [value.lower() for value in values if value]

        if target:
            exact = [device for device in online_devices if target in aliases_for(device)]
            if len(exact) == 1:
                self.remember_contextual_device_preference(
                    device_id=exact[0].device_id,
                    goal_id=goal_id,
                    action_type=action_type,
                    session_id=session_id,
                )
                return {"status": "resolved", "reason": "Alias exato encontrado.", "device": exact[0].model_dump(), "candidates": [exact[0].model_dump()]}
            partial = [device for device in online_devices if any(target in alias for alias in aliases_for(device))]
            if len(partial) == 1:
                self.remember_contextual_device_preference(
                    device_id=partial[0].device_id,
                    goal_id=goal_id,
                    action_type=action_type,
                    session_id=session_id,
                )
                return {"status": "resolved", "reason": "Alias parcial encontrado.", "device": partial[0].model_dump(), "candidates": [partial[0].model_dump()]}
            if len(partial) > 1:
                return {
                    "status": "ambiguous",
                    "reason": "Mais de um dispositivo corresponde ao alvo solicitado.",
                    "device": None,
                    "candidates": [device.model_dump() for device in partial],
                }
            return {
                "status": "not_found",
                "reason": f"Nenhum dispositivo online corresponde a '{raw_target}'.",
                "device": None,
                "candidates": [device.model_dump() for device in online_devices],
            }

        preferred = self.get_contextual_preferred_device(goal_id=goal_id, action_type=action_type, session_id=session_id)
        if preferred and preferred.get("status") in {"online", "busy"}:
            return {
                "status": "resolved",
                "reason": "Dispositivo preferido do contexto selecionado.",
                "device": preferred,
                "candidates": [preferred],
            }
        if len(online_devices) == 1:
            self.remember_contextual_device_preference(
                device_id=online_devices[0].device_id,
                goal_id=goal_id,
                action_type=action_type,
                session_id=session_id,
            )
            return {
                "status": "resolved",
                "reason": "Apenas um dispositivo online disponível.",
                "device": online_devices[0].model_dump(),
                "candidates": [online_devices[0].model_dump()],
            }
        preferred = sorted(
            online_devices,
            key=lambda item: (item.status != DeviceStatus.BUSY, item.last_seen_at or ""),
            reverse=True,
        )
        return {
            "status": "ambiguous",
            "reason": "Há mais de um dispositivo online; especifique qual alvo usar.",
            "device": None,
            "candidates": [device.model_dump() for device in preferred[:5]],
        }

    def list_actions(self, *, limit: int = 20, device_id: Optional[str] = None) -> list[dict]:
        self.sweep_action_timeouts()
        actions = list(self.actions.values())
        if device_id:
            actions = [action for action in actions if action.device_id == device_id]
        actions.sort(key=lambda action: action.updated_at or action.created_at, reverse=True)
        return [action.model_dump() for action in actions[:limit]]

    def sweep_action_timeouts(self) -> list[dict]:
        now = datetime.now()
        updated = []
        for action in self.actions.values():
            if action.status != ActionStatus.DISPATCHED or not action.dispatched_at:
                continue
            try:
                dispatched_at = datetime.fromisoformat(action.dispatched_at)
            except Exception:
                continue
            if now - dispatched_at <= timedelta(seconds=action.timeout_seconds):
                continue
            action.last_error = f"timeout_after_{action.timeout_seconds}s"
            action.last_error_code = "timeout_transient"
            action.updated_at = self._now_iso()
            should_retry, reason_code = self._error_aware_retry_policy(action, action.last_error_code)
            if should_retry:
                action.retry_count += 1
                action.status = ActionStatus.QUEUED
                action.dispatched_at = None
                self.device_queues.setdefault(action.device_id, []).append(action.action_id)
                device = self.devices.get(action.device_id)
                if device:
                    device.current_action_id = None
                    device.status = DeviceStatus.ONLINE
                    device.queue_depth = len(self.device_queues.get(action.device_id, []))
                    self._persist_device(action.device_id)
                self._persist_action(action.action_id)
                self._persist_queue(action.device_id)
                OperationLogger.log_event(
                    "device_action_timed_out_retrying",
                    "warning",
                    f"Ação {action.action_type} expirou e será reenfileirada.",
                    device_id=action.device_id,
                    action_id=action.action_id,
                    action_type=action.action_type,
                    retry_count=action.retry_count,
                    max_retries=action.max_retries,
                    reason_code=reason_code,
                    goal_id=action.goal_id,
                )
                self._emit_event("device_action_timed_out_retrying", action.model_dump())
            else:
                action.status = ActionStatus.TIMED_OUT
                action.terminal_failure = True
                action.terminal_reason_code = reason_code
                device = self.devices.get(action.device_id)
                if device:
                    device.current_action_id = None
                    device.status = DeviceStatus.ONLINE
                    self._persist_device(action.device_id)
                self._persist_action(action.action_id)
                OperationLogger.log_event(
                    "device_action_timed_out_failed",
                    "timed_out",
                    f"Ação {action.action_type} expirou e falhou em definitivo.",
                    device_id=action.device_id,
                    action_id=action.action_id,
                    action_type=action.action_type,
                    retry_count=action.retry_count,
                    max_retries=action.max_retries,
                    reason_code=reason_code,
                    goal_id=action.goal_id,
                )
                self._emit_event("device_action_timed_out_failed", action.model_dump())
            updated.append(action.model_dump())
        return updated

    def request_action(self, request: ActionRequest) -> dict:
        device = self.devices.get(request.device_id)
        if not device:
            raise ValueError(f"Dispositivo {request.device_id} não registrado.")
        self._mark_device_seen(request.device_id)
        request.parameters = dict(request.parameters or {})
        request.parameters.setdefault("requested_by", request.requested_by)
        capability = self._find_capability(device, request.action_type)
        if not capability:
            raise ValueError(f"O dispositivo {request.device_id} não declarou suporte para {request.action_type}.")

        risk, requires_confirmation, reason = self._assess_risk(device, request.action_type)
        status = (
            ActionStatus.QUEUED
            if (request.confirmed or not requires_confirmation)
            else ActionStatus.AWAITING_CONFIRMATION
        )
        now = self._now_iso()
        confirmation_expires_at = (
            (datetime.now() + timedelta(minutes=self.CONFIRMATION_TTL_MINUTES)).isoformat()
            if requires_confirmation and not request.confirmed
            else None
        )
        retryable, max_retries = self._retry_policy(request.action_type)
        action = ActionEnvelope(
            action_id=self._generate_action_id(),
            device_id=request.device_id,
            action_type=request.action_type,
            target=request.target,
            parameters=request.parameters,
            command_text=request.command_text,
            requested_by=request.requested_by,
            goal_id=(request.parameters or {}).get("goal_id"),
            context_key=self._context_preference_key(
                goal_id=(request.parameters or {}).get("goal_id"),
                action_type=request.action_type,
                session_id=(request.parameters or {}).get("session_id"),
            ),
            risk=risk,
            requires_confirmation=requires_confirmation,
            status=status,
            summary=self._build_action_summary(request.action_type, request.target, request.parameters),
            created_at=now,
            updated_at=now,
            confirmed_at=(now if request.confirmed else None),
            confirmation_reason=request.reason,
            confirmation_expires_at=confirmation_expires_at,
            confirmation_prompt=(
                f"Confirme a ação {request.action_type} para {device.device_name} "
                f"até {confirmation_expires_at}."
                if confirmation_expires_at else None
            ),
            timeout_seconds=int((request.parameters or {}).get("timeout_seconds") or self._action_timeout_seconds(request.action_type)),
            retryable=retryable,
            max_retries=max_retries,
        )
        self.actions[action.action_id] = action
        self.device_queues.setdefault(request.device_id, [])
        self.remember_contextual_device_preference(
            device_id=request.device_id,
            goal_id=action.goal_id,
            action_type=request.action_type,
            session_id=(request.parameters or {}).get("session_id"),
        )

        if status == ActionStatus.QUEUED:
            self.device_queues[request.device_id].append(action.action_id)
            self._persist_action(action.action_id)
            self._persist_queue(request.device_id)
            OperationLogger.log_event(
                "device_action_queued",
                "queued",
                f"Ação {action.action_type} enfileirada para {device.device_name}.",
                device_id=action.device_id,
                action_id=action.action_id,
                action_type=action.action_type,
                risk=action.risk.value,
                target=action.target,
                requires_confirmation=action.requires_confirmation,
                goal_id=action.goal_id,
            )
            self._emit_event("device_action_queued", action.model_dump())
        else:
            self._persist_action(action.action_id)
            OperationLogger.log_event(
                "device_action_requires_confirmation",
                "waiting_confirmation",
                f"Ação {action.action_type} aguardando confirmação para {device.device_name}.",
                device_id=action.device_id,
                action_id=action.action_id,
                action_type=action.action_type,
                risk=action.risk.value,
                target=action.target,
                policy_reason=reason,
                goal_id=action.goal_id,
                reason_code="awaiting_device_confirmation",
            )
            self._emit_event("device_action_requires_confirmation", action.model_dump())

        device.queue_depth = len(self.device_queues[request.device_id])
        self._persist_device(request.device_id)
        return action.model_dump()

    def confirm_action(self, action_id: str, *, reason: Optional[str] = None) -> dict:
        action = self.actions.get(action_id)
        if not action:
            raise ValueError(f"Ação {action_id} não encontrada.")
        if action.status != ActionStatus.AWAITING_CONFIRMATION:
            return action.model_dump()
        if action.confirmation_expires_at:
            expires_at = datetime.fromisoformat(action.confirmation_expires_at)
            if datetime.now() > expires_at:
                action.status = ActionStatus.REJECTED
                action.updated_at = self._now_iso()
                self._persist_action(action.action_id)
                raise ValueError(f"A confirmação da ação {action_id} expirou.")
        now = self._now_iso()
        action.status = ActionStatus.QUEUED
        action.updated_at = now
        action.confirmed_at = now
        action.confirmation_reason = reason or action.confirmation_reason
        self.device_queues.setdefault(action.device_id, []).append(action.action_id)
        device = self.devices.get(action.device_id)
        if device:
            device.queue_depth = len(self.device_queues[action.device_id])
            self._persist_device(action.device_id)
        self._persist_action(action.action_id)
        self._persist_queue(action.device_id)
        OperationLogger.log_event(
            "device_action_confirmed",
            "queued",
            f"Ação {action.action_type} confirmada e enfileirada.",
            device_id=action.device_id,
            action_id=action.action_id,
            action_type=action.action_type,
            risk=action.risk.value,
            confirmation_reason=action.confirmation_reason,
            goal_id=action.goal_id,
            reason_code="device_confirmation_received",
        )
        self._emit_event("device_action_confirmed", action.model_dump())
        return action.model_dump()

    def cancel_action(self, action_id: str, *, reason: Optional[str] = None) -> dict:
        action = self.actions.get(action_id)
        if not action:
            raise ValueError(f"Ação {action_id} não encontrada.")
        if action.status not in {ActionStatus.AWAITING_CONFIRMATION, ActionStatus.QUEUED}:
            return action.model_dump()
        queue = self.device_queues.setdefault(action.device_id, [])
        if action.action_id in queue:
            queue[:] = [queued_id for queued_id in queue if queued_id != action.action_id]
        action.status = ActionStatus.REJECTED
        action.updated_at = self._now_iso()
        action.confirmation_reason = reason or action.confirmation_reason
        device = self.devices.get(action.device_id)
        if device:
            device.queue_depth = len(queue)
            if device.current_action_id == action.action_id:
                device.current_action_id = None
            self._persist_device(action.device_id)
        self._persist_action(action.action_id)
        self._persist_queue(action.device_id)
        OperationLogger.log_event(
            "device_action_cancelled",
            "cancelled",
            f"Ação {action.action_type} cancelada antes da execução.",
            device_id=action.device_id,
            action_id=action.action_id,
            action_type=action.action_type,
            risk=action.risk.value,
            cancellation_reason=action.confirmation_reason,
            goal_id=action.goal_id,
            reason_code="device_confirmation_cancelled",
        )
        self._emit_event("device_action_cancelled", action.model_dump())
        return action.model_dump()

    def get_pending_confirmations(
        self,
        *,
        session_id: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> list[dict]:
        pending = []
        for action in self.actions.values():
            if action.status != ActionStatus.AWAITING_CONFIRMATION:
                continue
            if not self._action_context_matches(action, session_id=session_id, requested_by=requested_by):
                continue
            pending.append(action.model_dump())
        pending.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return pending

    def get_pending_actions_for_session(
        self,
        session_id: str,
        *,
        requested_by: Optional[str] = None,
    ) -> list[dict]:
        return self.get_pending_confirmations(session_id=session_id, requested_by=requested_by)

    def heartbeat(self, heartbeat: DeviceHeartbeat) -> dict:
        device = self.devices.get(heartbeat.device_id)
        if not device:
            raise ValueError(f"Dispositivo {heartbeat.device_id} não registrado.")
        now = self._now_iso()
        device.last_seen_at = now
        device.last_heartbeat_at = now
        device.current_action_id = heartbeat.current_action_id
        if heartbeat.last_result:
            device.last_result = heartbeat.last_result
        if heartbeat.status == DeviceStatus.BUSY or heartbeat.current_action_id:
            device.status = DeviceStatus.BUSY
            if heartbeat.current_action_id and heartbeat.current_action_id in self.actions:
                action = self.actions[heartbeat.current_action_id]
                if action.status == ActionStatus.DISPATCHED:
                    action.status = ActionStatus.RUNNING
                    action.updated_at = now
                    self._persist_action(action.action_id)
        elif heartbeat.status == DeviceStatus.OFFLINE:
            device.status = DeviceStatus.OFFLINE
        else:
            device.status = DeviceStatus.ONLINE
        OperationLogger.log_event(
            "device_heartbeat",
            "ok",
            f"Heartbeat recebido de {device.device_name}.",
            device_id=device.device_id,
            device_status=device.status.value,
            current_action_id=device.current_action_id,
        )
        payload = self._refresh_device_status(device).model_dump()
        self._persist_device(device.device_id)
        self._emit_event("device_heartbeat", payload)
        return payload

    def get_next_action(self, device_id: str) -> Optional[dict]:
        if device_id not in self.devices:
            raise ValueError(f"Dispositivo {device_id} não registrado.")
        self._mark_device_seen(device_id)
        queue = self.device_queues.setdefault(device_id, [])
        while queue:
            action_id = queue.pop(0)
            action = self.actions.get(action_id)
            if not action or action.status != ActionStatus.QUEUED:
                continue
            action.status = ActionStatus.DISPATCHED
            action.dispatched_at = self._now_iso()
            action.updated_at = action.dispatched_at
            device = self.devices[device_id]
            device.last_action_id = action.action_id
            device.current_action_id = action.action_id
            device.status = DeviceStatus.BUSY
            device.queue_depth = len(queue)
            self._persist_action(action.action_id)
            self._persist_device(device_id)
            self._persist_queue(device_id)
            OperationLogger.log_event(
                "device_action_dispatched",
                "dispatched",
                f"Ação {action.action_type} despachada para {device.device_name}.",
                device_id=action.device_id,
                action_id=action.action_id,
                action_type=action.action_type,
                target=action.target,
                goal_id=action.goal_id,
            )
            payload = action.model_dump()
            self._emit_event("device_action_dispatched", payload)
            return payload
        self.devices[device_id].queue_depth = 0
        self._persist_device(device_id)
        self._persist_queue(device_id)
        return None

    def submit_action_result(self, device_id: str, action_id: str, result: ActionResult) -> dict:
        action = self.actions.get(action_id)
        if not action:
            raise ValueError(f"Ação {action_id} não encontrada.")
        if action.device_id != device_id:
            raise ValueError("Resultado enviado para dispositivo incorreto.")
        self._mark_device_seen(device_id)
        action.result = result.model_dump()
        action.completed_at = result.finished_at or self._now_iso()
        action.updated_at = action.completed_at
        error_code = self._classify_action_error(action, result.error, result.error_code)
        action.last_error = result.error
        action.last_error_code = error_code if not result.success else None
        device = self.devices.get(device_id)
        if device:
            device.last_action_id = action.action_id
            device.current_action_id = None
            device.queue_depth = len(self.device_queues.get(device_id, []))
            device.last_result = result.model_dump()
            device.status = DeviceStatus.ONLINE
        if result.success:
            action.status = ActionStatus.COMPLETED
            event_type = "device_action_completed"
            event_status = "succeeded"
        else:
            should_retry, reason_code = self._error_aware_retry_policy(action, error_code)
            if should_retry:
                action.retry_count += 1
                action.status = ActionStatus.QUEUED
                action.terminal_failure = False
                action.terminal_reason_code = None
                action.dispatched_at = None
                self.device_queues.setdefault(action.device_id, []).append(action.action_id)
                event_type = "device_action_retry_scheduled"
                event_status = "warning"
            else:
                action.status = ActionStatus.FAILED
                action.terminal_failure = True
                action.terminal_reason_code = reason_code
                event_type = "device_action_failed"
                event_status = "failed"
        self._persist_action(action.action_id)
        self._persist_queue(action.device_id)
        if device:
            self._persist_device(device_id)
        OperationLogger.log_event(
            event_type,
            event_status,
            f"Ação {action.action_type} {'concluída' if result.success else 'falhou'} em {device.device_name if device else device_id}.",
            device_id=device_id,
            action_id=action.action_id,
            action_type=action.action_type,
            target=action.target,
            success=result.success,
            output=result.output,
            error=result.error,
            error_code=error_code,
            artifacts=result.artifacts,
            metadata=result.metadata,
            goal_id=action.goal_id,
            reason_code=action.terminal_reason_code,
            retry_count=action.retry_count,
            max_retries=action.max_retries,
        )
        payload = action.model_dump()
        self._emit_event(event_type, payload)
        return payload

    def _build_action_summary(self, action_type: str, target: Optional[str], parameters: dict) -> str:
        core = target or parameters.get("command") or parameters.get("url") or parameters.get("app") or "-"
        return f"{action_type} -> {core}"
