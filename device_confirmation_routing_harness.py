import gc
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, r"C:\Users\ernan\Downloads\agente stoa")

import main


def register_device(client: TestClient, device_id: str) -> None:
    capabilities = [
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
            "device_name": f"Windows {device_id}",
            "platform": "windows",
            "hostname": f"{device_id}-host",
            "aliases": [device_id],
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
            register_device(client, "fideles")
            register_device(client, "atlas")

            first = client.post("/api/command", json={"text": "execute o comando echo ok no fideles"})
            second = client.post("/api/command", json={"text": "execute o comando echo newer no fideles"})
            third = client.post("/api/command", json={"text": "capture a tela no atlas"})
            assert first.status_code == 200 and second.status_code == 200 and third.status_code == 200

            latest_before_confirm = third.json()["data"]["details"]["device_action"]["action_id"]
            confirm_last = client.post("/api/command", json={"text": "confirmar última ação"})
            assert confirm_last.status_code == 200, confirm_last.text
            confirm_last_payload = confirm_last.json()
            assert confirm_last_payload["module"] == "device_control"
            assert confirm_last_payload["data"]["mode"] == "ops"
            assert confirm_last_payload["data"]["details"]["device_action"]["status"] == "queued"
            assert confirm_last_payload["data"]["details"]["device_action"]["action_id"] == latest_before_confirm

            cancel_a = client.post("/api/command", json={"text": "execute o comando echo a no fideles"})
            cancel_b = client.post("/api/command", json={"text": "execute o comando echo b no atlas"})
            cancel_c = client.post("/api/command", json={"text": "capture a tela no fideles"})
            assert cancel_a.status_code == 200 and cancel_b.status_code == 200 and cancel_c.status_code == 200
            latest_before_cancel = cancel_c.json()["data"]["details"]["device_action"]["action_id"]
            cancel_last = client.post("/api/command", json={"text": "cancelar última ação"})
            assert cancel_last.status_code == 200, cancel_last.text
            cancel_last_payload = cancel_last.json()
            assert cancel_last_payload["module"] == "device_control"
            assert cancel_last_payload["data"]["details"]["device_action"]["status"] == "cancelled"
            assert cancel_last_payload["data"]["details"]["device_action"]["action_id"] == latest_before_cancel

            ambiguous = client.post("/api/command", json={"text": "confirmar acao"})
            assert ambiguous.status_code == 200, ambiguous.text
            ambiguous_payload = ambiguous.json()
            assert ambiguous_payload["module"] == "device_control"
            assert ambiguous_payload["data"]["details"]["next_unlock_action"] == "choose_pending_action_id"
            assert "Action ID" in ambiguous_payload["response"]
            assert ambiguous_payload["data"]["mode"] == "ops"
            pending_actions = ambiguous_payload["data"]["details"]["pending_device_actions"]
            assert len(pending_actions) >= 2
            assert pending_actions[0]["is_latest"] is True
            assert all("action_id" in item and "summary" in item for item in pending_actions)

            print(
                {
                    "confirm_mode": confirm_last_payload["data"]["mode"],
                    "confirm_module": confirm_last_payload["module"],
                    "confirm_latest_action_id": confirm_last_payload["data"]["details"]["device_action"]["action_id"],
                    "cancel_status": cancel_last_payload["data"]["details"]["device_action"]["status"],
                    "cancel_latest_action_id": cancel_last_payload["data"]["details"]["device_action"]["action_id"],
                    "ambiguous_next_unlock": ambiguous_payload["data"]["details"]["next_unlock_action"],
                    "latest_flag": pending_actions[0]["is_latest"],
                }
            )
        finally:
            del client
            del main.brain
            os.environ.pop("STOA_STATE_DB", None)
            gc.collect()


if __name__ == "__main__":
    main_harness()
