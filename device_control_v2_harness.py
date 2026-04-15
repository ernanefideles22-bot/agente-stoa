import sys

from fastapi.testclient import TestClient

sys.path.insert(0, r"C:\Users\ernan\Downloads\agente stoa")

import main


def main_harness() -> None:
    client = TestClient(main.app)

    register = client.post(
        "/api/devices/register",
        json={
            "device_id": "windows-main",
            "device_name": "Windows Main",
            "platform": "windows",
            "hostname": "main-host",
            "capabilities": [
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
                    "title": "Executar shell",
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
                    "risk": "safe",
                    "requires_confirmation": False,
                },
            ],
        },
    )
    assert register.status_code == 200, register.text

    open_url = client.post("/api/command", json={"text": "abra https://example.com no windows"})
    assert open_url.status_code == 200, open_url.text
    open_url_payload = open_url.json()
    assert open_url_payload["data"]["details"]["device_action"]["action_type"] == "open_url"
    assert open_url_payload["data"]["details"]["device_action"]["status"] == "queued"

    shell = client.post("/api/command", json={"text": "execute o comando echo hello no windows"})
    assert shell.status_code == 200, shell.text
    shell_payload = shell.json()
    assert shell_payload["data"]["details"]["device_action"]["action_type"] == "run_shell_command"
    assert shell_payload["data"]["details"]["device_action"]["status"] == "waiting_confirmation"

    confirm = client.post("/api/command", json={"text": "confirmar ação do dispositivo"})
    assert confirm.status_code == 200, confirm.text
    confirm_payload = confirm.json()
    assert confirm_payload["data"]["details"]["device_action"]["status"] == "queued"

    heartbeat = client.post(
        "/api/devices/windows-main/heartbeat",
        json={
            "device_id": "windows-main",
            "status": "busy",
            "current_action_id": confirm_payload["data"]["details"]["device_action"]["action_id"],
            "last_result": {"output": "partial"},
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    heartbeat_payload = heartbeat.json()
    assert heartbeat_payload["device"]["status"] == "busy"

    list_devices = client.get("/api/devices")
    assert list_devices.status_code == 200, list_devices.text
    items = list_devices.json()["items"]
    assert items[0]["status"] in {"online", "busy"}
    print(
        {
            "open_url_status": open_url_payload["data"]["details"]["device_action"]["status"],
            "shell_status": shell_payload["data"]["details"]["device_action"]["status"],
            "confirm_status": confirm_payload["data"]["details"]["device_action"]["status"],
            "heartbeat_status": heartbeat_payload["device"]["status"],
        }
    )


if __name__ == "__main__":
    main_harness()
