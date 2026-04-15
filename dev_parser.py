import re
from typing import Optional


class DevCommandParser:
    FILE_PATTERN = re.compile(r'([\w./\\-]+\.(?:py|txt|md|json|yaml|yml))', re.IGNORECASE)

    @staticmethod
    def _base_result() -> dict:
        return {
            "action": "unknown",
            "path": None,
            "target": None,
            "replacement": None,
            "start_marker": None,
            "end_marker": None,
            "content": None,
            "symbol_type": None,
            "symbol_name": None,
            "method": None,
            "route_path": None,
            "steps": None,
        }

    @staticmethod
    def _extract_path(command: str) -> Optional[str]:
        match = DevCommandParser.FILE_PATTERN.search(command or "")
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _split_change_set_command(command: str) -> list[str]:
        original = (command or '').strip()
        if not original:
            return []

        split_patterns = [
            r'\s+e\s+depois\s+',
            r'\s+e\s+ent[aã]o\s+',
            r'\s+e\s+(?=atualize\b|valide\b|adicione\b|crie\b|insira\b|substitua\b|substituir\b)',
        ]

        for pattern in split_patterns:
            parts = re.split(pattern, original, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2 and all(part.strip() for part in parts):
                return [parts[0].strip(), parts[1].strip()]
        return [original]

    @staticmethod
    def _build_step(parsed: dict) -> dict:
        action = parsed.get('action')
        path = parsed.get('path')

        if action == 'write_file':
            return {'type': 'write_file', 'path': path, 'content': parsed.get('content', '')}
        if action == 'append_to_file':
            return {'type': 'append_to_file', 'path': path, 'content': parsed.get('content', '')}
        if action == 'replace_in_file':
            return {'type': 'replace_in_file', 'path': path, 'target': parsed.get('target'), 'replacement': parsed.get('replacement')}
        if action == 'replace_block':
            return {'type': 'replace_block', 'path': path, 'start_marker': parsed.get('start_marker'), 'end_marker': parsed.get('end_marker'), 'replacement': parsed.get('replacement')}
        if action == 'replace_function':
            return {'type': 'replace_function', 'path': path, 'symbol_name': parsed.get('symbol_name'), 'content': parsed.get('content')}
        if action == 'replace_class':
            return {'type': 'replace_class', 'path': path, 'symbol_name': parsed.get('symbol_name'), 'content': parsed.get('content')}
        if action == 'insert_after_function':
            return {'type': 'insert_after_function', 'path': path, 'symbol_name': parsed.get('symbol_name'), 'content': parsed.get('content')}
        if action == 'insert_after_class':
            return {'type': 'insert_after_class', 'path': path, 'symbol_name': parsed.get('symbol_name'), 'content': parsed.get('content')}
        if action == 'insert_route':
            return {'type': 'insert_route', 'path': path, 'content': parsed.get('content'), 'method': parsed.get('method'), 'route_path': parsed.get('route_path')}
        if action == 'validate_file':
            return {'type': 'validate_file', 'path': path}
        if action == 'import_check':
            return {'type': 'import_check', 'path': path}
        return {'type': 'unknown', 'path': path}

    @staticmethod
    def _build_readme_update_content(previous_step: Optional[dict], clause: str) -> str:
        if previous_step and previous_step.get('action') == 'insert_route':
            route_path = previous_step.get('route_path') or 'rota nova'
            method = (previous_step.get('method') or 'get').upper()
            return f"\n\n## Documentação\n- Endpoint adicionado: `{method} {route_path}`\n"
        return f"\n\n## Documentação\n- Atualização solicitada: {clause.strip()}\n"

    @staticmethod
    def _parse_single(command: str, inherited_path: Optional[str] = None, previous_step: Optional[dict] = None) -> dict:
        result = DevCommandParser._base_result()
        original = (command or '').strip()
        normalized = re.sub(r'\s+', ' ', original.lower()).strip()
        path = DevCommandParser._extract_path(original) or inherited_path
        result['path'] = path

        if 'listar arquivos' in normalized:
            result['action'] = 'list_files'
            return result

        if path and ('validar import' in normalized or 'import check' in normalized):
            result['action'] = 'import_check'
            return result

        if path and ('validar arquivo' in normalized or 'valide o arquivo' in normalized or 'valide arquivo' in normalized or normalized == 'valide o arquivo'):
            result['action'] = 'validate_file'
            return result

        if path and ('ler arquivo' in normalized or 'ler o arquivo' in normalized or 'mostrar arquivo' in normalized):
            result['action'] = 'read_file'
            return result

        if 'abrir vscode' in normalized or 'abre vscode' in normalized or 'abrir vs code' in normalized:
            result['action'] = 'open_vscode'
            return result

        route_match = re.search(
            r'adicione\s+uma\s+rota\s+(get|post|put|delete|patch|options|head)\s+([^\s]+).*?:\s*(.+)$',
            original,
            re.IGNORECASE | re.DOTALL,
        )
        if path and route_match:
            result['action'] = 'insert_route'
            result['method'] = route_match.group(1).lower()
            result['route_path'] = route_match.group(2).strip()
            result['content'] = route_match.group(3).strip()
            return result

        replace_function_match = re.search(
            r'substitu(?:a|ir)?\s+a?\s*funç(?:ã|a)o\s+([A-Za-z_][A-Za-z0-9_]*)\b.*?por:\s*(.+)$',
            original,
            re.IGNORECASE | re.DOTALL,
        )
        if path and replace_function_match:
            result['action'] = 'replace_function'
            result['symbol_type'] = 'function'
            result['symbol_name'] = replace_function_match.group(1).strip()
            result['content'] = replace_function_match.group(2).strip()
            return result

        replace_class_match = re.search(
            r'substitu(?:a|ir)?\s+a?\s*classe\s+([A-Za-z_][A-Za-z0-9_]*)\b.*?por:\s*(.+)$',
            original,
            re.IGNORECASE | re.DOTALL,
        )
        if path and replace_class_match:
            result['action'] = 'replace_class'
            result['symbol_type'] = 'class'
            result['symbol_name'] = replace_class_match.group(1).strip()
            result['content'] = replace_class_match.group(2).strip()
            return result

        insert_after_function_match = re.search(
            r'insira\s+este\s+código\s+após\s+a?\s*funç(?:ã|a)o\s+([A-Za-z_][A-Za-z0-9_]*)\b.*?:\s*(.+)$',
            original,
            re.IGNORECASE | re.DOTALL,
        )
        if path and insert_after_function_match:
            result['action'] = 'insert_after_function'
            result['symbol_type'] = 'function'
            result['symbol_name'] = insert_after_function_match.group(1).strip()
            result['content'] = insert_after_function_match.group(2).strip()
            return result

        insert_after_class_match = re.search(
            r'insira\s+este\s+código\s+após\s+a?\s*classe\s+([A-Za-z_][A-Za-z0-9_]*)\b.*?:\s*(.+)$',
            original,
            re.IGNORECASE | re.DOTALL,
        )
        if path and insert_after_class_match:
            result['action'] = 'insert_after_class'
            result['symbol_type'] = 'class'
            result['symbol_name'] = insert_after_class_match.group(1).strip()
            result['content'] = insert_after_class_match.group(2).strip()
            return result

        create_class_match = re.search(
            r'crie\s+uma\s+classe\s+([A-Za-z_][A-Za-z0-9_]*)\b',
            original,
            re.IGNORECASE,
        )
        if path and create_class_match:
            class_name = create_class_match.group(1).strip()
            result['action'] = 'append_to_file'
            result['symbol_type'] = 'class'
            result['symbol_name'] = class_name
            result['content'] = f"\n\nclass {class_name}:\n    pass\n"
            return result

        update_docs_match = re.search(
            r'atualiz(?:e|ar)?\s+o\s+([\w./\\-]+\.(?:md|txt))\s+com\s+a\s+documentaç(?:ã|a)o',
            original,
            re.IGNORECASE,
        )
        if update_docs_match:
            result['action'] = 'append_to_file'
            result['path'] = update_docs_match.group(1).strip()
            result['content'] = DevCommandParser._build_readme_update_content(previous_step, original)
            return result

        if path and ('adicionar uma linha no final do arquivo' in normalized or 'adicionar no final do arquivo' in normalized):
            split_match = re.search(r':\s*(.+)$', original, re.DOTALL) or re.search(r'->\s*(.+)$', original, re.DOTALL)
            if split_match:
                result['action'] = 'append_to_file'
                result['content'] = split_match.group(1).strip()
            return result

        if path and ('substituir no arquivo' in normalized or 'substituir em arquivo' in normalized):
            block_match = re.search(
                r'bloco entre\s+(.+?)\s+e\s+(.+?)\s+por\s+(.+)$',
                original,
                re.IGNORECASE | re.DOTALL,
            )
            if block_match:
                result['action'] = 'replace_block'
                result['start_marker'] = block_match.group(1).strip()
                result['end_marker'] = block_match.group(2).strip()
                result['replacement'] = block_match.group(3).strip()
                return result

            replace_match = re.search(
                r'texto\s+(.+?)\s+por\s+(.+)$',
                original,
                re.IGNORECASE | re.DOTALL,
            )
            if replace_match:
                result['action'] = 'replace_in_file'
                result['target'] = replace_match.group(1).strip()
                result['replacement'] = replace_match.group(2).strip()
                return result

        return result

    @staticmethod
    def parse(command: str) -> dict:
        original = (command or '').strip()
        clauses = DevCommandParser._split_change_set_command(original)
        if len(clauses) > 1:
            parsed_steps = []
            inherited_path = None
            previous_step = None
            for clause in clauses:
                parsed = DevCommandParser._parse_single(clause, inherited_path=inherited_path, previous_step=previous_step)
                if parsed.get('action') == 'unknown':
                    parsed_steps = []
                    break
                parsed_steps.append(parsed)
                inherited_path = parsed.get('path') or inherited_path
                previous_step = parsed

            if len(parsed_steps) > 1:
                result = DevCommandParser._base_result()
                result['action'] = 'apply_change_set'
                result['path'] = inherited_path
                result['steps'] = [DevCommandParser._build_step(step) for step in parsed_steps]
                return result

        return DevCommandParser._parse_single(original)
