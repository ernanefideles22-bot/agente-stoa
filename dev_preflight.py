import ast
from pathlib import Path

from dev_executor import DevExecutor
from project_indexer import ProjectIndexer


class DevPreflightChecker:
    @staticmethod
    def route_exists(path: str, route_path: str) -> bool:
        try:
            indexed = ProjectIndexer.index_python_file(path)
        except Exception:
            return False
        for route in indexed.get('routes', []):
            if route.get('path') == route_path:
                return True
        return False

    @staticmethod
    def class_exists(path: str, class_name: str) -> bool:
        try:
            indexed = ProjectIndexer.index_python_file(path)
        except Exception:
            return False
        return class_name in indexed.get('classes', [])

    @staticmethod
    def function_exists(path: str, function_name: str) -> bool:
        try:
            indexed = ProjectIndexer.index_python_file(path)
        except Exception:
            return False
        return function_name in indexed.get('functions', [])

    @staticmethod
    def readme_contains(path: str, text: str) -> bool:
        try:
            file_path = DevExecutor.resolve_path(path)
        except Exception:
            return False
        if not file_path.exists() or not file_path.is_file():
            return False
        existing = file_path.read_text(encoding='utf-8').lower()
        candidate = (text or '').strip().lower()
        if not candidate:
            return False
        if candidate in existing:
            return True
        for line in [line.strip().lower() for line in candidate.splitlines() if line.strip()]:
            if len(line) >= 12 and line in existing:
                return True
        return False

    @staticmethod
    def _extract_python_symbols(content: str) -> dict:
        try:
            tree = ast.parse(content)
        except Exception:
            return {'classes': [], 'functions': []}

        classes = []
        functions = []
        for node in getattr(tree, 'body', []):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)
        return {'classes': classes, 'functions': functions}

    @staticmethod
    def _collect_step_conflicts(step: dict, step_index: int) -> tuple[list[dict], list[dict]]:
        errors = []
        warnings = []
        step_type = step.get('type')
        path = step.get('path')

        if step_type == 'insert_route':
            route_path = step.get('route_path')
            if path and route_path and DevPreflightChecker.route_exists(path, route_path):
                errors.append({
                    'step_index': step_index,
                    'type': 'route_exists',
                    'path': path,
                    'message': f'A rota {route_path} já existe em {path}',
                })

        if step_type in {'append_to_file', 'insert_after_class', 'insert_after_function'} and path and str(path).lower().endswith('.py'):
            symbols = DevPreflightChecker._extract_python_symbols(step.get('content', ''))
            for class_name in symbols.get('classes', []):
                if DevPreflightChecker.class_exists(path, class_name):
                    errors.append({
                        'step_index': step_index,
                        'type': 'class_exists',
                        'path': path,
                        'message': f'A classe {class_name} já existe em {path}',
                    })
            for function_name in symbols.get('functions', []):
                if DevPreflightChecker.function_exists(path, function_name):
                    errors.append({
                        'step_index': step_index,
                        'type': 'function_exists',
                        'path': path,
                        'message': f'A função {function_name} já existe em {path}',
                    })

        if step_type == 'replace_class' and path and step.get('symbol_name'):
            # replacement of existing class is intentional; no duplicate block here
            pass

        if step_type == 'replace_function' and path and step.get('symbol_name'):
            # replacement of existing function is intentional; no duplicate block here
            pass

        if step_type == 'append_to_file' and path and Path(path).suffix.lower() in {'.md', '.txt'}:
            if DevPreflightChecker.readme_contains(path, step.get('content', '')):
                warnings.append({
                    'step_index': step_index,
                    'type': 'readme_duplicate',
                    'path': path,
                    'message': f'{path} já contém documentação semelhante',
                })

        return errors, warnings

    @staticmethod
    def run_preflight(change_set: dict, project_index: dict | None = None) -> dict:
        errors = []
        warnings = []
        for index, step in enumerate(change_set.get('steps') or []):
            step_errors, step_warnings = DevPreflightChecker._collect_step_conflicts(step, index)
            errors.extend(step_errors)
            warnings.extend(step_warnings)
        return {
            'ok': not errors,
            'errors': errors,
            'warnings': warnings,
        }
