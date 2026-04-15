"""
stoa_guardrail.py — Proteção contra loops de auto-modificação do agente STOA
"""
import re
from typing import Optional

SELF_MODIFICATION_PATTERNS = [
    r"executive_orchestrator",
    r"stoa_memory\.py",
    r"stoa_guardrail",
    r"OrchestratorV\d+Temp",
    r"adicionar.*StoaMemory.*arquivo",
    r"criar.*classe.*Orchestrator",
    r"modificar.*main\.py",
    r"editar.*requirements\.txt",
    r"alterar.*device_control",
]

CODE_WRITE_SELF_PATTERNS = [
    r"open\(['\"].*orchestrator.*['\"],\s*['\"]w",
    r"open\(['\"].*main\.py.*['\"],\s*['\"]w",
    r"write.*executive_orchestrator",
]

BLOCK_MESSAGE = (
    "[GUARDRAIL] Ação bloqueada: o agente detectou uma instrução de auto-modificação. "
    "O STOA não pode modificar seus próprios arquivos de sistema durante execução. "
    "Se você quiser fazer uma mudança no projeto, peça diretamente ao desenvolvedor."
)


class StoaGuardrail:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._compiled = [re.compile(p, re.IGNORECASE) for p in SELF_MODIFICATION_PATTERNS]
        self._compiled_code = [re.compile(p, re.IGNORECASE) for p in CODE_WRITE_SELF_PATTERNS]

    def check_response(self, text: str) -> tuple[bool, Optional[str]]:
        """
        Verifica se o texto de resposta do agente contém intenção de auto-modificação.
        Retorna (bloqueado: bool, motivo: str | None)
        """
        if not self.enabled:
            return False, None

        for pattern in self._compiled:
            if pattern.search(text):
                return True, BLOCK_MESSAGE

        for pattern in self._compiled_code:
            if pattern.search(text):
                return True, BLOCK_MESSAGE

        return False, None

    def check_action(self, action_type: str, action_params: dict) -> tuple[bool, Optional[str]]:
        """
        Verifica se uma ação de device control aponta para arquivos do próprio STOA.
        Retorna (bloqueado: bool, motivo: str | None)
        """
        if not self.enabled:
            return False, None

        if action_type == "run_shell_command":
            cmd = str(action_params.get("command", ""))
            for pattern in self._compiled:
                if pattern.search(cmd):
                    return True, BLOCK_MESSAGE

        return False, None
