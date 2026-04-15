import ast
from pathlib import Path

from dev_executor import DevExecutor


class ProjectIndexer:
    @staticmethod
    def scan_files() -> list[str]:
        files = []
        for path in DevExecutor.BASE_DIR.rglob('*'):
            if any(part in DevExecutor.IGNORED_DIRS for part in path.parts):
                continue
            if path.is_file():
                files.append(path.relative_to(DevExecutor.BASE_DIR).as_posix())
        return sorted(files)

    @staticmethod
    def _is_http_route_decorator(decorator) -> bool:
        if not isinstance(decorator, ast.Call):
            return False
        func = decorator.func
        return isinstance(func, ast.Attribute) and func.attr in DevExecutor.HTTP_ROUTE_DECORATOR_NAMES

    @staticmethod
    def _extract_route_path(decorator) -> str | None:
        if not isinstance(decorator, ast.Call):
            return None
        if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
            return decorator.args[0].value
        return None

    @staticmethod
    def index_python_file(path: str) -> dict:
        file_path = DevExecutor.resolve_path(path)
        content = file_path.read_text(encoding='utf-8')
        tree = ast.parse(content)

        classes = []
        functions = []
        routes = []
        has_fastapi_app = False
        has_router = False

        for node in getattr(tree, 'body', []):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == 'FastAPI':
                    has_fastapi_app = True
                if isinstance(func, ast.Name) and func.id == 'APIRouter':
                    has_router = True

            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
                continue

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)
                for decorator in node.decorator_list:
                    if ProjectIndexer._is_http_route_decorator(decorator):
                        route_path = ProjectIndexer._extract_route_path(decorator)
                        routes.append({
                            'name': node.name,
                            'path': route_path,
                            'method': decorator.func.attr.lower() if isinstance(decorator.func, ast.Attribute) else None,
                        })

        return {
            'classes': classes,
            'functions': functions,
            'routes': routes,
            'has_fastapi_app': has_fastapi_app,
            'has_router': has_router,
        }

    @staticmethod
    def find_readme_files() -> list[str]:
        files = ProjectIndexer.scan_files()
        return [path for path in files if Path(path).name.lower().startswith('readme')]

    @staticmethod
    def find_fastapi_entrypoints() -> list[str]:
        entrypoints = []
        for path in ProjectIndexer.scan_files():
            if not path.lower().endswith('.py'):
                continue
            try:
                indexed = ProjectIndexer.index_python_file(path)
            except Exception:
                continue
            if indexed['has_fastapi_app'] or indexed['has_router'] or indexed['routes']:
                entrypoints.append(path)
        return entrypoints

    @staticmethod
    def build_index() -> dict:
        files = ProjectIndexer.scan_files()
        python_files = {}
        for path in files:
            if not path.lower().endswith('.py'):
                continue
            try:
                python_files[path] = ProjectIndexer.index_python_file(path)
            except Exception:
                continue
        return {
            'files': files,
            'readme_files': ProjectIndexer.find_readme_files(),
            'entrypoints': ProjectIndexer.find_fastapi_entrypoints(),
            'python_files': python_files,
        }
