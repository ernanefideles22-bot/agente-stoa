from __future__ import annotations

import re
from typing import Optional


DEVICE_HINTS = {
    "no windows",
    "no notebook",
    "no pc",
    "neste windows",
    "nesse windows",
    "neste computador",
    "nesse computador",
    "no dispositivo",
}


class DeviceCommandRouter:
    URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
    TARGET_SUFFIX_RE = re.compile(
        r"\s+(?:no|na|para o|para a|pro|pra|no dispositivo|na máquina|neste|nesse)\s+([a-z0-9][\w\-]{1,})\s*$",
        re.IGNORECASE,
    )

    @staticmethod
    def is_device_command(command: str) -> bool:
        text = (command or "").strip().lower()
        return any(
            marker in text
            for marker in [
                "abra ",
                "abrir ",
                "abre ",
                "tire um screenshot",
                "tirar screenshot",
                "captura de tela",
                "capture a tela",
                "executa ",
                "execute ",
                "rode ",
                "rodar comando",
                "run ",
                "dispositivo",
                "windows",
                "notepad",
                "explorer",
                "chrome",
                "edge",
                "cmd",
                "powershell",
            ]
        ) or bool(DeviceCommandRouter.URL_RE.search(text))

    @staticmethod
    def extract_device_hint(command: str) -> Optional[str]:
        text = (command or "").strip().lower()
        match = DeviceCommandRouter.TARGET_SUFFIX_RE.search(text)
        return match.group(1) if match else None

    @staticmethod
    def plan(command: str) -> dict:
        raw = (command or "").strip()
        text = raw.lower()
        target_device_hint = DeviceCommandRouter.extract_device_hint(raw)
        url_match = DeviceCommandRouter.URL_RE.search(raw)
        if "screenshot" in text or "captura de tela" in text or "capture a tela" in text:
            return {
                "intent": "device_take_screenshot",
                "action_type": "take_screenshot",
                "target": None,
                "parameters": {},
                "target_device_hint": target_device_hint,
                "user_summary": "Capturar screenshot do dispositivo.",
                "requires_confirmation": True,
            }
        if url_match:
            url = url_match.group(0)
            return {
                "intent": "device_open_url",
                "action_type": "open_url",
                "target": url,
                "parameters": {},
                "target_device_hint": target_device_hint,
                "user_summary": f"Abrir URL no dispositivo: {url}",
                "requires_confirmation": False,
            }
        if any(marker in text for marker in ["powershell", "cmd", "comando", "execute ", "executa ", "rode ", "run "]):
            shell_target = DeviceCommandRouter._extract_shell_target(raw)
            return {
                "intent": "device_run_shell_command",
                "action_type": "run_shell_command",
                "target": shell_target,
                "parameters": {"command": shell_target} if shell_target else {},
                "target_device_hint": target_device_hint,
                "user_summary": f"Executar comando no dispositivo: {shell_target or '-'}",
                "requires_confirmation": True,
            }
        app_target = DeviceCommandRouter._extract_app_target(raw)
        return {
            "intent": "device_open_app",
            "action_type": "open_app",
            "target": app_target,
            "parameters": {"app": app_target} if app_target else {},
            "target_device_hint": target_device_hint,
            "user_summary": f"Abrir aplicativo no dispositivo: {app_target or '-'}",
            "requires_confirmation": False,
        }

    @staticmethod
    def _extract_shell_target(command: str) -> Optional[str]:
        text = command.strip()
        patterns = [
            r"(?:execute|executa|rodar|rode|run)\s+(?:o\s+)?(?:comando\s+)?(.+?)\s*$",
            r"(?:powershell|cmd)\s+(.+?)\s*$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return DeviceCommandRouter._normalize_payload(match.group(1))
        return DeviceCommandRouter._normalize_payload(text.strip())

    @staticmethod
    def _extract_app_target(command: str) -> Optional[str]:
        text = command.strip()
        patterns = [
            r"(?:abra|abrir|abre)\s+(?:o\s+app\s+|o\s+aplicativo\s+|o\s+programa\s+)?(.+)",
            r"(?:inicie|iniciar)\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip(" .")
                candidate = re.sub(r"\s+(?:no|neste|nesse)\s+(?:windows|computador|notebook|pc|dispositivo).*$", "", candidate, flags=re.IGNORECASE)
                return DeviceCommandRouter._normalize_payload(candidate)
        return None

    @staticmethod
    def _strip_device_suffix(text: str) -> str:
        if not text:
            return text
        return re.sub(DeviceCommandRouter.TARGET_SUFFIX_RE, "", text).strip(" .")

    @staticmethod
    def _normalize_payload(text: str) -> str:
        cleaned = DeviceCommandRouter._strip_device_suffix(text)
        return re.sub(r"\s+", " ", cleaned).strip(" .")
