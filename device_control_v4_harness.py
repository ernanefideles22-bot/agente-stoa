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
    screenshot_cap = {
        "capability_id": "windows.take_screenshot",
        "action_type": "take_screenshot",
        "title": "Screenshot",
        "description": "Captura tela",
        "platform": "windows",
        "risk": "safe",
        "requires_confirmation": False,
    }
    shell_cap = {
        "capability_id": "windows.run_shell_command",
        "action_type": "run_shell_command",
        "title": "Shell",
        "description": "Executa shell",
        "platform": "windows",
        "risk": "sensitive",
        "requires_confirmation": True,
    }

    register_device(client, "alpha-v4", "Alpha V4", ["alpha-v4", "desk-a"], [open_url_cap, screenshot_cap, shell_cap])
    register_device(client, "beta-v4", "Beta V4", ["beta-v4", "desk-b"], [open_url_cap, screenshot_cap, shell_cap])

    preferred = client.post("/api/command", json={"text": "abra https://example.com no alpha-v4"})
    assert preferred.status_code == 200, preferred.text
    preferred_payload = preferred.json()
    assert preferred_payload["data"]["details"]["preferred_device_id"] == "alpha-v4"

    followup = client.post("/api/command", json={"text": "capture a tela"})
    assert followup.status_code == 200, followup.text
    followup_payload = followup.json()
    assert followup_payload["data"]["details"]["device_target_resolved"] == "alpha-v4"

    ambiguous = client.post("/api/command", json={"text": "abra https://openai.com no desk"})
    assert ambiguous.status_code == 200, ambiguous.text
    assert "Mais de um dispositivo" in ambiguous.json()["response"]

    retry_action_response = client.post(
        "/api/devices/actions",
        json={"device_id": "alpha-v4", "action_type": "open_url", "target": "https://retry.test"},
    )
    retry_action = retry_action_response.json()["action"]
    dispatched = client.get("/api/devices/alpha-v4/actions/next").json()["action"]
    core = main.brain.device_control
    core.actions[dispatched["action_id"]].dispatched_at = (datetime.now() - timedelta(seconds=90)).isoformat()
    retry_updates = core.sweep_action_timeouts()
    retried = next(item for item in retry_updates if item["action_id"] == dispatched["action_id"])
    assert retried["status"] == "queued"
    assert retried["retry_count"] == 1
    assert retried["retryable"] is True

    terminal_action_response = client.post(
        "/api/devices/actions",
        json={"device_id": "beta-v4", "action_type": "run_shell_command", "target": "echo fail", "confirmed": True},
    )
    terminal_action = terminal_action_response.json()["action"]
    terminal_dispatched = client.get("/api/devices/beta-v4/actions/next").json()["action"]
    core.actions[terminal_dispatched["action_id"]].dispatched_at = (datetime.now() - timedelta(seconds=120)).isoformat()
    terminal_updates = core.sweep_action_timeouts()
    terminal = next(item for item in terminal_updates if item["action_id"] == terminal_dispatched["action_id"])
    assert terminal["status"] == "failed"
    assert terminal["terminal_failure"] is True

    timeline = client.get("/api/events/timeline?event_domain=device&limit=20")
    assert timeline.status_code == 200, timeline.text
    timeline_items = timeline.json()["items"]
    assert any(item.get("event_domain") == "device" for item in timeline_items)

    print(
        {
            "preferred_device": preferred_payload["data"]["details"]["preferred_device_id"],
            "followup_resolved": followup_payload["data"]["details"]["device_target_resolved"],
            "retry_status": retried["status"],
            "retry_count": retried["retry_count"],
            "terminal_status": terminal["status"],
            "terminal_failure": terminal["terminal_failure"],
            "device_timeline_events": len(timeline_items),
        }
    )


if __name__ == "__main__":
    main_harness()
