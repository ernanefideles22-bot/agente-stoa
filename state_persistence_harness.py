import os
import sys
import tempfile
import gc
from pathlib import Path

sys.path.insert(0, r"C:\Users\ernan\Downloads\agente stoa")

import main
from device_control_models import ActionRequest, ActionResult, DeviceRegistration


def build_brain(db_path: str):
    os.environ["STOA_STATE_DB"] = db_path
    return main.STOAQuantumBrain()


def main_harness() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "stoa-state.db")

        brain1 = build_brain(db_path)
        brain1._create_active_goal(
            title="Goal persistido",
            description="Goal para rehydration",
            plan_steps=[{"id": "step_1", "title": "Etapa 1", "status": "pending"}],
            current_step_index=0,
            operation_id="op_goal_1",
        )
        brain1._update_working_context(
            current_goal="Goal persistido",
            current_plan_goal="Goal persistido",
            current_plan_steps=[{"id": "step_1", "title": "Etapa 1", "status": "pending"}],
            last_operation_id="op_goal_1",
            last_files=["main.py"],
        )
        brain1._create_pending_preview(
            {
                "goal": "Goal persistido",
                "plan_steps": [{"id": "step_1", "title": "Etapa 1", "status": "pending"}],
                "steps": [{"type": "append_to_file", "path": "main.py"}],
            },
            {
                "summary": "Preview persistido",
                "files_to_change": ["main.py"],
                "steps": [{"path": "main.py", "would_modify": True}],
            },
        )
        brain1.operational_state["current_phase"] = "awaiting_confirmation"
        brain1.operational_state["pending_preview_id"] = brain1.pending_preview["id"]
        brain1._persist_operational_state()

        registration = DeviceRegistration(
            device_id="persist-win",
            device_name="Persist Windows",
            platform="windows",
            hostname="persist-host",
            aliases=["persist-win", "persist"],
            capabilities=[
                {
                    "capability_id": "windows.open_url",
                    "action_type": "open_url",
                    "title": "Abrir URL",
                    "description": "Abre URL",
                    "platform": "windows",
                    "risk": "safe",
                    "requires_confirmation": False,
                }
            ],
        )
        brain1.device_control.register_device(registration)
        queued = brain1.device_control.request_action(
            ActionRequest(
                device_id="persist-win",
                action_type="open_url",
                target="https://example.com",
                parameters={"goal_id": brain1.active_goal["goal_id"], "session_id": "default"},
                confirmed=True,
            )
        )
        dispatched = brain1.device_control.get_next_action("persist-win")
        assert dispatched["status"] == "dispatched"
        result = brain1.device_control.submit_action_result(
            "persist-win",
            dispatched["action_id"],
            ActionResult(
                action_id=dispatched["action_id"],
                device_id="persist-win",
                success=True,
                status="succeeded",
                output="ok",
            ),
        )
        assert result["status"] == "succeeded"

        queued_again = brain1.device_control.request_action(
            ActionRequest(
                device_id="persist-win",
                action_type="open_url",
                target="https://queued.example",
                parameters={"goal_id": brain1.active_goal["goal_id"], "session_id": "default"},
                confirmed=True,
            )
        )
        inflight = brain1.device_control.get_next_action("persist-win")
        assert inflight["status"] == "dispatched"

        brain2 = build_brain(db_path)

        assert brain2.pending_preview is not None
        assert brain2.pending_preview["summary"] == "Preview persistido"
        assert brain2.active_goal is not None
        assert brain2.active_goal["title"] == "Goal persistido"
        assert brain2.working_context["current_goal"] == "Goal persistido"
        assert brain2.operational_state["current_phase"] == "awaiting_confirmation"

        restored_device = brain2.device_control.get_device("persist-win")
        assert restored_device is not None

        restored_completed = brain2.device_control.actions[result["action_id"]].model_dump()
        assert restored_completed["status"] == "succeeded"
        assert restored_completed["result"]["output"] == "ok"

        restored_inflight = brain2.device_control.actions[inflight["action_id"]].model_dump()
        assert restored_inflight["status"] == "queued"
        next_after_restart = brain2.device_control.get_next_action("persist-win")
        assert next_after_restart is not None
        assert next_after_restart["action_id"] == inflight["action_id"]

        print(
            {
                "preview_restored": brain2.pending_preview["id"],
                "goal_restored": brain2.active_goal["goal_id"],
                "device_restored": restored_device["device_id"],
                "completed_action_status": restored_completed["status"],
                "requeued_action_status": restored_inflight["status"],
                "next_after_restart": next_after_restart["action_id"],
                "queued_action_id": queued_again["action_id"],
            }
        )
        del brain1
        del brain2
        os.environ.pop("STOA_STATE_DB", None)
        gc.collect()


if __name__ == "__main__":
    main_harness()
