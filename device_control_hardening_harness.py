import gc
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, r"C:\Users\ernan\Downloads\agente stoa")

import main


def register_device(client: TestClient, device_id: str, name: str, aliases: list[str]) -> None:
    capabilities = [
        {
            "capability_id": "windows.open_url",
            "action_type": "open_url",
            "title": "Abrir URL",
            "description": "Abre URL",
            "platform": "windows",
            "risk": "safe",
            "requires_confirmation": False,
        },
        {
            "capability_id": "windows.run_shell_command",
            "action_type": "run_shell_command",
            "title": "Shell",
            "description": "Executa shell",
            "platform": "windows",
            "risk": "sensitive",
            "requires_confirmation": True,
        },
        {
            "capability_id": "windows.take_screenshot",
            "action_type": "take_screenshot",
            "title": "Screenshot",
            "description": "Captura tela",
            "platform": "windows",
            "risk": "sensitive",
            "requires_confirmation": True,
        },
        {
            "capability_id": "windows.open_app",
            "action_type": "open_app",
            "title": "Abrir app",
            "description": "Abre aplicativo",
            "platform": "windows",
            "risk": "safe",
            "requires_confirmation": False,
        },
    ]
    response = client.post(
        "/api/devices/register",
        json={
            "device_id": device_id,
            "device_name": name,
            "platform": "windows",
            "hostname": f"{device_id}-host",
            "aliases": aliases,
            "capabilities": capabilities,
        },
    )
    assert response.status_code == 200, response.text


def main_harness() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["STOA_STATE_DB"] = str(Path(tmpdir) / "stoa-state.db")
        main.brain = main.STOAQuantumBrain()
        client = TestClient(main.app)
        try:
            register_device(client, "fideles", "Windows Agent fideles", ["fideles", "windows"])
            register_device(client, "atlas", "Windows Agent atlas", ["atlas"])
            register_device(client, "old-node", "Windows Agent old-node", ["old-node"])

            shell_with_path = client.post(
                "/api/command",
                json={"text": 'execute o comando type "C:\\Users\\ernan\\file name.txt" no fideles'},
            )
            assert shell_with_path.status_code == 200, shell_with_path.text
            shell_payload = shell_with_path.json()
            shell_action = shell_payload["data"]["details"]["device_action"]
            assert shell_action["action_type"] == "run_shell_command"
            assert shell_payload["data"]["details"]["device_target_resolved"] == "fideles"
            assert shell_action["parameters"]["command"] == 'type "C:\\Users\\ernan\\file name.txt"'
            shell_confirm = client.post("/api/command", json={"text": f"confirmar ação {shell_action['action_id']}"})
            assert shell_confirm.status_code == 200, shell_confirm.text

            app_with_path = client.post(
                "/api/command",
                json={"text": 'abra o aplicativo "C:\\Program Files\\App\\tool.exe" no fideles'},
            )
            assert app_with_path.status_code == 200, app_with_path.text
            app_action = app_with_path.json()["data"]["details"]["device_action"]
            assert app_action["action_type"] == "open_app"
            assert app_action["target"] == '"C:\\Program Files\\App\\tool.exe"'

            other_session_pending = client.post(
                "/api/devices/actions",
                json={
                    "device_id": "atlas",
                    "action_type": "run_shell_command",
                    "target": "echo other",
                    "requested_by": "stoa_chat",
                    "parameters": {"session_id": "other-session"},
                },
            )
            assert other_session_pending.status_code == 200, other_session_pending.text

            screenshot_default = client.post("/api/command", json={"text": "capture a tela no fideles"})
            assert screenshot_default.status_code == 200, screenshot_default.text
            screenshot_action = screenshot_default.json()["data"]["details"]["device_action"]
            assert screenshot_action["status"] == "waiting_confirmation"

            confirm_last = client.post("/api/command", json={"text": "confirmar última ação"})
            assert confirm_last.status_code == 200, confirm_last.text
            confirmed_action = confirm_last.json()["data"]["details"]["device_action"]
            assert confirmed_action["action_id"] == screenshot_action["action_id"]
            assert confirmed_action["status"] == "queued"

            pending_a = client.post(
                "/api/devices/actions",
                json={
                    "device_id": "fideles",
                    "action_type": "run_shell_command",
                    "target": "echo a",
                    "requested_by": "stoa_chat",
                    "parameters": {"session_id": "default"},
                },
            )
            pending_b = client.post(
                "/api/devices/actions",
                json={
                    "device_id": "atlas",
                    "action_type": "run_shell_command",
                    "target": "echo b",
                    "requested_by": "stoa_chat",
                    "parameters": {"session_id": "default"},
                },
            )
            assert pending_a.status_code == 200 and pending_b.status_code == 200

            ambiguous = client.post("/api/command", json={"text": "confirmar última ação"})
            assert ambiguous.status_code == 200, ambiguous.text
            ambiguous_payload = ambiguous.json()
            assert ambiguous_payload["data"]["details"]["next_unlock_action"] == "choose_pending_action_id"
            assert "Action ID" in ambiguous_payload["response"]

            old_device = main.brain.device_control.devices["old-node"]
            old_device.last_seen_at = (datetime.now() - timedelta(days=3)).isoformat()
            old_device.last_heartbeat_at = old_device.last_seen_at
            old_device.current_action_id = None
            old_device.queue_depth = 0
            main.brain.device_control._persist_device("old-node")
            devices_after_prune = main.brain.device_control.list_devices()
            assert all(device["device_id"] != "old-node" for device in devices_after_prune)

            print(
                {
                    "shell_command": shell_action["parameters"]["command"],
                    "app_target": app_action["target"],
                    "confirm_last_status": confirmed_action["status"],
                    "ambiguous_next_unlock": ambiguous_payload["data"]["details"]["next_unlock_action"],
                    "offline_pruned": all(device["device_id"] != "old-node" for device in devices_after_prune),
                }
            )
        finally:
            del client
            del main.brain
            os.environ.pop("STOA_STATE_DB", None)
            gc.collect()


if __name__ == "__main__":
    main_harness()
