import gc
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

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
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["STOA_STATE_DB"] = str(Path(tmpdir) / "stoa-state.db")
        main.brain = main.STOAQuantumBrain()
        client = TestClient(main.app)
        core = main.brain.device_control

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

        register_device(client, "goal-a", "Goal A", ["goal-a", "desk-a"], [open_url_cap, screenshot_cap, shell_cap])
        register_device(client, "goal-b", "Goal B", ["goal-b", "desk-b"], [open_url_cap, shell_cap])

        core.remember_contextual_device_preference(device_id="goal-a", goal_id="goal-1", action_type="take_screenshot", session_id="default")
        pref = core.get_contextual_preferred_device(goal_id="goal-1", action_type="take_screenshot", session_id="default")
        assert pref and pref["device_id"] == "goal-a"

        resolve = core.resolve_device_detailed(goal_id="goal-1", action_type="take_screenshot", session_id="default")
        assert resolve["status"] == "resolved"
        assert resolve["device"]["device_id"] == "goal-a"

        capability_missing_error = core._classify_action_error(core.actions.get("missing") or type("X",(object,),{"action_type":"open_app"})(), "não declarou suporte")
        assert capability_missing_error == "capability_missing"

        app_not_found_error = core._classify_action_error(type("X",(object,),{"action_type":"open_app"})(), "arquivo não encontrado")
        assert app_not_found_error == "target_not_found" or app_not_found_error == "app_not_found"

        retry_action_response = client.post(
            "/api/devices/actions",
            json={"device_id": "goal-a", "action_type": "open_url", "target": "https://retry-v5.test"},
        )
        retry_action = retry_action_response.json()["action"]
        dispatched = client.get("/api/devices/goal-a/actions/next").json()["action"]
        core.actions[dispatched["action_id"]].dispatched_at = (datetime.now() - timedelta(seconds=90)).isoformat()
        retry_updates = core.sweep_action_timeouts()
        retried = next(item for item in retry_updates if item["action_id"] == dispatched["action_id"])
        assert retried["status"] == "queued"
        assert retried["retry_count"] == 1
        assert retried["last_error_code"] == "timeout_transient"

        shell_request = client.post(
            "/api/devices/actions",
            json={"device_id": "goal-b", "action_type": "run_shell_command", "target": "echo broken", "confirmed": True},
        )
        assert shell_request.status_code == 200, shell_request.text
        shell_dispatched = client.get("/api/devices/goal-b/actions/next").json()["action"]
        failed = core.submit_action_result(
            "goal-b",
            shell_dispatched["action_id"],
            main.ActionResult(
                action_id=shell_dispatched["action_id"],
                device_id="goal-b",
                success=False,
                status="failed",
                error="Comando falhou com exit code 1.",
            ),
        )
        assert failed["status"] == "failed"
        assert failed["terminal_failure"] is True
        assert failed["terminal_reason_code"] in {"terminal_capability_or_target_failure", "retry_budget_exhausted", "terminal_unknown_failure"}
        assert failed["last_error_code"] == "command_failed"

        core.devices["goal-b"].last_heartbeat_at = (datetime.now() - timedelta(minutes=10)).isoformat()
        offline = client.post("/api/command", json={"text": "abra https://openai.com no goal-b"})
        assert offline.status_code == 200, offline.text
        assert "Nenhum dispositivo online" in offline.json()["response"]

        timeline = client.get("/api/events/trajectories?event_domain=device&limit=20")
        assert timeline.status_code == 200, timeline.text
        summary = timeline.json()["summary"]
        assert summary["episode_count"] >= 1

        print(
            {
                "context_pref_device": pref["device_id"],
                "resolved_device": resolve["device"]["device_id"],
                "retry_error_code": retried["last_error_code"],
                "terminal_error_code": failed["last_error_code"],
                "terminal_reason_code": failed["terminal_reason_code"],
                "timeline_goal_narrative": summary.get("active_goal_narrative"),
            }
        )
        del client
        del core
        os.environ.pop("STOA_STATE_DB", None)
        gc.collect()


if __name__ == "__main__":
    main_harness()
