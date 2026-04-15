import ast
import difflib
import json
import py_compile
import re
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path


class DevExecutor:
    BASE_DIR = Path(__file__).parent.resolve()
    BACKUP_DIR = BASE_DIR / ".stoa_backups"
    IGNORED_DIRS = {"__pycache__", ".git", "venv", ".venv", "node_modules", ".stoa_backups"}
    ROUTE_DECORATOR_PATTERN = re.compile(r"@app\.(get|post|put|delete|patch|options|head)\s*\(")
    HTTP_ROUTE_DECORATOR_NAMES = {"get", "post", "put", "delete", "patch", "options", "head"}

    @staticmethod
    def resolve_path(path: str) -> Path:
        raw_path = (path or "").strip().replace("\\", "/")
        if not raw_path:
            raise ValueError("Caminho não informado")

        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = DevExecutor.BASE_DIR / candidate

        resolved = candidate.resolve()

        try:
            resolved.relative_to(DevExecutor.BASE_DIR)
        except ValueError as exc:
            raise ValueError("Acesso bloqueado: caminho fora da raiz do projeto") from exc

        return resolved

    @staticmethod
    def list_files() -> list[str]:
        files = []
        for path in DevExecutor.BASE_DIR.rglob("*"):
            if any(part in DevExecutor.IGNORED_DIRS for part in path.parts):
                continue
            if path.is_file():
                files.append(path.relative_to(DevExecutor.BASE_DIR).as_posix())
        return sorted(files)

    @staticmethod
    def read_file(path: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"
        return file_path.read_text(encoding="utf-8")

    @staticmethod
    def create_backup(path: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if not file_path.exists() or not file_path.is_file():
            return "arquivo novo - backup não necessário"

        DevExecutor.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = file_path.relative_to(DevExecutor.BASE_DIR).as_posix().replace("/", "__")
        backup_path = DevExecutor.BACKUP_DIR / f"{timestamp}__{safe_name}.bak"
        backup_path.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")
        return backup_path.relative_to(DevExecutor.BASE_DIR).as_posix()

    @staticmethod
    def generate_diff(old_content: str, new_content: str, path: str) -> str:
        diff = difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
        diff_text = "\n".join(diff).strip()
        return diff_text or "Sem diferenças detectadas."

    @staticmethod
    def _build_change_result(path: Path, backup_path: str, old_content: str, new_content: str) -> str:
        relative_path = path.relative_to(DevExecutor.BASE_DIR).as_posix()
        diff_text = DevExecutor.generate_diff(old_content, new_content, relative_path)
        validation_text = ""
        import_text = ""

        if path.suffix.lower() == ".py":
            validation_text = DevExecutor.run_validation(relative_path)
            import_text = DevExecutor.run_import_check(relative_path)

        parts = [
            f"Arquivo alterado: {relative_path}",
            f"Backup: {backup_path}",
            "Diff:",
            diff_text,
        ]

        if validation_text:
            parts.extend(["", validation_text])
        if import_text:
            parts.extend(["", import_text])

        return "\n".join(parts)

    @staticmethod
    def _detect_newline(content: str) -> str:
        return "\r\n" if "\r\n" in content else "\n"

    @staticmethod
    def _indent_width(line: str) -> int:
        return len(line) - len(line.lstrip())

    @staticmethod
    def _prepare_indented_content(content: str, indent: str, newline: str) -> list[str]:
        normalized = textwrap.dedent(content).strip("\r\n")
        if not normalized:
            return []

        prepared_lines = []
        for line in normalized.splitlines():
            if line.strip():
                prepared_lines.append(f"{indent}{line}{newline}")
            else:
                prepared_lines.append(newline)
        return prepared_lines

    @staticmethod
    def _find_block_end(lines: list[str], header_index: int) -> int:
        base_indent = DevExecutor._indent_width(lines[header_index])
        for index in range(header_index + 1, len(lines)):
            stripped = lines[index].strip()
            if not stripped:
                continue
            if DevExecutor._indent_width(lines[index]) <= base_indent:
                return index
        return len(lines)

    @staticmethod
    def _find_function_block(lines: list[str], function_name: str):
        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith(f"def {function_name}(") or stripped.startswith(f"async def {function_name}("):
                indent = line[: len(line) - len(stripped)]
                start_index = index
                while start_index > 0:
                    previous = lines[start_index - 1]
                    previous_stripped = previous.lstrip()
                    previous_indent = previous[: len(previous) - len(previous_stripped)]
                    if previous_stripped.startswith("@") and previous_indent == indent:
                        start_index -= 1
                    else:
                        break
                end_index = DevExecutor._find_block_end(lines, index)
                return start_index, end_index, indent
        return None

    @staticmethod
    def _find_class_block(lines: list[str], class_name: str):
        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith(f"class {class_name}(") or stripped.startswith(f"class {class_name}:"):
                indent = line[: len(line) - len(stripped)]
                end_index = DevExecutor._find_block_end(lines, index)
                return index, end_index, indent
        return None

    @staticmethod
    def _get_python_source_info(path: str) -> tuple[str, list[str], ast.AST]:
        file_path = DevExecutor.resolve_path(path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(path)

        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        tree = ast.parse(content)
        return content, lines, tree

    @staticmethod
    def _find_function_node(tree: ast.AST, function_name: str):
        for node in getattr(tree, 'body', []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                return node
        return None

    @staticmethod
    def _find_class_node(tree: ast.AST, class_name: str):
        for node in getattr(tree, 'body', []):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return node
        return None

    @staticmethod
    def _get_node_line_range(lines: list[str], node) -> tuple[int, int]:
        start_line = getattr(node, 'lineno', None)
        end_line = getattr(node, 'end_lineno', None)
        if start_line is None or end_line is None:
            raise ValueError('Não foi possível determinar o intervalo do símbolo via AST')

        decorator_lines = getattr(node, 'decorator_list', None) or []
        if decorator_lines:
            start_line = min(getattr(decorator, 'lineno', start_line) for decorator in decorator_lines)

        start_index = max(start_line - 1, 0)
        end_index = min(end_line, len(lines))
        return start_index, end_index

    @staticmethod
    def _is_http_route_decorator(decorator) -> bool:
        if not isinstance(decorator, ast.Call):
            return False

        func = decorator.func
        return isinstance(func, ast.Attribute) and func.attr in DevExecutor.HTTP_ROUTE_DECORATOR_NAMES

    @staticmethod
    def _find_top_level_route_nodes(tree: ast.AST) -> list[ast.AST]:
        route_nodes = []
        for node in getattr(tree, 'body', []):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(DevExecutor._is_http_route_decorator(decorator) for decorator in node.decorator_list):
                route_nodes.append(node)
        return route_nodes


    @staticmethod
    def normalize_top_level_spacing(content: str) -> str:
        newline = DevExecutor._detect_newline(content)
        lines = content.splitlines(keepends=True)
        normalized_lines = []
        pending_blank_lines = 0
        current_section = None
        previous_top_level_kind = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                pending_blank_lines += 1
                continue

            indent = line[: len(line) - len(line.lstrip())]
            is_top_level = indent == ""
            is_decorator = is_top_level and stripped.startswith("@")
            is_header = is_top_level and (
                stripped.startswith("class ")
                or stripped.startswith("def ")
                or stripped.startswith("async def ")
            )

            if is_top_level and (is_decorator or is_header):
                if previous_top_level_kind == "decorator" and is_header:
                    desired_blank_lines = 0
                elif current_section == "top_block":
                    desired_blank_lines = 2
                else:
                    desired_blank_lines = min(pending_blank_lines, 2)

                normalized_lines.extend([newline] * desired_blank_lines)
                current_section = "top_block"
                previous_top_level_kind = "decorator" if is_decorator else "header"
            else:
                normalized_lines.extend([newline] * pending_blank_lines)
                if is_top_level:
                    current_section = "other"
                    previous_top_level_kind = None

            normalized_lines.append(line if line.endswith(("\n", "\r")) else f"{line}{newline}")
            pending_blank_lines = 0

        if pending_blank_lines:
            normalized_lines.extend([newline] * min(pending_blank_lines, 1))

        return "".join(normalized_lines)

    @staticmethod
    def _apply_content_change(file_path: Path, old_content: str, new_content: str, normalize_python: bool = False) -> str:
        if normalize_python and file_path.suffix.lower() == ".py":
            new_content = DevExecutor.normalize_top_level_spacing(new_content)
        backup_path = DevExecutor.create_backup(file_path.relative_to(DevExecutor.BASE_DIR).as_posix())
        file_path.write_text(new_content, encoding="utf-8")
        return DevExecutor._build_change_result(file_path, backup_path, old_content, new_content)

    @staticmethod
    def write_file(path: str, content: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        old_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        return DevExecutor._apply_content_change(file_path, old_content, content)

    @staticmethod
    def append_to_file(path: str, content: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        old_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        new_content = old_content + content
        return DevExecutor._apply_content_change(file_path, old_content, new_content)

    @staticmethod
    def replace_in_file(path: str, target: str, replacement: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"

        current_content = file_path.read_text(encoding="utf-8")
        if target not in current_content:
            return "❌ Trecho alvo não encontrado no arquivo"

        updated_content = current_content.replace(target, replacement)
        return DevExecutor._apply_content_change(file_path, current_content, updated_content)

    @staticmethod
    def replace_block(path: str, start_marker: str, end_marker: str, replacement: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"

        current_content = file_path.read_text(encoding="utf-8")
        lines = current_content.splitlines(keepends=True)

        start_line_index = None
        for index, line in enumerate(lines):
            if start_marker in line:
                start_line_index = index
                break

        if start_line_index is None:
            return "❌ Marcador inicial não encontrado"

        end_line_index = None
        for index in range(start_line_index + 1, len(lines)):
            if end_marker in lines[index]:
                end_line_index = index
                break

        if end_line_index is None:
            return "❌ Marcador final não encontrado após o marcador inicial"

        if end_line_index < start_line_index:
            return "❌ Marcador inicial encontrado depois do marcador final"

        newline = DevExecutor._detect_newline(current_content)
        replacement_lines = DevExecutor._prepare_indented_content(replacement, "", newline)
        updated_lines = lines[:start_line_index] + replacement_lines + lines[end_line_index + 1:]
        updated_content = "".join(updated_lines)
        return DevExecutor._apply_content_change(file_path, current_content, updated_content)

    @staticmethod
    def replace_function_in_file(path: str, function_name: str, replacement: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if file_path.suffix.lower() != ".py":
            return f"❌ Operação suportada apenas para arquivos Python: {path}"
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"

        current_content, lines, tree = DevExecutor._get_python_source_info(path)
        node = DevExecutor._find_function_node(tree, function_name)
        if not node:
            return f"❌ Função não encontrada: {function_name}"

        start_index, end_index = DevExecutor._get_node_line_range(lines, node)
        indent = lines[start_index][: len(lines[start_index]) - len(lines[start_index].lstrip())] if lines else ""
        newline = DevExecutor._detect_newline(current_content)
        replacement_lines = DevExecutor._prepare_indented_content(replacement, indent, newline)
        updated_lines = lines[:start_index] + replacement_lines + lines[end_index:]
        updated_content = "".join(updated_lines)
        return DevExecutor._apply_content_change(file_path, current_content, updated_content, normalize_python=True)

    @staticmethod
    def replace_class_in_file(path: str, class_name: str, replacement: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if file_path.suffix.lower() != ".py":
            return f"❌ Operação suportada apenas para arquivos Python: {path}"
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"

        current_content, lines, tree = DevExecutor._get_python_source_info(path)
        node = DevExecutor._find_class_node(tree, class_name)
        if not node:
            return f"❌ Classe não encontrada: {class_name}"

        start_index, end_index = DevExecutor._get_node_line_range(lines, node)
        indent = lines[start_index][: len(lines[start_index]) - len(lines[start_index].lstrip())] if lines else ""
        newline = DevExecutor._detect_newline(current_content)
        replacement_lines = DevExecutor._prepare_indented_content(replacement, indent, newline)
        updated_lines = lines[:start_index] + replacement_lines + lines[end_index:]
        updated_content = "".join(updated_lines)
        return DevExecutor._apply_content_change(file_path, current_content, updated_content, normalize_python=True)

    @staticmethod
    def insert_after_function(path: str, function_name: str, content: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if file_path.suffix.lower() != ".py":
            return f"❌ Operação suportada apenas para arquivos Python: {path}"
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"

        current_content, lines, tree = DevExecutor._get_python_source_info(path)
        node = DevExecutor._find_function_node(tree, function_name)
        if not node:
            return f"❌ Função não encontrada: {function_name}"

        _, end_index = DevExecutor._get_node_line_range(lines, node)
        newline = DevExecutor._detect_newline(current_content)
        content_lines = DevExecutor._prepare_indented_content(content, "", newline)
        updated_lines = lines[:end_index] + content_lines + lines[end_index:]
        updated_content = "".join(updated_lines)
        return DevExecutor._apply_content_change(file_path, current_content, updated_content, normalize_python=True)

    @staticmethod
    def insert_after_class(path: str, class_name: str, content: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if file_path.suffix.lower() != ".py":
            return f"❌ Operação suportada apenas para arquivos Python: {path}"
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"

        current_content, lines, tree = DevExecutor._get_python_source_info(path)
        node = DevExecutor._find_class_node(tree, class_name)
        if not node:
            return f"❌ Classe não encontrada: {class_name}"

        _, end_index = DevExecutor._get_node_line_range(lines, node)
        newline = DevExecutor._detect_newline(current_content)
        content_lines = DevExecutor._prepare_indented_content(content, "", newline)
        updated_lines = lines[:end_index] + content_lines + lines[end_index:]
        updated_content = "".join(updated_lines)
        return DevExecutor._apply_content_change(file_path, current_content, updated_content, normalize_python=True)

    @staticmethod
    def insert_route(path: str, content: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if file_path.suffix.lower() != ".py":
            return f"❌ Operação suportada apenas para arquivos Python: {path}"
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"

        current_content, lines, tree = DevExecutor._get_python_source_info(path)
        route_nodes = DevExecutor._find_top_level_route_nodes(tree)
        if not route_nodes:
            return "❌ Nenhum endpoint FastAPI/APIRouter encontrado para inserir a rota"

        last_route = max(route_nodes, key=lambda node: DevExecutor._get_node_line_range(lines, node)[1])
        _, end_index = DevExecutor._get_node_line_range(lines, last_route)
        newline = DevExecutor._detect_newline(current_content)
        content_lines = DevExecutor._prepare_indented_content(content, "", newline)
        updated_lines = lines[:end_index] + content_lines + lines[end_index:]
        updated_content = "".join(updated_lines)
        return DevExecutor._apply_content_change(file_path, current_content, updated_content, normalize_python=True)


    @staticmethod
    def _finalize_simulation(file_path: Path, old_content: str, new_content: str, normalize_python: bool = False) -> dict:
        if normalize_python and file_path.suffix.lower() == ".py":
            new_content = DevExecutor.normalize_top_level_spacing(new_content)
        relative_path = file_path.relative_to(DevExecutor.BASE_DIR).as_posix()
        return {
            "success": True,
            "path": relative_path,
            "old_content": old_content,
            "new_content": new_content,
            "estimated_diff": DevExecutor.generate_diff(old_content, new_content, relative_path),
        }

    @staticmethod
    def simulate_step(step: dict) -> dict:
        step_type = step.get("type")
        path = step.get("path")

        if step_type not in {
            "write_file",
            "append_to_file",
            "replace_in_file",
            "replace_block",
            "replace_function",
            "replace_class",
            "insert_after_function",
            "insert_after_class",
            "insert_route",
        }:
            return {
                "success": False,
                "error": f"Tipo de step não suportado para preview: {step_type}",
                "path": path,
            }

        try:
            file_path = DevExecutor.resolve_path(path)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "path": path,
            }

        old_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        try:
            if step_type == "write_file":
                return DevExecutor._finalize_simulation(file_path, old_content, step.get("content", ""))

            if step_type == "append_to_file":
                new_content = old_content + step.get("content", "")
                return DevExecutor._finalize_simulation(file_path, old_content, new_content)

            if step_type == "replace_in_file":
                if not file_path.exists() or not file_path.is_file():
                    return {"success": False, "error": f"Arquivo não encontrado: {path}", "path": path}
                target = step.get("target", "")
                replacement = step.get("replacement", "")
                if target not in old_content:
                    return {"success": False, "error": "Trecho alvo não encontrado no arquivo", "path": path}
                new_content = old_content.replace(target, replacement)
                return DevExecutor._finalize_simulation(file_path, old_content, new_content)

            if step_type == "replace_block":
                if not file_path.exists() or not file_path.is_file():
                    return {"success": False, "error": f"Arquivo não encontrado: {path}", "path": path}
                start_marker = step.get("start_marker", "")
                end_marker = step.get("end_marker", "")
                replacement = step.get("replacement", "")
                lines = old_content.splitlines(keepends=True)
                start_line_index = next((i for i, line in enumerate(lines) if start_marker in line), None)
                if start_line_index is None:
                    return {"success": False, "error": "Marcador inicial não encontrado", "path": path}
                end_line_index = next((i for i in range(start_line_index + 1, len(lines)) if end_marker in lines[i]), None)
                if end_line_index is None:
                    return {"success": False, "error": "Marcador final não encontrado após o marcador inicial", "path": path}
                if end_line_index < start_line_index:
                    return {"success": False, "error": "Marcador inicial encontrado depois do marcador final", "path": path}
                newline = DevExecutor._detect_newline(old_content)
                replacement_lines = DevExecutor._prepare_indented_content(replacement, "", newline)
                updated_lines = lines[:start_line_index] + replacement_lines + lines[end_line_index + 1:]
                return DevExecutor._finalize_simulation(file_path, old_content, "".join(updated_lines))

            if file_path.suffix.lower() != ".py":
                return {"success": False, "error": f"Operação suportada apenas para arquivos Python: {path}", "path": path}
            if not file_path.exists() or not file_path.is_file():
                return {"success": False, "error": f"Arquivo não encontrado: {path}", "path": path}

            current_content, lines, tree = DevExecutor._get_python_source_info(path)
            newline = DevExecutor._detect_newline(current_content)

            if step_type == "replace_function":
                node = DevExecutor._find_function_node(tree, step.get("symbol_name", ""))
                if not node:
                    return {"success": False, "error": f"Função não encontrada: {step.get('symbol_name', '')}", "path": path}
                start_index, end_index = DevExecutor._get_node_line_range(lines, node)
                indent = lines[start_index][: len(lines[start_index]) - len(lines[start_index].lstrip())] if lines else ""
                replacement_lines = DevExecutor._prepare_indented_content(step.get("content", ""), indent, newline)
                updated_lines = lines[:start_index] + replacement_lines + lines[end_index:]
                return DevExecutor._finalize_simulation(file_path, current_content, "".join(updated_lines), normalize_python=True)

            if step_type == "replace_class":
                node = DevExecutor._find_class_node(tree, step.get("symbol_name", ""))
                if not node:
                    return {"success": False, "error": f"Classe não encontrada: {step.get('symbol_name', '')}", "path": path}
                start_index, end_index = DevExecutor._get_node_line_range(lines, node)
                indent = lines[start_index][: len(lines[start_index]) - len(lines[start_index].lstrip())] if lines else ""
                replacement_lines = DevExecutor._prepare_indented_content(step.get("content", ""), indent, newline)
                updated_lines = lines[:start_index] + replacement_lines + lines[end_index:]
                return DevExecutor._finalize_simulation(file_path, current_content, "".join(updated_lines), normalize_python=True)

            if step_type == "insert_after_function":
                node = DevExecutor._find_function_node(tree, step.get("symbol_name", ""))
                if not node:
                    return {"success": False, "error": f"Função não encontrada: {step.get('symbol_name', '')}", "path": path}
                _, end_index = DevExecutor._get_node_line_range(lines, node)
                content_lines = DevExecutor._prepare_indented_content(step.get("content", ""), "", newline)
                updated_lines = lines[:end_index] + content_lines + lines[end_index:]
                return DevExecutor._finalize_simulation(file_path, current_content, "".join(updated_lines), normalize_python=True)

            if step_type == "insert_after_class":
                node = DevExecutor._find_class_node(tree, step.get("symbol_name", ""))
                if not node:
                    return {"success": False, "error": f"Classe não encontrada: {step.get('symbol_name', '')}", "path": path}
                _, end_index = DevExecutor._get_node_line_range(lines, node)
                content_lines = DevExecutor._prepare_indented_content(step.get("content", ""), "", newline)
                updated_lines = lines[:end_index] + content_lines + lines[end_index:]
                return DevExecutor._finalize_simulation(file_path, current_content, "".join(updated_lines), normalize_python=True)

            if step_type == "insert_route":
                route_nodes = DevExecutor._find_top_level_route_nodes(tree)
                if not route_nodes:
                    return {"success": False, "error": "Nenhum endpoint FastAPI/APIRouter encontrado para inserir a rota", "path": path}
                last_route = max(route_nodes, key=lambda node: DevExecutor._get_node_line_range(lines, node)[1])
                _, end_index = DevExecutor._get_node_line_range(lines, last_route)
                content_lines = DevExecutor._prepare_indented_content(step.get("content", ""), "", newline)
                updated_lines = lines[:end_index] + content_lines + lines[end_index:]
                return DevExecutor._finalize_simulation(file_path, current_content, "".join(updated_lines), normalize_python=True)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "path": path,
            }

    @staticmethod
    def _format_import_check_result(result: dict) -> str:
        status = result.get("status", "error")
        message = result.get("message", "Import check sem mensagem")
        details = (result.get("details") or "").strip()

        if status == "success":
            return f"✅ {message}"
        if status == "warning":
            return f"⚠️ {message}" + (f"\nDetalhes: {details}" if details else "")
        return f"❌ {message}" + (f"\nDetalhes: {details}" if details else "")

    @staticmethod
    def run_import_check_info(path: str) -> dict:
        file_path = DevExecutor.resolve_path(path)
        relative_path = file_path.relative_to(DevExecutor.BASE_DIR).as_posix() if file_path.exists() else path

        if not file_path.exists() or not file_path.is_file():
            return {
                "status": "error",
                "message": f"Arquivo não encontrado: {path}",
                "details": "",
            }

        if file_path.suffix.lower() != ".py":
            return {
                "status": "error",
                "message": f"Import check não suportado para: {file_path.name}",
                "details": "",
            }

        module_name = file_path.stem
        probe = "\n".join([
            "import importlib, json, traceback",
            f"module_name = {module_name!r}",
            "try:",
            "    importlib.import_module(module_name)",
            "    print(json.dumps({'ok': True}))",
            "except Exception as exc:",
            "    print(json.dumps({",
            "        'ok': False,",
            "        'error_type': exc.__class__.__name__,",
            "        'error_message': str(exc),",
            "        'traceback': traceback.format_exc(),",
            "    }))",
        ])
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(file_path.parent),
            capture_output=True,
            text=True,
            timeout=15,
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        payload = None
        try:
            if stdout:
                payload = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError:
            payload = None

        if payload and payload.get("ok") is True and result.returncode == 0:
            return {
                "status": "success",
                "message": f"Import check concluído com sucesso: {relative_path}",
                "details": "",
            }

        error_type = payload.get("error_type") if payload else None
        error_message = payload.get("error_message") if payload else None
        traceback_text = (payload.get("traceback") if payload else None) or stderr or stdout or "Erro desconhecido"

        if error_type == "ModuleNotFoundError":
            missing_match = re.search(r'No module named [\'"]([^\'"]+)[\'"]', error_message or traceback_text)
            missing_module = missing_match.group(1) if missing_match else None
            local_missing = False
            if missing_module:
                module_parts = missing_module.split('.')
                module_path = DevExecutor.BASE_DIR.joinpath(*module_parts)
                local_missing = module_path.with_suffix('.py').exists() or module_path.is_dir()

            if missing_module and missing_module != module_name and not local_missing:
                return {
                    "status": "warning",
                    "message": f"Import check com dependência ausente no ambiente: {relative_path}",
                    "details": traceback_text.strip(),
                }

        if error_type in {"SyntaxError", "IndentationError", "NameError", "ImportError", "ModuleNotFoundError"}:
            return {
                "status": "error",
                "message": f"Erro estrutural no import check: {relative_path}",
                "details": traceback_text.strip(),
            }

        return {
            "status": "error",
            "message": f"Erro no import check: {relative_path}",
            "details": traceback_text.strip(),
        }

    @staticmethod
    def run_validation(path: str) -> str:
        file_path = DevExecutor.resolve_path(path)
        if not file_path.exists() or not file_path.is_file():
            return f"❌ Arquivo não encontrado: {path}"

        if file_path.suffix.lower() != ".py":
            return f"❌ Validação não suportada para: {file_path.name}"

        try:
            py_compile.compile(str(file_path), doraise=True)
            return f"✅ Validação concluída com sucesso: {file_path.relative_to(DevExecutor.BASE_DIR).as_posix()}"
        except py_compile.PyCompileError as exc:
            return f"❌ Erro de validação: {exc.msg}"

    @staticmethod
    def run_import_check(path: str) -> str:
        return DevExecutor._format_import_check_result(DevExecutor.run_import_check_info(path))
