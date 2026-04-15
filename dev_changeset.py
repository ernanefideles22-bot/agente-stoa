import re
from pathlib import Path

from dev_executor import DevExecutor
from dev_preflight import DevPreflightChecker
from operation_log import OperationLogger


class DevChangeSetExecutor:
    MODIFYING_STEP_TYPES = {
        "write_file",
        "append_to_file",
        "replace_in_file",
        "replace_block",
        "replace_function",
        "replace_class",
        "insert_after_function",
        "insert_after_class",
        "insert_route",
    }
    PREVIEW_MAX_DIFF_LINES = 80
    PREVIEW_MAX_DIFF_CHARS = 4000

    @staticmethod
    def _summarize_diff(diff_text: str) -> dict:
        added = 0
        removed = 0
        for line in (diff_text or '').splitlines():
            if line.startswith('+++') or line.startswith('---') or line.startswith('@@'):
                continue
            if line.startswith('+'):
                added += 1
            elif line.startswith('-'):
                removed += 1
        return {'added_lines': added, 'removed_lines': removed}

    @staticmethod
    def _truncate_diff(diff_text: str) -> tuple[str, bool]:
        if not diff_text:
            return '', False
        lines = diff_text.splitlines()
        truncated = False
        if len(lines) > DevChangeSetExecutor.PREVIEW_MAX_DIFF_LINES:
            lines = lines[:DevChangeSetExecutor.PREVIEW_MAX_DIFF_LINES]
            truncated = True
        truncated_text = '\n'.join(lines)
        if len(truncated_text) > DevChangeSetExecutor.PREVIEW_MAX_DIFF_CHARS:
            truncated_text = truncated_text[:DevChangeSetExecutor.PREVIEW_MAX_DIFF_CHARS].rstrip()
            truncated = True
        if truncated:
            truncated_text += '\n... diff truncado ...'
        return truncated_text, truncated

    @staticmethod
    def _extract_backup_path(result: str):
        match = re.search(r"^Backup:\s*(.+)$", result or "", re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _step_success(result: str) -> bool:
        text = (result or "").strip()
        if not text:
            return False
        return "❌" not in text

    @staticmethod
    def preview(change_set: dict, project_index: dict | None = None) -> dict:
        steps = change_set.get("steps") or []
        files_to_change = []
        preview_steps = []
        simulation_errors = []

        for index, step in enumerate(steps):
            step_type = step.get("type", "unknown")
            path = step.get("path")
            would_modify = step_type in DevChangeSetExecutor.MODIFYING_STEP_TYPES
            step_preview = {
                "index": index,
                "type": step_type,
                "path": path,
                "would_modify": would_modify,
            }

            if would_modify and path and path not in files_to_change:
                files_to_change.append(path)

            if would_modify:
                simulation = DevExecutor.simulate_step(step)
                if simulation.get("success"):
                    diff_text = simulation.get("estimated_diff", "")
                    diff_summary = DevChangeSetExecutor._summarize_diff(diff_text)
                    truncated_diff, truncated = DevChangeSetExecutor._truncate_diff(diff_text)
                    step_preview.update({
                        "estimated_diff": truncated_diff,
                        "estimated_diff_summary": diff_summary,
                        "estimated_diff_truncated": truncated,
                    })
                else:
                    step_preview["simulation_error"] = simulation.get("error", "Falha ao simular a alteração")
                    simulation_errors.append({
                        "step_index": index,
                        "type": step_type,
                        "path": path,
                        "message": step_preview["simulation_error"],
                    })

            preview_steps.append(step_preview)

        preflight = DevPreflightChecker.run_preflight(change_set, project_index=project_index)
        success = preflight.get("ok", True) and not simulation_errors
        if simulation_errors:
            summary = f"Preview gerado com {len(simulation_errors)} problema(s) de simulação."
        else:
            summary = (
                f"Preview pronto: {len(preview_steps)} etapa(s), {len(files_to_change)} arquivo(s) afetado(s)."
                if preflight.get("ok", True)
                else f"Preview detectou conflitos em {len(preflight.get('errors') or [])} etapa(s)."
            )

        return {
            "success": success,
            "mode": "preview",
            "files_to_change": files_to_change,
            "steps": preview_steps,
            "preflight": preflight,
            "simulation_errors": simulation_errors,
            "summary": summary,
        }

    @staticmethod
    def _execute_step(step: dict) -> str:
        step_type = step.get("type")
        path = step.get("path")

        if step_type == "write_file":
            return DevExecutor.write_file(path, step.get("content", ""))
        if step_type == "append_to_file":
            return DevExecutor.append_to_file(path, step.get("content", ""))
        if step_type == "replace_in_file":
            return DevExecutor.replace_in_file(path, step.get("target", ""), step.get("replacement", ""))
        if step_type == "replace_block":
            return DevExecutor.replace_block(path, step.get("start_marker", ""), step.get("end_marker", ""), step.get("replacement", ""))
        if step_type == "replace_function":
            return DevExecutor.replace_function_in_file(path, step.get("symbol_name", ""), step.get("content", ""))
        if step_type == "replace_class":
            return DevExecutor.replace_class_in_file(path, step.get("symbol_name", ""), step.get("content", ""))
        if step_type == "insert_after_function":
            return DevExecutor.insert_after_function(path, step.get("symbol_name", ""), step.get("content", ""))
        if step_type == "insert_after_class":
            return DevExecutor.insert_after_class(path, step.get("symbol_name", ""), step.get("content", ""))
        if step_type == "insert_route":
            return DevExecutor.insert_route(path, step.get("content", ""))
        if step_type == "validate_file":
            return DevExecutor.run_validation(path)
        if step_type == "import_check":
            return DevExecutor.run_import_check(path)
        return f"❌ Tipo de step não suportado: {step_type}"

    @staticmethod
    def execute(change_set: dict, operation_id: str | None = None) -> dict:
        steps = change_set.get("steps") or []
        applied_steps = []
        failed_step = None
        rollback_result = None

        for index, step in enumerate(steps):
            step_type = step.get("type", "unknown")
            path = step.get("path")
            try:
                result = DevChangeSetExecutor._execute_step(step)
            except Exception as exc:
                result = f"❌ Erro ao executar step: {exc}"

            success = DevChangeSetExecutor._step_success(result)
            step_record = {
                "index": index,
                "type": step_type,
                "path": path,
                "success": success,
                "result": result,
                "backup_path": DevChangeSetExecutor._extract_backup_path(result),
            }

            if success:
                applied_steps.append(step_record)
                continue

            failed_step = {
                "index": index,
                "type": step_type,
                "path": path,
                "error": result,
            }
            rollback_steps = list(applied_steps)
            if step_type in DevChangeSetExecutor.MODIFYING_STEP_TYPES and step_record.get("backup_path"):
                rollback_steps.append(step_record)
            applied_steps = rollback_steps if rollback_steps else applied_steps
            break

        if failed_step:
            rollback_result = DevChangeSetExecutor.rollback(applied_steps, operation_id=operation_id)

        success = failed_step is None
        summary = (
            f"Change set aplicado com sucesso: {len(applied_steps)} etapa(s)."
            if success
            else f"Change set interrompido na etapa {failed_step['index'] + 1}; rollback {'ok' if rollback_result and rollback_result.get('success') else 'parcial/dispensado'}."
        )

        files = []
        for step in steps:
            step_path = step.get("path")
            if step_path and step_path not in files:
                files.append(step_path)

        if success:
            OperationLogger.log_event(
                "changeset_executed",
                "success",
                summary,
                files=files,
                step_count=len(steps),
                rollback_triggered=False,
                operation_id=operation_id,
                metadata={
                    "applied_step_count": len(applied_steps),
                },
            )
        else:
            OperationLogger.log_event(
                "changeset_failed",
                "error",
                summary,
                files=files,
                step_count=len(steps),
                rollback_triggered=bool(rollback_result),
                operation_id=operation_id,
                metadata={
                    "failed_step": failed_step,
                },
            )
            if rollback_result:
                OperationLogger.log_event(
                    "rollback_executed" if rollback_result.get("success") else "rollback_failed",
                    "success" if rollback_result.get("success") else "error",
                    "Rollback executado após falha no change set." if rollback_result.get("success") else "Rollback falhou ou foi parcial após falha no change set.",
                    files=files,
                    step_count=len(rollback_result.get("details") or []),
                    rollback_triggered=True,
                    operation_id=operation_id,
                    metadata={
                        "rollback": rollback_result,
                    },
                )

        return {
            "success": success,
            "applied_steps": applied_steps,
            "failed_step": failed_step,
            "rollback": rollback_result,
            "summary": summary,
        }

    @staticmethod
    def rollback(applied_steps: list[dict], operation_id: str | None = None) -> dict:
        details = []
        success = True

        for step in reversed(applied_steps):
            step_type = step.get("type")
            path = step.get("path")
            backup_path = step.get("backup_path")

            if step_type not in DevChangeSetExecutor.MODIFYING_STEP_TYPES:
                continue

            if not backup_path or backup_path == "arquivo novo - backup não necessário":
                details.append({
                    "index": step.get("index"),
                    "type": step_type,
                    "path": path,
                    "restored": False,
                    "detail": "Sem backup disponível para rollback desta etapa.",
                })
                success = False
                continue

            try:
                target_path = DevExecutor.resolve_path(path)
                source_backup = DevExecutor.resolve_path(backup_path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(source_backup.read_text(encoding="utf-8"), encoding="utf-8")
                details.append({
                    "index": step.get("index"),
                    "type": step_type,
                    "path": path,
                    "restored": True,
                    "backup_path": backup_path,
                })
            except Exception as exc:
                success = False
                details.append({
                    "index": step.get("index"),
                    "type": step_type,
                    "path": path,
                    "restored": False,
                    "backup_path": backup_path,
                    "detail": str(exc),
                })

        return {
            "attempted": bool(applied_steps),
            "success": success,
            "details": details,
        }
