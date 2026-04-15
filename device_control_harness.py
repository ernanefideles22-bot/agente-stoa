from device_control_core import DeviceControlCore
from device_control_models import ActionRequest, ActionResult, ActionStatus, DeviceRegistration, DeviceCapability


def main() -> None:
    core = DeviceControlCore()
    device = core.register_device(
        DeviceRegistration(
            device_id="windows-dev-1",
            device_name="Windows Dev 1",
            platform="windows",
            hostname="lab-win",
            capabilities=[
                DeviceCapability(
                    capability_id="windows.open_url",
                    action_type="open_url",
                    title="Abrir URL",
                    description="Abre uma URL localmente.",
                    platform="windows",
                    risk="safe",
                ),
                DeviceCapability(
                    capability_id="windows.run_shell_command",
                    action_type="run_shell_command",
                    title="Executar shell",
                    description="Executa comando shell local.",
                    platform="windows",
                    risk="sensitive",
                    requires_confirmation=True,
                ),
            ],
        )
    )
    assert device["device_id"] == "windows-dev-1"

    safe_action = core.request_action(
        ActionRequest(
            device_id="windows-dev-1",
            action_type="open_url",
            target="https://example.com",
        )
    )
    assert safe_action["status"] == ActionStatus.QUEUED
    dispatched_safe = core.get_next_action("windows-dev-1")
    assert dispatched_safe["status"] == ActionStatus.DISPATCHED
    completed_safe = core.submit_action_result(
        "windows-dev-1",
        dispatched_safe["action_id"],
        ActionResult(
            action_id=dispatched_safe["action_id"],
            device_id="windows-dev-1",
            success=True,
            status=ActionStatus.COMPLETED,
            output="ok",
        ),
    )
    assert completed_safe["status"] == ActionStatus.COMPLETED

    sensitive_action = core.request_action(
        ActionRequest(
            device_id="windows-dev-1",
            action_type="run_shell_command",
            target="echo hello",
        )
    )
    assert sensitive_action["status"] == ActionStatus.AWAITING_CONFIRMATION
    confirmed = core.confirm_action(sensitive_action["action_id"], reason="Harness confirmation")
    assert confirmed["status"] == ActionStatus.QUEUED
    dispatched_sensitive = core.get_next_action("windows-dev-1")
    assert dispatched_sensitive["status"] == ActionStatus.DISPATCHED
    failed_sensitive = core.submit_action_result(
        "windows-dev-1",
        dispatched_sensitive["action_id"],
        ActionResult(
            action_id=dispatched_sensitive["action_id"],
            device_id="windows-dev-1",
            success=False,
            status=ActionStatus.FAILED,
            error="command failed",
        ),
    )
    assert failed_sensitive["status"] == ActionStatus.FAILED

    recent_actions = core.list_actions(limit=10)
    assert len(recent_actions) >= 2
    print(
        {
            "device_count": len(core.list_devices()),
            "recent_action_statuses": [action["status"] for action in recent_actions[:2]],
            "confirmation_flow_ok": True,
        }
    )


if __name__ == "__main__":
    main()
