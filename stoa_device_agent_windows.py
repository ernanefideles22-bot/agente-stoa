from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path


def _load_env() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k:
            os.environ.setdefault(k, v)

_load_env()


def now_iso() -> str:
    return datetime.now().isoformat()


def default_capabilities() -> list[dict]:
    return [
        {
            "capability_id": "windows.open_app",
            "action_type": "open_app",
            "title": "Abrir aplicativo",
            "description": "Abre um aplicativo local do Windows por caminho ou nome.",
            "platform": "windows",
            "risk": "safe",
            "requires_confirmation": False,
            "parameters_schema": {"target": "Caminho do executável ou nome do app"},
        },
        {
            "capability_id": "windows.open_url",
            "action_type": "open_url",
            "title": "Abrir URL",
            "description": "Abre uma URL no navegador padrão.",
            "platform": "windows",
            "risk": "safe",
            "requires_confirmation": False,
            "parameters_schema": {"target": "URL absoluta"},
        },
        {
            "capability_id": "windows.run_shell_command",
            "action_type": "run_shell_command",
            "title": "Executar comando shell",
            "description": "Executa um comando PowerShell/cmd localmente.",
            "platform": "windows",
            "risk": "sensitive",
            "requires_confirmation": True,
            "parameters_schema": {"target": "Comando shell", "timeout_seconds": "Opcional"},
        },
        {
            "capability_id": "windows.take_screenshot",
            "action_type": "take_screenshot",
            "title": "Capturar screenshot",
            "description": "Captura a tela atual em PNG.",
            "platform": "windows",
            "risk": "sensitive",
            "requires_confirmation": True,
            "parameters_schema": {"save_path": "Opcional"},
        },
        {
            "capability_id": "windows.close_app",
            "action_type": "close_app",
            "title": "Fechar aplicativo",
            "description": "Encerra um processo pelo nome do executável.",
            "platform": "windows",
            "risk": "sensitive",
            "requires_confirmation": True,
            "parameters_schema": {"target": "Nome do executável (ex: notepad.exe)"},
        },
        {
            "capability_id": "windows.media_control",
            "action_type": "media_control",
            "title": "Controlar mídia",
            "description": "Pausa, retoma, próxima faixa ou faixa anterior.",
            "platform": "windows",
            "risk": "safe",
            "requires_confirmation": False,
            "parameters_schema": {"action": "play_pause | next | prev | volume_up | volume_down | mute"},
        },
        {
            "capability_id": "windows.vscode_open",
            "action_type": "vscode_open",
            "title": "Abrir no VSCode",
            "description": "Abre um arquivo ou pasta no VSCode.",
            "platform": "windows",
            "risk": "safe",
            "requires_confirmation": False,
            "parameters_schema": {"target": "Caminho do arquivo ou pasta"},
        },
        {
            "capability_id": "windows.send_whatsapp",
            "action_type": "send_whatsapp",
            "title": "Enviar mensagem WhatsApp",
            "description": "Abre o WhatsApp Web com número e mensagem pré-preenchidos.",
            "platform": "windows",
            "risk": "safe",
            "requires_confirmation": False,
            "parameters_schema": {"phone": "Número com DDI (ex: 5565999999999)", "message": "Texto da mensagem"},
        },
    ]


class WindowsDeviceAgent:
    def __init__(self, core_url: str, device_id: str, device_name: str, poll_interval: int = 4) -> None:
        self.core_url = core_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.poll_interval = poll_interval
        self.hostname = socket.gethostname()
        self.current_action_id = None
        self.last_result = None

    def request_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        headers = {"Content-Type": "application/json"}
        _token = os.environ.get("STOA_TOKEN", "")
        if _token:
            headers["Authorization"] = f"Bearer {_token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=f"{self.core_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}

    def register(self) -> dict:
        payload = {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "platform": "windows",
            "hostname": self.hostname,
            "os_version": os.name,
            "agent_version": "1.0.0",
            "aliases": [self.device_id, self.device_name, self.hostname, "windows", "pc", "notebook"],
            "capabilities": default_capabilities(),
            "metadata": {"agent_runtime": "python", "cwd": str(Path.cwd())},
        }
        return self.request_json("POST", "/api/devices/register", payload)

    def heartbeat(self, *, status: str = "online") -> dict:
        payload = {
            "device_id": self.device_id,
            "status": status,
            "current_action_id": self.current_action_id,
            "last_result": self.last_result,
            "metadata": {"hostname": self.hostname},
        }
        return self.request_json("POST", f"/api/devices/{self.device_id}/heartbeat", payload)

    def poll_forever(self) -> None:
        print(f"[STOA Agent] Registrando {self.device_name} em {self.core_url}")
        self.register()
        while True:
            try:
                self.heartbeat(status="busy" if self.current_action_id else "online")
                response = self.request_json("GET", f"/api/devices/{self.device_id}/actions/next")
                action = response.get("action")
                if action:
                    self.current_action_id = action.get("action_id")
                    self.heartbeat(status="busy")
                    result = self.execute_action(action)
                    self.last_result = result
                    self.request_json(
                        "POST",
                        f"/api/devices/{self.device_id}/actions/{action['action_id']}/result",
                        result,
                    )
                    self.current_action_id = None
                    self.heartbeat(status="online")
                time.sleep(self.poll_interval)
            except urllib.error.HTTPError as error:
                print(f"[STOA Agent] HTTP error: {error.code} {error.reason}")
                time.sleep(self.poll_interval)
            except Exception as error:
                print(f"[STOA Agent] Loop error: {error}")
                self.current_action_id = None
                time.sleep(self.poll_interval)

    def execute_action(self, action: dict) -> dict:
        action_type = action.get("action_type")
        target = action.get("target")
        parameters = action.get("parameters") or {}
        started_at = now_iso()
        try:
            if action_type == "open_app":
                payload = self._open_app(target, parameters)
            elif action_type == "open_url":
                payload = self._open_url(target)
            elif action_type == "run_shell_command":
                payload = self._run_shell_command(target or parameters.get("command"), parameters)
            elif action_type == "take_screenshot":
                payload = self._take_screenshot(parameters)
            elif action_type == "close_app":
                payload = self._close_app(target, parameters)
            elif action_type == "media_control":
                payload = self._media_control(parameters)
            elif action_type == "vscode_open":
                payload = self._vscode_open(target, parameters)
            elif action_type == "send_whatsapp":
                payload = self._send_whatsapp(parameters)
            else:
                raise ValueError(f"Ação não suportada pelo agent Windows: {action_type}")
            success = payload.pop("success", True)
            status = payload.pop("status", "succeeded" if success else "failed")
            return {
                "action_id": action["action_id"],
                "device_id": self.device_id,
                "success": success,
                "status": status,
                "output": payload.get("output"),
                "error": payload.get("error"),
                "artifacts": payload.get("artifacts", []),
                "logs": payload.get("logs", []),
                "started_at": started_at,
                "finished_at": now_iso(),
                "metadata": payload.get("metadata", {}),
            }
        except Exception as error:
            return {
                "action_id": action["action_id"],
                "device_id": self.device_id,
                "success": False,
                "status": "failed",
                "error": str(error),
                "started_at": started_at,
                "finished_at": now_iso(),
                "metadata": {"action_type": action_type},
            }

    def _open_app(self, target: str | None, parameters: dict) -> dict:
        app = target or parameters.get("app")
        if not app:
            raise ValueError("open_app exige target/app.")
        subprocess.Popen(app, shell=True)
        return {"output": f"Aplicativo aberto: {app}"}

    def _open_url(self, target: str | None) -> dict:
        if not target:
            raise ValueError("open_url exige target.")
        webbrowser.open(target)
        return {"output": f"URL aberta: {target}"}

    def _run_shell_command(self, command: str | None, parameters: dict) -> dict:
        if not command:
            raise ValueError("run_shell_command exige um comando.")
        timeout_seconds = int(parameters.get("timeout_seconds", 20))
        shell_executable = os.environ.get("COMSPEC", "cmd.exe")
        try:
            completed = subprocess.run(
                [shell_executable, "/c", command],
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            stdout = (error.stdout or "").strip()
            stderr = (error.stderr or "").strip()
            return {
                "success": False,
                "status": "failed",
                "output": stdout or None,
                "error": stderr or f"Comando excedeu o timeout de {timeout_seconds}s.",
                "logs": [entry for entry in [f"returncode=timeout", stdout, stderr] if entry],
                "metadata": {
                    "command": command,
                    "timeout_seconds": timeout_seconds,
                    "shell": shell_executable,
                    "returncode": None,
                    "timed_out": True,
                },
            }
        except Exception as error:
            return {
                "success": False,
                "status": "failed",
                "error": str(error),
                "logs": [f"unexpected_error={type(error).__name__}"],
                "metadata": {
                    "command": command,
                    "timeout_seconds": timeout_seconds,
                    "shell": shell_executable,
                },
            }

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        success = completed.returncode == 0
        return {
            "success": success,
            "status": "succeeded" if success else "failed",
            "output": stdout or (f"Comando executado sem stdout: {command}" if success else None),
            "error": None if success else (stderr or stdout or f"Comando falhou com exit code {completed.returncode}."),
            "logs": [entry for entry in [f"returncode={completed.returncode}", stdout, stderr] if entry],
            "metadata": {
                "command": command,
                "timeout_seconds": timeout_seconds,
                "shell": shell_executable,
                "returncode": completed.returncode,
            },
        }

    def _take_screenshot(self, parameters: dict) -> dict:
        save_path = parameters.get("save_path")
        if not save_path:
            save_path = str(Path(tempfile.gettempdir()) / f"stoa-screenshot-{int(time.time())}.png")
        safe_path = save_path.replace("'", "''")
        powershell_script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "Add-Type -AssemblyName System.Drawing;"
            "$bounds=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
            "$bmp=New-Object System.Drawing.Bitmap($bounds.Width,$bounds.Height);"
            "$graphics=[System.Drawing.Graphics]::FromImage($bmp);"
            "$graphics.CopyFromScreen($bounds.Left,$bounds.Top,0,0,$bmp.Size);"
            f"$bmp.Save('{safe_path}',[System.Drawing.Imaging.ImageFormat]::Png);"
            "$graphics.Dispose();"
            "$bmp.Dispose();"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", powershell_script],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Falha ao capturar screenshot.")
        return {
            "output": f"Screenshot salvo em {save_path}",
            "artifacts": [save_path],
        }

    def _close_app(self, target: str | None, parameters: dict) -> dict:
        app = target or parameters.get("app") or parameters.get("target")
        if not app:
            raise ValueError("close_app exige target com nome do executável.")
        if not app.lower().endswith(".exe"):
            app = app + ".exe"
        result = subprocess.run(["taskkill", "/IM", app, "/F"], capture_output=True, text=True)
        if result.returncode == 0:
            return {"output": f"Processo {app} encerrado."}
        raise RuntimeError(result.stderr.strip() or f"Falha ao encerrar {app}.")

    def _media_control(self, parameters: dict) -> dict:
        action = (parameters.get("action") or "play_pause").lower()
        key_map = {
            "play_pause": 0xB3,
            "next":       0xB0,
            "prev":       0xB1,
            "volume_up":  0xAF,
            "volume_down":0xAE,
            "mute":       0xAD,
        }
        vk = key_map.get(action)
        if vk is None:
            raise ValueError(f"Ação de mídia desconhecida: {action}. Use: {list(key_map)}")
        script = (
            "Add-Type -TypeDefinition '"
            "using System; using System.Runtime.InteropServices;"
            "public class KbSend {"
            "  [DllImport(\"user32.dll\")] public static extern void keybd_event(byte bVk, byte bScan, uint flags, int extra);"
            "}' -Language CSharp;"
            f"[KbSend]::keybd_event({vk}, 0, 0, 0);"
            f"[KbSend]::keybd_event({vk}, 0, 2, 0);"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
        return {"output": f"Tecla de mídia enviada: {action}"}

    def _vscode_open(self, target: str | None, parameters: dict) -> dict:
        path = target or parameters.get("path") or parameters.get("target")
        if not path:
            raise ValueError("vscode_open exige target com caminho.")
        subprocess.Popen(["code", path], shell=True)
        return {"output": f"VSCode abrindo: {path}"}

    def _send_whatsapp(self, parameters: dict) -> dict:
        phone = parameters.get("phone", "").strip().lstrip("+").replace(" ", "")
        message = parameters.get("message", "").strip()
        if not phone:
            raise ValueError("send_whatsapp exige phone.")
        url = f"https://wa.me/{phone}"
        if message:
            url += "?" + urllib.parse.urlencode({"text": message})
        webbrowser.open(url)
        return {"output": f"WhatsApp Web aberto para {phone}"}


def main() -> None:
    parser = argparse.ArgumentParser(description="STOA Agent Windows")
    parser.add_argument("--core-url", default="http://127.0.0.1:8000")
    parser.add_argument("--device-id", default=socket.gethostname().lower().replace(" ", "-"))
    parser.add_argument("--device-name", default=f"Windows Agent {socket.gethostname()}")
    parser.add_argument("--poll-interval", type=int, default=4)
    args = parser.parse_args()

    agent = WindowsDeviceAgent(
        core_url=args.core_url,
        device_id=args.device_id,
        device_name=args.device_name,
        poll_interval=args.poll_interval,
    )
    agent.poll_forever()


if __name__ == "__main__":
    main()
