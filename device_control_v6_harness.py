import gc
import os
import sys
import tempfile
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

            open_url = client.post("/api/command", json={"text": "abra https://example.com no fideles"})
            assert open_url.status_code == 200, open_url.text
            open_url_payload = open_url.json()
            open_url_action = open_url_payload["data"]["details"]["device_action"]
            assert open_url_action["action_type"] == "open_url"
            assert open_url_payload["data"]["details"]["device_target_resolved"] == "fideles"
            assert open_url_action["target"] == "https://example.com"

            shell = client.post("/api/command", json={"text": "execute o comando echo hello no fideles"})
            assert shell.status_code == 200, shell.text
            shell_payload = shell.json()
            shell_action = shell_payload["data"]["details"]["device_action"]
            assert shell_action["action_type"] == "run_shell_command"
            assert shell_payload["data"]["details"]["device_target_resolved"] == "fideles"
            assert shell_action["target"] == "echo hello"
            assert shell_action["parameters"]["command"] == "echo hello"
            shell_confirm = client.post("/api/command", json={"text": f"confirmar ação {shell_action['action_id']}"})
            assert shell_confirm.status_code == 200, shell_confirm.text

            screenshot = client.post("/api/command", json={"text": "capture a tela no fideles"})
            assert screenshot.status_code == 200, screenshot.text
            screenshot_payload = screenshot.json()
            screenshot_action = screenshot_payload["data"]["details"]["device_action"]
            assert screenshot_action["action_type"] == "take_screenshot"
            assert screenshot_action["status"] == "waiting_confirmation"
            assert screenshot_payload["data"]["details"]["device_confirmation"]["confirm_command"] == "confirmar última ação"

            confirm_last = client.post("/api/command", json={"text": "confirmar última ação"})
            assert confirm_last.status_code == 200, confirm_last.text
            confirm_action = confirm_last.json()["data"]["details"]["device_action"]
            assert confirm_action["action_id"] == screenshot_action["action_id"]
            assert confirm_action["status"] == "queued"

            screenshot_cancel = client.post("/api/command", json={"text": "capture a tela no fideles"})
            assert screenshot_cancel.status_code == 200, screenshot_cancel.text
            cancel_last = client.post("/api/command", json={"text": "cancelar última ação"})
            assert cancel_last.status_code == 200, cancel_last.text
            cancel_action = cancel_last.json()["data"]["details"]["device_action"]
            assert cancel_action["action_id"] == screenshot_cancel.json()["data"]["details"]["device_action"]["action_id"]
            assert cancel_action["status"] == "cancelled"

            pending_a = client.post("/api/devices/actions", json={"device_id": "fideles", "action_type": "run_shell_command", "target": "echo a"})
            pending_b = client.post("/api/devices/actions", json={"device_id": "atlas", "action_type": "run_shell_command", "target": "echo b"})
            assert pending_a.status_code == 200 and pending_b.status_code == 200
            ambiguous = client.post("/api/command", json={"text": "confirmar acao"})
            assert ambiguous.status_code == 200, ambiguous.text
            ambiguous_payload = ambiguous.json()
            assert "ação sensível pendente" in ambiguous_payload["response"]
            assert ambiguous_payload["data"]["details"]["next_unlock_action"] == "choose_pending_action_id"

            manual_confirm = client.post(
                "/api/command",
                json={"text": f"confirmar ação {pending_a.json()['action']['action_id']}"},
            )
            assert manual_confirm.status_code == 200, manual_confirm.text
            manual_action = manual_confirm.json()["data"]["details"]["device_action"]
            assert manual_action["action_id"] == pending_a.json()["action"]["action_id"]
            assert manual_action["status"] == "queued"

            print(
                {
                    "open_url_target": open_url_action["target"],
                    "shell_command": shell_action["parameters"]["command"],
                    "screenshot_status": screenshot_action["status"],
                    "confirm_last_status": confirm_action["status"],
                    "cancel_last_status": cancel_action["status"],
                    "ambiguous_next_unlock": ambiguous_payload["data"]["details"]["next_unlock_action"],
                    "manual_confirm_status": manual_action["status"],
                }
            )
        finally:
            del client
            del main.brain
            os.environ.pop("STOA_STATE_DB", None)
            gc.collect()


if __name__ == "__main__":
    main_harness()
