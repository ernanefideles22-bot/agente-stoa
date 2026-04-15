from __future__ import annotations

from collections import Counter
from typing import Optional

from operation_log import OperationLogger


class ExecutionEventQuery:
    @staticmethod
    def _severity_from_status(status: str) -> str:
        if status in {"error", "failed"}:
            return "error"
        if status in {"warning"}:
            return "warning"
        return "info"

    @staticmethod
    def _taxonomy_from_legacy(event: dict) -> tuple[str, str, str, str]:
        event_type = event.get("event_type") or "unknown"
        if event_type in {"preview_created", "preview_replaced"}:
            return "preview.created", "preview", "preview", "created"
        if event_type == "preview_cancelled":
            return "preview.cancelled", "preview", "preview", "cancelled"
        if event_type == "preview_expired":
            return "preview.expired", "preview", "preview", "expired"
        if event_type == "preflight_failed":
            return "validation.failed", "validation", "operation", "failed"
        if event_type == "preflight_warning":
            return "validation.warning", "validation", "operation", "warning"
        if event_type == "preview_applied":
            return "operation.applied", "operation", "operation", "applied"
        if event_type == "rollback_executed":
            return "operation.rolled_back", "operation", "operation", "rolled_back"
        if event_type == "rollback_failed":
            return "operation.failed", "operation", "operation", "failed"
        if event_type == "orchestrator_decision":
            return "guard.decided", "guard", "decision", "recorded"
        if event_type == "device_registered":
            return "device.registered", "device", "device", "registered"
        if event_type == "device_heartbeat":
            return "device.heartbeat", "device", "device", "heartbeat"
        if event_type == "device_action_requires_confirmation":
            return "device.confirmation_requested", "device", "operation", "awaiting_confirmation"
        if event_type == "device_action_confirmed":
            return "device.confirmed", "device", "operation", "confirmed"
        if event_type == "device_action_queued":
            return "device.queued", "device", "operation", "queued"
        if event_type == "device_action_dispatched":
            return "device.dispatched", "device", "operation", "dispatched"
        if event_type == "device_action_completed":
            return "device.completed", "device", "operation", "completed"
        if event_type == "device_action_failed":
            return "device.failed", "device", "operation", "failed"
        if event_type == "device_action_retry_scheduled":
            return "device.retrying", "device", "operation", "retrying"
        if event_type == "device_action_timed_out_retrying":
            return "device.retrying", "device", "operation", "retrying"
        if event_type == "device_action_timed_out_failed":
            return "device.timeout_failed", "device", "operation", "failed"
        return f"legacy.{event_type}", "legacy", "event", "observed"

    @staticmethod
    def normalize(raw_event: dict) -> dict:
        metadata = raw_event.get("metadata") or {}
        is_execution_event = raw_event.get("event_type") == "execution_event"
        if is_execution_event and metadata:
            normalized = dict(metadata)
            normalized.setdefault("logged_event_type", raw_event.get("event_type"))
            normalized.setdefault("logged_status", raw_event.get("status"))
            normalized.setdefault("logged_summary", raw_event.get("summary"))
            normalized.setdefault("timestamp", raw_event.get("timestamp"))
            normalized.setdefault("severity", metadata.get("severity") or raw_event.get("status") or "info")
            return normalized

        event_code, event_domain, event_subject, event_outcome = ExecutionEventQuery._taxonomy_from_legacy(raw_event)
        return {
            "event_id": f"legacy_{raw_event.get('timestamp', 'unknown')}_{event_code}",
            "event_type": raw_event.get("event_type") or "unknown",
            "event_code": event_code,
            "event_domain": event_domain,
            "event_subject": event_subject,
            "event_outcome": event_outcome,
            "severity": ExecutionEventQuery._severity_from_status(raw_event.get("status") or "info"),
            "phase": (metadata.get("phase") or raw_event.get("phase") or "observing"),
            "goal_id": raw_event.get("goal_id") or metadata.get("goal_id"),
            "step_id": raw_event.get("step_id") or metadata.get("step_id"),
            "operation_id": raw_event.get("operation_id") or metadata.get("operation_id") or raw_event.get("action_id"),
            "preview_id": raw_event.get("preview_id") or metadata.get("preview_id"),
            "reason_code": raw_event.get("reason_code") or metadata.get("reason_code") or event_code,
            "summary": raw_event.get("summary") or metadata.get("summary") or event_code,
            "timestamp": raw_event.get("timestamp"),
            "metadata": metadata,
        }

    @staticmethod
    def query(
        *,
        goal_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        phase: Optional[str] = None,
        severity: Optional[str] = None,
        event_domain: Optional[str] = None,
        limit: int = 30,
    ) -> list[dict]:
        events = [ExecutionEventQuery.normalize(event) for event in OperationLogger._read_all()]
        if goal_id:
            events = [event for event in events if event.get("goal_id") == goal_id]
        if operation_id:
            events = [event for event in events if event.get("operation_id") == operation_id]
        if phase:
            events = [event for event in events if event.get("phase") == phase]
        if severity:
            events = [event for event in events if event.get("severity") == severity]
        if event_domain:
            events = [event for event in events if event.get("event_domain") == event_domain]
        events.sort(key=lambda item: item.get("timestamp") or "")
        return list(reversed(events[-max(limit, 0):]))

    @staticmethod
    def summarize(events: list[dict]) -> dict:
        if not events:
            return {
                "count": 0,
                "by_severity": {},
                "by_phase": {},
                "by_domain": {},
                "progress": {"done_steps": 0, "failed_steps": 0, "in_progress_steps": 0},
                "latest_goal_id": None,
                "latest_operation_id": None,
            }
        severity_counts = Counter(event.get("severity") or "info" for event in events)
        phase_counts = Counter(event.get("phase") or "unknown" for event in events)
        domain_counts = Counter(event.get("event_domain") or "unknown" for event in events)
        progress = {
            "done_steps": sum(1 for event in events if event.get("event_code") == "step.completed"),
            "failed_steps": sum(1 for event in events if event.get("event_code") in {"step.failed", "goal.failed", "operation.failed", "validation.failed"}),
            "in_progress_steps": sum(1 for event in events if event.get("event_code") in {"step.in_progress", "validation.running", "operation.applied"}),
        }
        latest = events[0]
        return {
            "count": len(events),
            "by_severity": dict(severity_counts),
            "by_phase": dict(phase_counts),
            "by_domain": dict(domain_counts),
            "progress": progress,
            "latest_goal_id": latest.get("goal_id"),
            "latest_operation_id": latest.get("operation_id"),
        }
