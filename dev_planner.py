import re
from datetime import datetime, timedelta
from typing import Optional


class DevPlanner:
    FILE_PATTERN = re.compile(r'([\w./\\-]+\.(?:py|txt|md|json|yaml|yml))', re.IGNORECASE)
    CONTEXT_TTL_MINUTES = 30

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r'\s+', ' ', (text or '').strip().lower()).strip()

    @staticmethod
    def _extract_path(command: str) -> Optional[str]:
        match = DevPlanner.FILE_PATTERN.search(command or "")
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_route(command: str) -> tuple[Optional[str], Optional[str]]:
        match = re.search(
            r'(?:rota|endpoint)\s+(get|post|put|delete|patch|options|head)\s+([^\s:]+)',
            command or '',
            re.IGNORECASE,
        )
        if not match:
            return None, None
        return match.group(1).lower(), match.group(2).strip()

    @staticmethod
    def _split(command: str) -> list[str]:
        text = (command or '').strip()
        if not text:
            return []
        parts = re.split(
            r'\s+e\s+depois\s+|\s+e\s+(?=atualize\b|atualizar\b|documente\b|documentar\b|valide\b|validar\b|rode\b|adicione\b|adicionar\b|crie\b|criar\b)',
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _pick_single(paths: list[str]) -> Optional[str]:
        return paths[0] if len(paths) == 1 else None

    @staticmethod
    def _context_is_fresh(working_context: dict | None) -> bool:
        if not working_context:
            return False
        last_touched_at = working_context.get('last_touched_at')
        if not last_touched_at:
            return False
        try:
            last_dt = datetime.fromisoformat(last_touched_at)
        except Exception:
            return False
        return datetime.now(last_dt.tzinfo) - last_dt <= timedelta(minutes=DevPlanner.CONTEXT_TTL_MINUTES)

    @staticmethod
    def _recent_files(working_context: dict | None) -> list[str]:
        files = (working_context or {}).get('last_files') or []
        return [path for path in files if path]

    @staticmethod
    def _last_python_file(working_context: dict | None) -> Optional[str]:
        for path in DevPlanner._recent_files(working_context):
            if path.lower().endswith('.py'):
                return path
        return None

    @staticmethod
    def _last_readme_file(working_context: dict | None) -> Optional[str]:
        for path in DevPlanner._recent_files(working_context):
            lower = path.lower()
            if lower.endswith('.md') and 'readme' in lower:
                return path
        return None

    @staticmethod
    def _resolve_readme(project_index: dict | None, working_context: dict | None) -> tuple[Optional[str], bool, bool, Optional[str]]:
        context_fresh = DevPlanner._context_is_fresh(working_context)
        if context_fresh:
            readme_from_context = DevPlanner._last_readme_file(working_context)
            if readme_from_context:
                return readme_from_context, True, True, None
        if project_index:
            readmes = project_index.get('readme_files') or []
            if len(readmes) == 1:
                return readmes[0], False, True, None
            if len(readmes) > 1:
                return None, False, False, 'Há múltiplos arquivos README candidatos no projeto.'
        return None, False, False, 'Não foi possível inferir um README único com segurança.'

    @staticmethod
    def _resolve_entrypoint(project_index: dict | None, working_context: dict | None) -> tuple[Optional[str], bool, bool, Optional[str]]:
        context_fresh = DevPlanner._context_is_fresh(working_context)
        if context_fresh:
            last_python = DevPlanner._last_python_file(working_context)
            if last_python:
                return last_python, True, True, None
        if project_index:
            entrypoints = project_index.get('entrypoints') or []
            if len(entrypoints) == 1:
                return entrypoints[0], False, True, None
            if len(entrypoints) > 1:
                return None, False, False, 'Há múltiplos entrypoints FastAPI/APIRouter no projeto.'
        return None, False, False, 'Não foi possível inferir um entrypoint FastAPI único com segurança.'

    @staticmethod
    def _resolve_target_file(
        clause: str,
        *,
        inherited_path: Optional[str],
        project_index: dict | None,
        working_context: dict | None,
        prefer_python: bool = False,
    ) -> tuple[Optional[str], bool, bool, Optional[str]]:
        explicit_path = DevPlanner._extract_path(clause)
        if explicit_path:
            return explicit_path, False, False, None
        if inherited_path:
            return inherited_path, False, False, None

        normalized = DevPlanner._normalize(clause)
        context_fresh = DevPlanner._context_is_fresh(working_context)
        if context_fresh and (
            'mesmo arquivo' in normalized
            or normalized in {'continue', 'proximo passo', 'próximo passo', 'retome isso'}
            or 'documente isso tambem' in normalized
            or 'documente isso também' in normalized
        ):
            candidate = DevPlanner._last_python_file(working_context) if prefer_python else DevPlanner._pick_single(DevPlanner._recent_files(working_context))
            if candidate:
                return candidate, True, True, None

        if prefer_python and project_index:
            python_files = list((project_index.get('python_files') or {}).keys())
            if len(python_files) == 1:
                return python_files[0], False, True, None
            if len(python_files) > 1:
                return None, False, False, 'Há múltiplos arquivos Python candidatos; especifique o arquivo-alvo.'

        return None, False, False, 'Não foi possível inferir o arquivo-alvo com segurança.'

    @staticmethod
    def _build_plan_response(
        goal: str,
        steps: list[dict],
        *,
        planner_context_used: bool = False,
        context_fresh: bool = False,
        inferred_from_context: bool = False,
    ) -> dict:
        files = list(dict.fromkeys([step.get('path') for step in steps if step.get('path')]))
        plan_steps = DevPlanner._build_plan_steps(steps, goal=goal)
        return {
            'action': 'apply_change_set',
            'goal': goal,
            'steps': steps,
            'plan_steps': plan_steps,
            'files': files,
            'planner_context_used': planner_context_used,
            'context_fresh': context_fresh,
            'inferred_from_context': inferred_from_context,
        }

    @staticmethod
    def _build_partial_plan_response(
        goal: str,
        reason: str,
        *,
        missing: Optional[list[str]] = None,
        steps: Optional[list[dict]] = None,
        plan_steps: Optional[list[dict]] = None,
        files: Optional[list[str]] = None,
        planner_context_used: bool = False,
        context_fresh: bool = False,
        inferred_from_context: bool = False,
    ) -> dict:
        return {
            'action': 'planner_partial',
            'goal': goal,
            'reason': reason,
            'missing': list(missing or []),
            'steps': list(steps or []),
            'plan_steps': list(plan_steps or []),
            'files': list(files or []),
            'planner_context_used': planner_context_used,
            'context_fresh': context_fresh,
            'inferred_from_context': inferred_from_context,
        }

    @staticmethod
    def _build_unknown_response(
        reason: str,
        *,
        goal: str = '',
        planner_context_used: bool = False,
        context_fresh: bool = False,
        inferred_from_context: bool = False,
    ) -> dict:
        return {
            'action': 'unknown',
            'goal': goal,
            'reason': reason,
            'steps': [],
            'plan_steps': [],
            'planner_context_used': planner_context_used,
            'context_fresh': context_fresh,
            'inferred_from_context': inferred_from_context,
        }

    @staticmethod
    def _clone_plan_steps(plan_steps: list[dict] | None) -> list[dict]:
        return [dict(step) for step in (plan_steps or []) if isinstance(step, dict)]

    @staticmethod
    def _build_plan_steps(steps: list[dict], *, goal: str = '') -> list[dict]:
        plan_steps = []
        seen = set()

        def add_step(title: str, description: str):
            key = (title.strip().lower(), description.strip().lower())
            if key in seen:
                return
            seen.add(key)
            plan_steps.append({
                'id': f"step_{len(plan_steps) + 1}",
                'title': title.strip(),
                'description': description.strip(),
                'status': 'pending',
                'linked_step_types': [],
                'linked_files': [],
                'linked_operation_id': None,
            })

        def bind_last(step_types: list[str], files: list[str]):
            if not plan_steps:
                return
            plan_steps[-1]['linked_step_types'] = list(dict.fromkeys([item for item in step_types if item]))
            plan_steps[-1]['linked_files'] = list(dict.fromkeys([item for item in files if item]))

        for step in steps or []:
            step_type = step.get('type') or ''
            path = step.get('path') or 'arquivo alvo'
            if step_type == 'insert_route':
                method = (step.get('method') or 'get').upper()
                route_path = step.get('route_path') or '/'
                add_step(f"Adicionar rota {route_path}", f"Criar endpoint {method} {route_path} no arquivo {path}")
                bind_last(['insert_route'], [path])
            elif step_type == 'append_to_file':
                content = (step.get('content') or '').strip()
                class_match = re.search(r'^class\s+([A-Za-z_][A-Za-z0-9_]*)', content, re.IGNORECASE | re.MULTILINE)
                function_match = re.search(r'^(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)', content, re.IGNORECASE | re.MULTILINE)
                if class_match:
                    class_name = class_match.group(1)
                    add_step(f"Criar classe {class_name}", f"Adicionar a classe {class_name} no arquivo {path}")
                    bind_last(['append_to_file'], [path])
                elif function_match:
                    function_name = function_match.group(1)
                    add_step(f"Criar função {function_name}", f"Adicionar a função {function_name} no arquivo {path}")
                    bind_last(['append_to_file'], [path])
                elif path.lower().endswith('.md') or 'readme' in path.lower():
                    add_step("Documentar README", f"Atualizar a documentação no arquivo {path}")
                    bind_last(['append_to_file', 'write_file'], [path])
                else:
                    add_step("Aplicar patch", f"Adicionar conteúdo novo no arquivo {path}")
                    bind_last(['append_to_file'], [path])
            elif step_type == 'validate_file':
                add_step("Validar arquivo", f"Executar validação do arquivo {path}")
                bind_last(['validate_file', 'import_check'], [path])
            elif step_type == 'import_check':
                add_step("Validar imports", f"Executar import check do arquivo {path}")
                bind_last(['import_check'], [path])
            elif step_type == 'write_file':
                add_step("Escrever arquivo", f"Gravar conteúdo no arquivo {path}")
                bind_last(['write_file'], [path])
            elif step_type in {'replace_in_file', 'replace_block', 'replace_function', 'replace_class', 'insert_after_function', 'insert_after_class'}:
                add_step("Aplicar patch", f"Modificar estruturalmente o arquivo {path}")
                bind_last([step_type], [path])

        if not plan_steps and goal:
            add_step("Revisar objetivo", f"Organizar a próxima ação para: {goal}")

        return plan_steps

    @staticmethod
    def _readme_doc_step(
        clause: str,
        *,
        route_path: Optional[str] = None,
        method: Optional[str] = None,
        project_index: dict | None = None,
        working_context: dict | None = None,
    ) -> tuple[Optional[dict], bool, bool, Optional[str]]:
        match = re.search(r'(README\.md|[\w./\\-]+\.(?:md|txt))', clause, re.IGNORECASE)
        if not match and 'readme' not in clause.lower() and 'document' not in clause.lower():
            return None, False, False, None
        if match:
            doc_path = match.group(1)
            used_context = False
            inferred = False
            reason = None
        else:
            doc_path, used_context, inferred, reason = DevPlanner._resolve_readme(project_index, working_context)
        if not doc_path:
            return None, used_context, inferred, reason
        if route_path and method:
            content = f"\n\n## Documentação\n- Endpoint adicionado: `{method.upper()} {route_path}`\n"
        else:
            content = f"\n\n## Documentação\n- Atualização solicitada: {clause.strip()}\n"
        return {
            'type': 'append_to_file',
            'path': doc_path,
            'content': content,
        }, used_context, inferred, None

    @staticmethod
    def _plan_next_step(command: str, working_context: dict | None) -> dict:
        context_fresh = DevPlanner._context_is_fresh(working_context)
        if not context_fresh:
            return DevPlanner._build_unknown_response(
                'O contexto operacional expirou; peça o objetivo novamente ou especifique o arquivo/alvo.',
                goal=command,
                context_fresh=False,
            )

        goal = (working_context or {}).get('current_goal')
        last_plan = (working_context or {}).get('last_plan') or {}
        context_plan_steps = DevPlanner._clone_plan_steps((working_context or {}).get('current_plan_steps'))
        pending_steps = [step for step in context_plan_steps if step.get('status') != 'done']
        next_step = pending_steps[0] if pending_steps else None
        fallback_steps = last_plan.get('steps') or []
        if goal or next_step or context_plan_steps or fallback_steps:
            steps_text = []
            if next_step:
                steps_text.append(next_step.get('description') or next_step.get('title'))
            steps_text.extend(step for step in fallback_steps if step and step not in steps_text)
            reason = 'Continuidade do plano anterior com base no contexto operacional atual.'
            return DevPlanner._build_partial_plan_response(
                goal=goal or command,
                reason=reason,
                steps=steps_text,
                plan_steps=context_plan_steps,
                files=DevPlanner._recent_files(working_context),
                planner_context_used=True,
                context_fresh=True,
                inferred_from_context=True,
            )

        return DevPlanner._build_unknown_response(
            'Não há plano recente suficiente para continuar com segurança.',
            goal=command,
            planner_context_used=True,
            context_fresh=True,
            inferred_from_context=True,
        )

    @staticmethod
    def _plan_single(
        clause: str,
        *,
        inherited_path: Optional[str] = None,
        project_index: dict | None = None,
        working_context: dict | None = None,
    ) -> tuple[Optional[dict], dict]:
        original = (clause or '').strip()
        normalized = DevPlanner._normalize(original)

        route_match = re.search(
            r'(?:adicione|adicionar|crie|criar)\s+(?:uma|um)?\s*(?:rota|endpoint)\s+(get|post|put|delete|patch|options|head)\s+([^\s:]+)(?:.*?(?:arquivo\s+|no\s+arquivo\s+|no\s+|em\s+)([\w./\\-]+\.py))?\s*:\s*(.+)$',
            original,
            re.IGNORECASE | re.DOTALL,
        )
        if route_match:
            target_path = route_match.group(3).strip() if route_match.group(3) else None
            used_context = False
            inferred = False
            reason = None
            if not target_path:
                target_path, used_context, inferred, reason = DevPlanner._resolve_entrypoint(project_index, working_context)
            if not target_path:
                return None, {
                    'reason': reason or 'Não foi possível inferir o entrypoint para inserir a rota.',
                    'missing': ['target_file'],
                    'planner_context_used': used_context,
                    'context_fresh': DevPlanner._context_is_fresh(working_context),
                    'inferred_from_context': inferred,
                }
            return {
                'type': 'insert_route',
                'path': target_path,
                'method': route_match.group(1).lower(),
                'route_path': route_match.group(2).strip(),
                'content': route_match.group(4).strip(),
            }, {
                'planner_context_used': used_context,
                'context_fresh': DevPlanner._context_is_fresh(working_context),
                'inferred_from_context': inferred,
            }

        create_class_match = re.search(
            r'(?:crie|criar)\s+uma\s+classe\s+([A-Za-z_][A-Za-z0-9_]*)\b(?:\s+no\s+arquivo|\s+em)?\s*([\w./\\-]+\.py)?',
            original,
            re.IGNORECASE,
        )
        if create_class_match:
            target_path, used_context, inferred, reason = DevPlanner._resolve_target_file(
                original,
                inherited_path=inherited_path,
                project_index=project_index,
                working_context=working_context,
                prefer_python=True,
            )
            if not target_path:
                return None, {
                    'reason': reason or 'Não foi possível inferir o arquivo Python para criar a classe.',
                    'missing': ['target_file'],
                    'planner_context_used': used_context,
                    'context_fresh': DevPlanner._context_is_fresh(working_context),
                    'inferred_from_context': inferred,
                }
            class_name = create_class_match.group(1).strip()
            return {
                'type': 'append_to_file',
                'path': target_path,
                'content': f"\n\nclass {class_name}:\n    pass\n",
            }, {
                'planner_context_used': used_context,
                'context_fresh': DevPlanner._context_is_fresh(working_context),
                'inferred_from_context': inferred,
            }

        add_function_match = re.search(
            r'(?:adicione|adicionar)\s+uma\s+funç(?:ã|a)o\s+([A-Za-z_][A-Za-z0-9_]*)\b(?:\s+no\s+arquivo|\s+em)?\s*([\w./\\-]+\.py)?',
            original,
            re.IGNORECASE,
        )
        if add_function_match:
            target_path, used_context, inferred, reason = DevPlanner._resolve_target_file(
                original,
                inherited_path=inherited_path,
                project_index=project_index,
                working_context=working_context,
                prefer_python=True,
            )
            if not target_path:
                return None, {
                    'reason': reason or 'Não foi possível inferir o arquivo Python para criar a função.',
                    'missing': ['target_file'],
                    'planner_context_used': used_context,
                    'context_fresh': DevPlanner._context_is_fresh(working_context),
                    'inferred_from_context': inferred,
                }
            function_name = add_function_match.group(1).strip()
            return {
                'type': 'append_to_file',
                'path': target_path,
                'content': f"\n\ndef {function_name}():\n    pass\n",
            }, {
                'planner_context_used': used_context,
                'context_fresh': DevPlanner._context_is_fresh(working_context),
                'inferred_from_context': inferred,
            }

        if 'documente isso também' in normalized or 'documente isso tambem' in normalized:
            method, route_path = DevPlanner._extract_route((working_context or {}).get('current_goal') or '')
            doc_step, used_context, inferred, reason = DevPlanner._readme_doc_step(
                original,
                route_path=route_path,
                method=method,
                project_index=project_index,
                working_context=working_context,
            )
            if not doc_step:
                return None, {
                    'reason': reason or 'Não foi possível inferir um README para documentar a mudança.',
                    'missing': ['readme_file'],
                    'planner_context_used': used_context,
                    'context_fresh': DevPlanner._context_is_fresh(working_context),
                    'inferred_from_context': inferred,
                }
            return doc_step, {
                'planner_context_used': used_context,
                'context_fresh': DevPlanner._context_is_fresh(working_context),
                'inferred_from_context': inferred,
            }

        path, used_context, inferred, reason = DevPlanner._resolve_target_file(
            original,
            inherited_path=inherited_path,
            project_index=project_index,
            working_context=working_context,
            prefer_python=original.lower().endswith('.py') or 'arquivo' in normalized,
        )
        if path and ('valide o arquivo' in normalized or 'valide arquivo' in normalized or 'validar o arquivo' in normalized or 'validar arquivo' in normalized or 'rode validação' in normalized or 'rode validacao' in normalized):
            return {
                'type': 'validate_file',
                'path': path,
            }, {
                'planner_context_used': used_context,
                'context_fresh': DevPlanner._context_is_fresh(working_context),
                'inferred_from_context': inferred,
            }

        doc_step, doc_used_context, doc_inferred, doc_reason = DevPlanner._readme_doc_step(
            original,
            project_index=project_index,
            working_context=working_context,
        )
        if doc_step:
            return doc_step, {
                'planner_context_used': doc_used_context,
                'context_fresh': DevPlanner._context_is_fresh(working_context),
                'inferred_from_context': doc_inferred,
            }
        if 'readme' in normalized or 'document' in normalized:
            return None, {
                'reason': doc_reason or 'Não foi possível inferir um README para a documentação.',
                'missing': ['readme_file'],
                'planner_context_used': doc_used_context,
                'context_fresh': DevPlanner._context_is_fresh(working_context),
                'inferred_from_context': doc_inferred,
            }

        return None, {
            'reason': reason or 'O planner não conseguiu estruturar essa instrução com segurança.',
            'missing': [],
            'planner_context_used': used_context,
            'context_fresh': DevPlanner._context_is_fresh(working_context),
            'inferred_from_context': inferred,
        }

    @staticmethod
    def plan(command: str, project_index: dict | None = None, working_context: dict | None = None) -> dict:
        original = (command or '').strip()
        normalized = DevPlanner._normalize(original)
        context_fresh = DevPlanner._context_is_fresh(working_context)

        if not original:
            return DevPlanner._build_unknown_response(
                'Nenhum comando foi fornecido ao planner.',
                context_fresh=context_fresh,
            )

        if normalized in {'continue', 'próximo passo', 'proximo passo', 'retome isso', 'continue o plano anterior'}:
            return DevPlanner._plan_next_step(original, working_context)

        clauses = DevPlanner._split(original)
        if not clauses:
            return DevPlanner._build_unknown_response(
                'Não foi possível decompor o pedido em etapas planejáveis.',
                goal=original,
                context_fresh=context_fresh,
            )

        steps = []
        inherited_path = None
        last_route_path = None
        last_route_method = None
        planner_context_used = False
        inferred_from_context = False

        for clause in clauses:
            step, info = DevPlanner._plan_single(
                clause,
                inherited_path=inherited_path,
                project_index=project_index,
                working_context=working_context,
            )

            if step is None and ('readme' in clause.lower() or 'document' in clause.lower()):
                step, doc_used_context, doc_inferred, doc_reason = DevPlanner._readme_doc_step(
                    clause,
                    route_path=last_route_path,
                    method=last_route_method,
                    project_index=project_index,
                    working_context=working_context,
                )
                if step is not None:
                    info = {
                        'planner_context_used': doc_used_context,
                        'context_fresh': context_fresh,
                        'inferred_from_context': doc_inferred,
                    }
                else:
                    info = {
                        'reason': doc_reason or (info or {}).get('reason'),
                        'missing': ['readme_file'],
                        'planner_context_used': doc_used_context,
                        'context_fresh': context_fresh,
                        'inferred_from_context': doc_inferred,
                    }

            if step is None:
                return DevPlanner._build_partial_plan_response(
                    goal=original,
                    reason=(info or {}).get('reason') or 'Faltam dados para montar um plano seguro.',
                    missing=(info or {}).get('missing') or [],
                    steps=steps,
                    plan_steps=DevPlanner._build_plan_steps(steps, goal=original),
                    files=list(dict.fromkeys([item.get('path') for item in steps if item.get('path')])),
                    planner_context_used=planner_context_used or bool((info or {}).get('planner_context_used')),
                    context_fresh=context_fresh,
                    inferred_from_context=inferred_from_context or bool((info or {}).get('inferred_from_context')),
                )

            steps.append(step)
            inherited_path = step.get('path') or inherited_path
            planner_context_used = planner_context_used or bool((info or {}).get('planner_context_used'))
            inferred_from_context = inferred_from_context or bool((info or {}).get('inferred_from_context'))
            if step.get('type') == 'insert_route':
                last_route_path = step.get('route_path')
                last_route_method = step.get('method')

        if not steps:
            return DevPlanner._build_unknown_response(
                'O planner não conseguiu gerar etapas executáveis.',
                goal=original,
                planner_context_used=planner_context_used,
                context_fresh=context_fresh,
                inferred_from_context=inferred_from_context,
            )

        return DevPlanner._build_plan_response(
            goal=original,
            steps=steps,
            planner_context_used=planner_context_used,
            context_fresh=context_fresh,
            inferred_from_context=inferred_from_context,
        )
