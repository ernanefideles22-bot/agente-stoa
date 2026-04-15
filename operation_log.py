import json
from datetime import datetime, timedelta
from pathlib import Path


class OperationLogger:
    BASE_DIR = Path(__file__).parent.resolve()
    LOG_FILE = BASE_DIR / ".stoa_ops_log.jsonl"

    @staticmethod
    def log_path() -> str:
        return OperationLogger.LOG_FILE.as_posix()

    @staticmethod
    def log_event(event_type: str, status: str, summary: str, **kwargs) -> None:
        OperationLogger.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "status": status,
            "summary": summary,
        }
        for key, value in kwargs.items():
            if value is not None:
                event[key] = value
        with OperationLogger.LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    @staticmethod
    def _read_all() -> list[dict]:
        if not OperationLogger.LOG_FILE.exists():
            return []
        events = []
        for line in OperationLogger.LOG_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    @staticmethod
    def read_recent(limit: int = 20) -> list[dict]:
        events = OperationLogger._read_all()
        return list(reversed(events[-max(limit, 0):]))


    @staticmethod
    def _events_within_hours(hours: int = 24) -> list[dict]:
        cutoff = datetime.now() - timedelta(hours=max(hours, 0))
        events = []
        for event in OperationLogger._read_all():
            timestamp_raw = event.get("timestamp")
            try:
                timestamp = datetime.fromisoformat(timestamp_raw) if timestamp_raw else None
            except Exception:
                timestamp = None
            if timestamp and timestamp >= cutoff:
                events.append(event)
        return events

    @staticmethod
    def count_by_event_type(hours: int = 24) -> dict:
        counts = {}
        for event in OperationLogger._events_within_hours(hours):
            event_type = event.get("event_type") or "unknown"
            counts[event_type] = counts.get(event_type, 0) + 1
        return counts

    @staticmethod
    def count_by_final_status(hours: int = 24) -> dict:
        events = OperationLogger._events_within_hours(hours)
        operation_ids = []
        seen = set()
        for event in events:
            operation_id = event.get("operation_id")
            if operation_id and operation_id not in seen:
                seen.add(operation_id)
                operation_ids.append(operation_id)

        counts = {
            "preview_only": 0,
            "applied": 0,
            "rolled_back": 0,
            "failed": 0,
            "cancelled": 0,
            "expired": 0,
        }
        for operation_id in operation_ids:
            summary = OperationLogger.summarize_operation(operation_id)
            if not summary:
                continue
            final_status = summary.get("final_status")
            if final_status in counts:
                counts[final_status] += 1
            else:
                counts[final_status] = counts.get(final_status, 0) + 1
        return counts

    @staticmethod
    def most_changed_files(hours: int = 24, limit: int = 10) -> list[dict]:
        # Contagem por operação, não por evento, para evitar inflar arquivos repetidos dentro do mesmo fluxo.
        events = OperationLogger._events_within_hours(hours)
        file_ops = {}
        for event in events:
            operation_id = event.get("operation_id") or f"event:{event.get('timestamp')}:{event.get('event_type')}"
            for file_path in event.get("files") or []:
                file_ops.setdefault(file_path, set()).add(operation_id)
        ranked = [
            {"path": path, "count": len(op_ids)}
            for path, op_ids in file_ops.items()
        ]
        ranked.sort(key=lambda item: (-item["count"], item["path"]))
        return ranked[:max(limit, 0)]

    @staticmethod
    def preview_funnel(hours: int = 24) -> dict:
        counts = OperationLogger.count_by_event_type(hours)
        return {
            "preview_created": counts.get("preview_created", 0),
            "preview_applied": counts.get("preview_applied", 0),
            "preview_cancelled": counts.get("preview_cancelled", 0),
            "preview_expired": counts.get("preview_expired", 0),
            "apply_preview_missing": counts.get("apply_preview_missing", 0),
            "rollbacks": counts.get("rollback_executed", 0) + counts.get("rollback_failed", 0),
        }

    @staticmethod
    def summarize_metrics(hours: int = 24) -> dict:
        events = OperationLogger._events_within_hours(hours)
        event_type_counts = OperationLogger.count_by_event_type(hours)
        final_status_counts = OperationLogger.count_by_final_status(hours)
        top_changed_files = OperationLogger.most_changed_files(hours, limit=10)
        funnel = OperationLogger.preview_funnel(hours)
        total_operations = sum(final_status_counts.values())
        rollbacks = final_status_counts.get("rolled_back", 0)
        failures = final_status_counts.get("failed", 0)
        return {
            "hours": hours,
            "total_events": len(events),
            "total_operations": total_operations,
            "final_status_counts": final_status_counts,
            "event_type_counts": event_type_counts,
            "preview_funnel": funnel,
            "top_changed_files": top_changed_files,
            "rollback_rate": (rollbacks / total_operations) if total_operations else 0,
            "failure_rate": (failures / total_operations) if total_operations else 0,
        }

    @staticmethod
    def filter_by_event_type(event_type: str, limit: int = 20) -> list[dict]:
        matched = [event for event in OperationLogger._read_all() if event.get("event_type") == event_type]
        return list(reversed(matched[-max(limit, 0):]))

    @staticmethod
    def filter_by_status(status: str, limit: int = 20) -> list[dict]:
        matched = [event for event in OperationLogger._read_all() if event.get("status") == status]
        return list(reversed(matched[-max(limit, 0):]))

    @staticmethod
    def find_last_event(event_type: str) -> dict | None:
        for event in reversed(OperationLogger._read_all()):
            if event.get("event_type") == event_type:
                return event
        return None

    @staticmethod
    def recent_affected_files(limit: int = 20) -> list[str]:
        files = []
        seen = set()
        for event in OperationLogger.read_recent(limit=limit):
            for file_path in event.get("files") or []:
                if file_path not in seen:
                    seen.add(file_path)
                    files.append(file_path)
        return files

    @staticmethod
    def summarize_recent(hours: int = 24) -> dict:
        cutoff = datetime.now() - timedelta(hours=max(hours, 0))
        events = []
        for event in OperationLogger._read_all():
            timestamp_raw = event.get("timestamp")
            try:
                timestamp = datetime.fromisoformat(timestamp_raw) if timestamp_raw else None
            except Exception:
                timestamp = None
            if timestamp and timestamp >= cutoff:
                events.append(event)

        affected_files = []
        seen_files = set()
        for event in reversed(events):
            for file_path in event.get("files") or []:
                if file_path not in seen_files:
                    seen_files.add(file_path)
                    affected_files.append(file_path)

        return {
            "total_events": len(events),
            "applied": sum(1 for event in events if event.get("event_type") in {"preview_applied", "changeset_executed"}),
            "failed": sum(1 for event in events if event.get("status") == "error"),
            "rollbacks": sum(1 for event in events if event.get("event_type") in {"rollback_executed", "rollback_failed"}),
            "previews_created": sum(1 for event in events if event.get("event_type") == "preview_created"),
            "affected_files": affected_files,
        }

    @staticmethod
    def find_by_operation_id(operation_id: str) -> list[dict]:
        if not operation_id:
            return []
        matched = [event for event in OperationLogger._read_all() if event.get("operation_id") == operation_id]
        return matched


    @staticmethod
    def summarize_operation(operation_id: str) -> dict | None:
        events = OperationLogger.find_by_operation_id(operation_id)
        if not events:
            return None

        event_types = [event.get("event_type") for event in events]
        files = []
        seen_files = set()
        preview_id = None
        step_count = None
        rollback_triggered = False
        error = None
        created_at = events[0].get("timestamp") if events else None
        last_event_at = events[-1].get("timestamp") if events else None

        for event in events:
            if not preview_id and event.get("preview_id"):
                preview_id = event.get("preview_id")
            if step_count is None and event.get("step_count") is not None:
                step_count = event.get("step_count")
            rollback_triggered = rollback_triggered or bool(event.get("rollback_triggered"))
            for file_path in event.get("files") or []:
                if file_path not in seen_files:
                    seen_files.add(file_path)
                    files.append(file_path)

        for event in reversed(events):
            if event.get("event_type") in {"changeset_failed", "rollback_failed"}:
                error = event.get("summary") or event.get("status")
                break

        # Precedência de status terminal, do mais forte para o mais específico.
        # rollback_failed/changeset_failed sem rollback bem-sucedido => failed
        # changeset_failed + rollback_executed => rolled_back
        # preview_applied + changeset_executed sem falha => applied
        # preview_cancelled => cancelled
        # preview_expired => expired
        # apenas preview_created => preview_only
        if "preview_cancelled" in event_types:
            final_status = "cancelled"
        elif "preview_expired" in event_types:
            final_status = "expired"
        elif "changeset_failed" in event_types and "rollback_executed" in event_types:
            final_status = "rolled_back"
        elif "changeset_failed" in event_types:
            final_status = "failed"
        elif "preview_applied" in event_types and "changeset_executed" in event_types:
            final_status = "applied"
        else:
            final_status = "preview_only"

        return {
            "operation_id": operation_id,
            "preview_id": preview_id,
            "event_count": len(events),
            "final_status": final_status,
            "files": files,
            "step_count": step_count,
            "rollback_triggered": rollback_triggered or final_status == "rolled_back",
            "error": error,
            "created_at": created_at,
            "last_event_at": last_event_at,
            "events": [
                {
                    "timestamp": event.get("timestamp"),
                    "event_type": event.get("event_type"),
                    "status": event.get("status"),
                }
                for event in events
            ],
        }
