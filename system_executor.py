import subprocess

class SystemExecutor:

    ALLOWED_COMMANDS = [
        "notepad",
        "calc",
        "dir",
        "echo",
        "start",
        "code"
    ]

    BLOCKED_COMMANDS = [
        "del",
        "rm",
        "shutdown",
        "format"
    ]

    @staticmethod
    def run(command: str) -> str:
        try:
            parts = command.lower().split()
            if not parts:
                return "❌ Comando vazio"

            base_cmd = parts[0]

            if base_cmd in SystemExecutor.BLOCKED_COMMANDS:
                return f"❌ Comando bloqueado: {base_cmd}"

            if base_cmd not in SystemExecutor.ALLOWED_COMMANDS:
                return f"❌ Comando não permitido: {base_cmd}"

            if base_cmd == "start":
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                return result.stdout or "Aplicação iniciada"

            result = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return f"Erro: {result.stderr}"

            return result.stdout or "Comando executado com sucesso"

        except subprocess.TimeoutExpired:
            return "❌ Timeout na execução"
        except Exception as e:
            return f"❌ Erro: {str(e)}"
