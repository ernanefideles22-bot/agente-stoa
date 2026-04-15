import json
import sys
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

sys.path.insert(0, r"C:\Users\ernan\Downloads\agente stoa")

import main


def register_device(client: TestClient, device_id: str, name: str, aliases: list[str], capabilities: list[dict]) -> None:
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
    client = TestClient(main.app)
    open_url_cap = {
        "capability_id": "windows.open_url",
        "action_type": "open_url",
        "title": "Abrir URL",
        "description": "Abre URL",
        "platform": "windows",
        "risk": "safe",
        "requires_confirmation": False,
    }
    shell_cap = {
        "capability_id": "windows.run_shell_command",
        "action_type": "run_shell_command",
        "title": "Executar shell",
        "description": "Executa shell",
        "platform": "windows",
        "risk": "sensitive",
        "requires_confirmation": True,
    }
    screenshot_cap = {
        "capability_id": "windows.take_screenshot",
        "action_type": "take_screenshot",
        "title": "Screenshot",
        "description": "Captura tela",
        "platform": "windows",
        "risk": "safe",
        "requires_confirmation": False,
    }

    register_device(client, "alpha", "Windows Alpha", ["alpha", "desk-alpha"], [open_url_cap, shell_cap, screenshot_cap])
    register_device(client, "beta", "Windows Beta", ["beta", "desk-beta"], [open_url_cap, shell_cap])

    ambiguous = client.post("/api/command", json={"text": "abra https://example.com"})
    assert ambiguous.status_code == 200, ambiguous.text
    ambiguous_payload = ambiguous.json()
    assert "Mais de um dispositivo" in ambiguous_payload["response"], ambiguous_payload

    resolved = client.post("/api/command", json={"text": "abra https://example.com no alpha"})
    assert resolved.status_code == 200, resolved.text
    resolved_payload = resolved.json()
    assert resolved_payload["data"]["details"]["device_action"]["action_type"] == "open_url"

    shell = client.post("/api/command", json={"text": "execute o comando echo hello no alpha"})
    assert shell.status_code == 200, shell.text
    shell_payload = shell.json()
    action_id = shell_payload["data"]["details"]["device_action"]["action_id"]
    assert shell_payload["data"]["details"]["device_confirmation"]["action_id"] == action_id

    with client.websocket_connect("/ws") as websocket:
        confirm = client.post("/api/command", json={"text": f"confirmar ação {action_id}"})
        assert confirm.status_code == 200, confirm.text
        queued_event = json.loads(websocket.receive_text())
        dispatched_pull = client.get("/api/devices/alpha/actions/next")
        assert dispatched_pull.status_code == 200, dispatched_pull.text
        dispatched_event = json.loads(websocket.receive_text())
        assert queued_event["type"] == "device_event"
        assert dispatched_event["type"] == "device_event"

    main.brain.device_control.devices["beta"].last_heartbeat_at = (datetime.now() - timedelta(minutes=10)).isoformat()
    offline = client.post("/api/command", json={"text": "capture a tela no beta"})
    assert offline.status_code == 200, offline.text
    assert "Nenhum dispositivo online" in offline.json()["response"] or "Há dispositivos registrados, mas nenhum está online." in offline.json()["response"]

    print(
        {
            "ambiguous_status": ambiguous_payload["data"]["status"],
            "resolved_action": resolved_payload["data"]["details"]["device_action"]["action_type"],
            "confirmation_action_id": action_id,
            "queued_event_type": queued_event["event"]["event_type"],
            "dispatched_event_type": dispatched_event["event"]["event_type"],
            "offline_response": offline.json()["response"],
        }
    )


if __name__ == "__main__":
    main_harness()
