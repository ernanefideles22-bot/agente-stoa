import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path

from dev_changeset import DevChangeSetExecutor
from dev_executor import DevExecutor
from dev_parser import DevCommandParser
from dev_planner import DevPlanner
from dev_preflight import DevPreflightChecker
from operation_log import OperationLogger
from project_indexer import ProjectIndexer
from system_executor import SystemExecutor
from state_store import StateStore


class Planner:
    """Orquestrador de planejamento e execução de mudanças no código"""

    def __init__(self, state_store: StateStore):
        self.state_store = state_store
        self.pending_preview = None
        self._rehydrate_state()

    def _rehydrate_state(self) -> None:
        stored_preview = self.state_store.load_pending_preview()
        if stored_preview:
            self.pending_preview = stored_preview
            if self._get_pending_preview_status().get('expired'):
                self.pending_preview = None
                self.state_store.clear_pending_preview()

    def _persist_pending_preview(self) -> None:
        if self.pending_preview:
            self.state_store.save_pending_preview(self.pending_preview)
        else:
            self.state_store.clear_pending_preview()

    @staticmethod
    def _generate_preview_id() -> str:
        return f"preview-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _generate_operation_id() -> str:
        return f"op_{uuid.uuid4().hex[:10]}"

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    def _now_iso(self) -> str:
        return self._now().isoformat()

    def _preview_ttl_minutes(self) -> int:
        return 15  # STOAQuantumBrain.PREVIEW_TTL_MINUTES

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

    def plan_and_preview(self, command: str, project_index: dict | None = None, working_context: dict | None = None) -> Tuple[str, Dict[str, Any]]:
        """Planeja e cria preview de mudanças"""
        from dev_changeset import DevChangeSetExecutor
        from dev_executor import DevExecutor
        from dev_parser import DevCommandParser
        from dev_planner import DevPlanner
        from dev_preflight import DevPreflightChecker
        from operation_log import OperationLogger
        from project_indexer import ProjectIndexer
        from system_executor import SystemExecutor

        normalized_command = (command or '').lower().strip()
        preview_mode = (
            normalized_command.startswith('planeje ')
            or normalized_command.startswith('simule ')
            or ' simule ' in f' {normalized_command} '
            or 'dry run' in normalized_command
            or 'mostre o patch' in normalized_command
            or 'o que mudaria' in normalized_command
        )

        if preview_mode:
            parsed = DevCommandParser.parse(command)
            action = parsed.get('action', 'unknown')
            if action == 'unknown':
                planned = DevPlanner.plan(
                    command,
                    project_index=project_index,
                    working_context=working_context,
                )
                if planned.get('action') == 'apply_change_set' and planned.get('steps'):
                    parsed = planned
                    action = 'apply_change_set'

            if action == 'apply_change_set':
                project_index_data = ProjectIndexer.build_index()
                preview_result = DevChangeSetExecutor.preview(parsed, project_index=project_index_data)
                if preview_result.get('success'):
                    pending_preview, replaced_preview = self._create_pending_preview(parsed, preview_result)
                    OperationLogger.log_event(
                        'preview_created',
                        'success',
                        preview_result.get('summary', 'Preview criado.'),
                        operation_id=pending_preview['operation_id'],
                        preview_id=pending_preview['id'],
                        files=pending_preview['files_to_change'],
                        step_count=pending_preview['step_count'],
                    )
                    rendered = self._format_preview_result(preview_result)
                    return (
                        f"Preview criado com sucesso.\n"
                        f"Preview ID: {pending_preview['id']}\n"
                        f"Operation ID: {pending_preview['operation_id']}\n\n"
                        f"{rendered}"
                    ), {
                        'operation': 'create_preview',
                        'parsed': parsed,
                        'preview_result': preview_result,
                        'preview_id': pending_preview['id'],
                        'operation_id': pending_preview['operation_id'],
                        'preview_summary': pending_preview['summary'],
                        'preview_created_at': pending_preview['created_at'],
                        'preview_expires_at': pending_preview['expires_at'],
                        'files_to_change': pending_preview['files_to_change'],
                        'step_count': pending_preview['step_count'],
                    }
                else:
                    return f"❌ Falha ao criar preview: {preview_result.get('error', 'Erro desconhecido')}", {
                        'operation': 'create_preview_failed',
                        'parsed': parsed,
                        'preview_result': preview_result,
                    }
            else:
                return f"❌ Comando não reconhecido para preview: {command}", {
                    'operation': 'unknown_command',
                    'parsed': parsed,
                }
        else:
            return f"❌ Modo preview não ativado. Use 'planeje' ou 'simule' para criar previews.", {
                'operation': 'preview_mode_not_active',
            }

    def apply_pending_preview(self) -> Tuple[str, Dict[str, Any]]:
        """Aplica o preview pendente"""
        from dev_changeset import DevChangeSetExecutor
        from dev_preflight import DevPreflightChecker
        from operation_log import OperationLogger
        from project_indexer import ProjectIndexer

        status = self._get_pending_preview_status()
        preview = status.get('preview')
        if not preview:
            OperationLogger.log_event('apply_preview_missing', 'info', 'Tentativa de aplicar preview sem preview pendente.')
            return '❌ Não há preview pendente para aplicar. Gere um preview primeiro com "planeje", "simule" ou "dry run".', {
                'operation': 'apply_preview_missing',
            }
        if status.get('expired'):
            expired_preview = self._clear_pending_preview() or preview
            OperationLogger.log_event(
                'preview_expired',
                'warning',
                f"Preview {expired_preview.get('id', '-')} expirou antes da aplicação.",
                operation_id=expired_preview.get('operation_id'),
                preview_id=expired_preview.get('id'),
                files=expired_preview.get('files_to_change') or [],
                step_count=expired_preview.get('step_count'),
                metadata={'expires_at': expired_preview.get('expires_at')},
            )
            return (
                f"❌ O preview pendente expirou e foi descartado.\n"
                f"Preview ID: {expired_preview.get('id', '-')}\n"
                f"Expirou em: {expired_preview.get('expires_at', '-')}\n"
                f"Gere um novo preview antes de aplicar."
            ), {
                'operation': 'apply_preview_expired',
                'preview_id': expired_preview.get('id'),
                'operation_id': expired_preview.get('operation_id'),
                'expired_at': expired_preview.get('expires_at'),
            }

        parsed = json.loads(json.dumps(preview.get('change_set') or {}))
        project_index = ProjectIndexer.build_index()
        preflight = DevPreflightChecker.run_preflight(parsed, project_index=project_index)
        if not preflight.get('ok', True):
            lines = ['❌ O preview pendente não pode mais ser aplicado porque o preflight falhou:']
            for error in preflight.get('errors', []):
                lines.append(f"- {error.get('message', 'Conflito')} ({error.get('path') or '-'})")
            self._clear_pending_preview()
            OperationLogger.log_event(
                'preflight_failed',
                'error',
                'Preflight falhou ao aplicar preview pendente.',
                preview_id=preview.get('id'),
                files=preview.get('files_to_change') or [],
                step_count=preview.get('step_count'),
                metadata={'errors': preflight.get('errors') or []},
            )
            return "\n".join(lines), {
                'operation': 'apply_preview_preflight_failed',
                'parsed': parsed,
                'preflight': preflight,
                'preview_id': preview.get('id'),
                'operation_id': preview.get('operation_id'),
                'preview_summary': preview.get('summary'),
                'preview_created_at': preview.get('created_at'),
                'preview_expires_at': preview.get('expires_at'),
            }

        change_set_result = DevChangeSetExecutor.execute(parsed, operation_id=preview.get('operation_id'))
        change_set_result['preflight'] = preflight
        preview_id = preview.get('id')
        operation_id = preview.get('operation_id')
        preview_summary = preview.get('summary')
        preview_created_at = preview.get('created_at')
        preview_expires_at = preview.get('expires_at')
        self._clear_pending_preview()
        rendered = self._format_change_set_result(change_set_result)
        OperationLogger.log_event(
            'preview_applied',
            'success' if change_set_result.get('success') else 'error',
            f"Preview {preview_id or '-'} aplicado a partir do estado pendente.",
            operation_id=operation_id,
            preview_id=preview_id,
            files=preview.get('files_to_change') or [],
            step_count=preview.get('step_count'),
            rollback_triggered=bool(change_set_result.get('rollback')),
        )
        return (
            f"Aplicado a partir do preview armazenado.\n"
            f"Preview ID: {preview_id or '-'}\n"
            f"Operation ID: {operation_id or '-'}\n"
            f"Resumo: {preview_summary or '-'}\n"
            f"Criado em: {preview_created_at or '-'}\n"
            f"Expirava em: {preview_expires_at or '-'}\n\n"
            f"{rendered}"
        ), {
            'operation': 'apply_preview_change_set',
            'parsed': parsed,
            'change_set': change_set_result,
            'preflight': preflight,
            'preview_id': preview_id,
            'operation_id': operation_id,
            'preview_summary': preview_summary,
            'preview_created_at': preview_created_at,
            'preview_expires_at': preview_expires_at,
        }

    def cancel_pending_preview(self) -> Tuple[str, Dict[str, Any]]:
        """Cancela o preview pendente"""
        from operation_log import OperationLogger

        status = self._get_pending_preview_status()
        preview = status.get('preview')
        if not preview:
            OperationLogger.log_event('preview_cancelled', 'info', 'Tentativa de cancelar preview sem preview pendente.')
            return '❌ Não há preview pendente para descartar.', {
                'operation': 'cancel_preview_missing',
            }
        self._clear_pending_preview()
        OperationLogger.log_event(
            'preview_cancelled',
            'info',
            f"Preview {preview.get('id', '-')} cancelado pelo usuário.",
            operation_id=preview.get('operation_id'),
            preview_id=preview.get('id'),
            files=preview.get('files_to_change') or [],
            step_count=preview.get('step_count'),
        )
        return (
            f"Preview pendente descartado.\n"
            f"Preview ID: {preview.get('id', '-')}\n"
            f"Resumo anterior: {preview.get('summary') or '-'}"
        ), {
            'operation': 'cancel_preview',
            'preview_id': preview.get('id'),
            'operation_id': preview.get('operation_id'),
        }

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


class Executor:
    """Executor de operações básicas de desenvolvimento"""

    @staticmethod
    def execute_command(command: str, project_index: dict | None = None, working_context: dict | None = None) -> Tuple[str, Dict[str, Any]]:
        """Executa comandos básicos de desenvolvimento"""
        from dev_executor import DevExecutor
        from dev_parser import DevCommandParser
        from system_executor import SystemExecutor

        parsed = DevCommandParser.parse(command)
        action = parsed.get('action', 'unknown')
        path = parsed.get('path')

        try:
            if action == 'list_files':
                files = DevExecutor.list_files()
                response = '\n'.join(files) if files else 'Nenhum arquivo relevante encontrado.'
                return response, {'operation': 'list_files', 'count': len(files), 'parsed': parsed}

            if action == 'read_file' and path:
                return DevExecutor.read_file(path), {'operation': 'read_file', 'path': path, 'parsed': parsed}

            if action == 'validate_file' and path:
                return DevExecutor.run_validation(path), {'operation': 'run_validation', 'path': path, 'parsed': parsed}

            if action == 'import_check' and path:
                return DevExecutor.run_import_check(path), {'operation': 'run_import_check', 'path': path, 'parsed': parsed}

            if action == 'open_vscode':
                return SystemExecutor.run('code'), {'operation': 'open_vscode', 'parsed': parsed}

            return f"❌ Comando não reconhecido: {command}", {
                'operation': 'unknown_command',
                'parsed': parsed,
            }

        except Exception as e:
            return f"❌ Erro ao executar comando: {e}", {
                'operation': 'execution_error',
                'error': str(e),
                'parsed': parsed,
            }
