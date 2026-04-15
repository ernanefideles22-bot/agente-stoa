from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from executive_orchestrator import ExecutiveOrchestrator  # noqa: E402
from execution_event_query import ExecutionEventQuery  # noqa: E402
from trajectory_correlation import TrajectoryCorrelation  # noqa: E402


def load_main_module():
    spec = importlib.util.spec_from_file_location("stoa_main", PROJECT_DIR / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_snapshot(**overrides):
    snapshot = {
        "original_command": "",
        "effective_command": "",
        "forced_mode": None,
        "legacy_mode_hint": "conversation",
        "contextual_resolution_used": False,
        "context_fresh": False,
        "pending_preview_valid": False,
        "pending_preview_exists": False,
        "pending_preview_expired": False,
        "pending_preview_id": None,
        "pending_preview_goal": None,
        "pending_preview_plan_step_ids": [],
        "pending_preview_step_count": 0,
        "active_goal_status": None,
        "active_goal_id": None,
        "active_goal_step_count": 0,
        "active_goal_current_step_index": 0,
        "active_goal_next_step_id": None,
        "active_goal_next_step_status": None,
        "operational_phase": "idle",
        "working_context_file_count": 0,
        "has_failed_steps": False,
        "has_in_progress_steps": False,
        "working_context_summary": "",
        "last_operation_id": None,
    }
    snapshot.update(overrides)
    return snapshot


class DummyResponse:
    def __init__(self, mode: str, status: str, details: dict | None = None):
        self.data = {
            "mode": mode,
            "status": status,
            "details": details or {},
        }


def run_decision_harness():
    orchestrator = ExecutiveOrchestrator()
    cases = [
        {
            "name": "conversa simples",
            "command": "me explica esse erro",
            "legacy_mode_hint": "conversation",
            "snapshot": build_snapshot(),
            "expected_mode": "conversation",
            "expected_intent": "conversation",
        },
        {
            "name": "mutação destrutiva",
            "command": "apague a classe LegacyWorker do main.py",
            "legacy_mode_hint": "dev",
            "snapshot": build_snapshot(working_context_file_count=1),
            "expected_mode": "preview",
            "expected_intent": "mutation_request",
            "expected_confirmation": "preview_before_apply",
        },
        {
            "name": "continuidade com contexto fresco",
            "command": "use o mesmo arquivo",
            "legacy_mode_hint": "planner",
            "snapshot": build_snapshot(
                contextual_resolution_used=True,
                context_fresh=True,
                active_goal_status="active",
                working_context_file_count=1,
            ),
            "expected_mode": "planner",
            "expected_intent": "planner_or_guidance",
        },
        {
            "name": "continuidade ambígua com contexto fraco",
            "command": "continue",
            "legacy_mode_hint": "planner",
            "snapshot": build_snapshot(
                contextual_resolution_used=True,
                context_fresh=False,
                active_goal_status="active",
            ),
            "expected_mode": "planner",
            "expected_intent": "planner_or_guidance",
        },
        {
            "name": "pedido híbrido código+docs",
            "command": "crie uma rota /status e documente no README",
            "legacy_mode_hint": "dev",
            "snapshot": build_snapshot(working_context_file_count=2),
            "expected_mode": "preview",
            "expected_intent": "mutation_request",
            "expected_scope": "multi_file",
        },
        {
            "name": "apply com preview pendente",
            "command": "aplique isso",
            "legacy_mode_hint": "dev",
            "snapshot": build_snapshot(
                pending_preview_valid=True,
                pending_preview_exists=True,
                pending_preview_id="preview-test",
            ),
            "expected_mode": "dev",
            "expected_intent": "apply_preview",
            "expected_confirmation": "apply_pending_preview",
        },
        {
            "name": "consulta ops",
            "command": "qual foi a última operação aplicada?",
            "legacy_mode_hint": "ops",
            "snapshot": build_snapshot(),
            "expected_mode": "ops",
            "expected_intent": "ops_query",
        },
    ]

    failures = []
    for case in cases:
        decision = orchestrator.decide(
            case["command"],
            state_snapshot=case["snapshot"],
            legacy_mode_hint=case["legacy_mode_hint"],
        )
        result = {
            "name": case["name"],
            "command": case["command"],
            "mode": decision.mode,
            "intent": decision.intent.name,
            "risk_level": decision.risk.level,
            "confirmation_action": decision.confirmation.action,
            "scope": decision.operation_profile.scope,
            "destructive": decision.operation_profile.destructive,
        }
        if result["mode"] != case["expected_mode"]:
            failures.append((case["name"], f"mode={result['mode']}"))
        if result["intent"] != case["expected_intent"]:
            failures.append((case["name"], f"intent={result['intent']}"))
        if case.get("expected_confirmation") and result["confirmation_action"] != case["expected_confirmation"]:
            failures.append((case["name"], f"confirmation={result['confirmation_action']}"))
        if case.get("expected_scope") and result["scope"] != case["expected_scope"]:
            failures.append((case["name"], f"scope={result['scope']}"))
        print(json.dumps(result, ensure_ascii=False))

    return failures


def run_process_harness():
    module = load_main_module()
    brain = module.brain
    commands = [
        "me explica esse erro",
        "organize um plano para criar autenticação",
        "simule adicionar uma rota /status no main.py",
        "aplique isso",
        "qual foi a última operação aplicada?",
    ]

    async def _run():
        import asyncio

        results = []
        for command in commands:
            response = await brain.process_command(command)
            details = (response.data or {}).get("details") or {}
            results.append(
                {
                    "command": command,
                    "mode": (response.data or {}).get("mode"),
                    "status": (response.data or {}).get("status"),
                    "intent": details.get("intent"),
                    "risk_level": details.get("risk_level"),
                    "confirmation_action": details.get("confirmation_action"),
                    "has_transition": "operational_transition" in details,
                    "has_preview_validity": "preview_validity" in details,
                    "has_execution_model": "execution_model" in details,
                    "has_decision_explanation": "decision_explanation" in details,
                    "has_operational_state": "operational_state" in details,
                }
            )
        return results

    import asyncio

    return asyncio.run(_run())


def run_preview_policy_regression():
    orchestrator = ExecutiveOrchestrator()
    checks = []

    expired_snapshot = build_snapshot(
        pending_preview_exists=True,
        pending_preview_valid=False,
        pending_preview_expired=True,
        pending_preview_id="preview-expired",
    )
    expired_decision = orchestrator.decide("aplique isso", state_snapshot=expired_snapshot, legacy_mode_hint="dev")
    expired_validity = orchestrator.assess_preview_validity(
        expired_decision,
        DummyResponse("dev", "dev_preview_expired"),
        state_snapshot=expired_snapshot,
        runtime_state={
            "active_goal": {"goal_id": "goal-1", "status": "active", "title": "Atualizar status", "plan_steps": [{"id": "step_1", "status": "pending"}]},
            "pending_preview_status": {"exists": True, "valid": False, "expired": True, "preview": {"id": "preview-expired", "goal": "Atualizar status"}},
            "working_context": {"last_operation_id": "op_old", "current_step_index": 0},
        },
    )
    checks.append({
        "name": "preview_expired",
        "status": expired_validity.status,
        "severity": expired_validity.severity,
        "recommended_action": expired_validity.recommended_action,
    })

    invalid_snapshot = build_snapshot(
        pending_preview_exists=True,
        pending_preview_valid=True,
        pending_preview_id="preview-invalid",
        pending_preview_goal="Objetivo antigo",
        pending_preview_plan_step_ids=["step_old"],
        active_goal_status="active",
        active_goal_id="goal-new",
    )
    invalid_decision = orchestrator.decide("aplique isso", state_snapshot=invalid_snapshot, legacy_mode_hint="dev")
    invalid_validity = orchestrator.assess_preview_validity(
        invalid_decision,
        DummyResponse("dev", "dev_preview_missing"),
        state_snapshot=invalid_snapshot,
        runtime_state={
            "active_goal": {"goal_id": "goal-new", "status": "failed", "title": "Objetivo novo", "plan_steps": [{"id": "step_new", "status": "failed"}]},
            "pending_preview_status": {
                "exists": True,
                "valid": True,
                "expired": False,
                "preview": {"id": "preview-invalid", "goal": "Objetivo antigo", "plan_step_ids": ["step_old"], "operation_id": "op-preview"},
            },
            "working_context": {"last_operation_id": "op-new", "current_step_index": 0},
        },
    )
    checks.append({
        "name": "preview_invalidated",
        "status": invalid_validity.status,
        "severity": invalid_validity.severity,
        "causes": invalid_validity.invalidation_causes,
        "recommended_action": invalid_validity.recommended_action,
    })

    warning_snapshot = build_snapshot(
        pending_preview_exists=True,
        pending_preview_valid=True,
        pending_preview_id="preview-warning",
        active_goal_status="paused",
        has_failed_steps=True,
    )
    warning_decision = orchestrator.decide(
        "crie uma rota /status e documente no README",
        state_snapshot=warning_snapshot,
        legacy_mode_hint="preview",
    )
    warning_validity = orchestrator.assess_preview_validity(
        warning_decision,
        DummyResponse("preview", "preview_pending_stored"),
        state_snapshot=warning_snapshot,
        runtime_state={
            "active_goal": {"goal_id": "goal-2", "status": "paused", "title": "Status", "plan_steps": [{"id": "step_1", "status": "failed"}]},
            "pending_preview_status": {"exists": True, "valid": True, "expired": False, "preview": {"id": "preview-warning", "goal": "Status", "plan_step_ids": ["step_1"]}},
            "working_context": {"last_operation_id": "op-warning", "current_step_index": 0},
        },
    )
    checks.append({
        "name": "preview_warning",
        "status": warning_validity.status,
        "severity": warning_validity.severity,
        "causes": warning_validity.invalidation_causes,
        "recommended_action": warning_validity.recommended_action,
    })

    soft_snapshot = build_snapshot(
        pending_preview_exists=True,
        pending_preview_valid=True,
        pending_preview_id="preview-soft",
    )
    soft_decision = orchestrator.decide("continue", state_snapshot=soft_snapshot, legacy_mode_hint="planner")
    soft_validity = orchestrator.assess_preview_validity(
        soft_decision,
        DummyResponse("planner", "planner_plan_partial"),
        state_snapshot=soft_snapshot,
        runtime_state={
            "active_goal": {"goal_id": "goal-soft", "status": "active", "title": "Objetivo soft", "plan_steps": [{"id": "step_soft", "status": "pending"}]},
            "pending_preview_status": {
                "exists": True,
                "valid": True,
                "expired": False,
                "preview": {"id": "preview-soft", "goal": "Objetivo soft", "plan_step_ids": ["step_soft"], "operation_id": "op-preview-soft"},
            },
            "working_context": {"last_operation_id": "op-newer-soft", "current_step_index": 0},
        },
    )
    checks.append({
        "name": "preview_soft_invalid_review",
        "status": soft_validity.status,
        "severity": soft_validity.severity,
        "causes": soft_validity.invalidation_causes,
        "recommended_action": soft_validity.recommended_action,
    })

    return checks


def run_transition_and_completion_regression():
    orchestrator = ExecutiveOrchestrator()
    checks = []

    transition_decision = orchestrator.decide("me explica esse erro", state_snapshot=build_snapshot(), legacy_mode_hint="conversation")
    transition = orchestrator.derive_transition(
        transition_decision,
        DummyResponse("conversation", "conversation_answer"),
        current_state={"current_phase": "blocked"},
        runtime_state={"active_goal": {}, "pending_preview_status": {"exists": False, "valid": False, "expired": False, "preview": None}, "working_context": {}},
    )
    checks.append({
        "name": "transition_guard_recovery",
        "next_phase": transition.next_phase,
        "reason_code": transition.reason_code,
        "rule_name": transition.rule_name,
    })

    runtime_state = {
        "active_goal": {
            "goal_id": "goal-complete",
            "status": "active",
            "title": "Completar fluxo",
            "plan_steps": [{"id": "step_1", "status": "done"}, {"id": "step_2", "status": "done"}],
        },
        "pending_preview_status": {"exists": False, "valid": False, "expired": False, "preview": None},
        "working_context": {"current_step_index": 2},
    }
    completion = orchestrator.assess_completion(
        runtime_state,
        type("PV", (), {"severity": "ok"})(),
    )
    checks.append({
        "name": "completion_ready",
        "can_complete": completion.can_complete,
        "reason_code": completion.reason_code,
        "progress_ratio": completion.progress.progress_ratio,
    })

    rollback_runtime = {
        "active_goal": {
            "goal_id": "goal-rollback",
            "status": "failed",
            "title": "Rollback validation",
            "plan_steps": [{"id": "step_a", "status": "failed"}],
        },
        "pending_preview_status": {"exists": True, "valid": False, "expired": False, "preview": {"id": "preview-rollback"}},
        "working_context": {"last_operation_id": "op-rollback", "current_step_index": 0},
    }
    rollback_decision = orchestrator.decide("aplique isso", state_snapshot=build_snapshot(active_goal_status="failed", has_failed_steps=True), legacy_mode_hint="dev")
    rollback_transition = orchestrator.derive_transition(
        rollback_decision,
        DummyResponse("dev", "dev_apply_failed", {"operation_id": "op-rollback"}),
        current_state={"current_phase": "validating_changes"},
        runtime_state=rollback_runtime,
    )
    rollback_validity = orchestrator.assess_preview_validity(
        rollback_decision,
        DummyResponse("dev", "dev_apply_failed", {"operation_id": "op-rollback"}),
        state_snapshot=build_snapshot(active_goal_status="failed", has_failed_steps=True, pending_preview_exists=True, pending_preview_valid=False),
        runtime_state=rollback_runtime,
    )
    rollback_completion = orchestrator.assess_completion(rollback_runtime, rollback_validity)
    checks.append({
        "name": "rollback_after_validation_failure",
        "phase": rollback_transition.next_phase,
        "preview_severity": rollback_validity.severity,
        "completion_reason_code": rollback_completion.reason_code,
    })

    hard_continue_snapshot = build_snapshot(
        pending_preview_exists=True,
        pending_preview_valid=True,
        pending_preview_id="preview-hard-continue",
        pending_preview_goal="Objetivo antigo",
        pending_preview_plan_step_ids=["step_old"],
        active_goal_status="active",
        active_goal_id="goal-newer",
    )
    hard_continue_decision = orchestrator.decide("continue", state_snapshot=hard_continue_snapshot, legacy_mode_hint="planner")
    hard_continue_validity = orchestrator.assess_preview_validity(
        hard_continue_decision,
        DummyResponse("planner", "planner_plan_partial"),
        state_snapshot=hard_continue_snapshot,
        runtime_state={
            "active_goal": {"goal_id": "goal-newer", "status": "failed", "title": "Objetivo novo", "plan_steps": [{"id": "step_new", "status": "failed"}]},
            "pending_preview_status": {
                "exists": True,
                "valid": True,
                "expired": False,
                "preview": {"id": "preview-hard-continue", "goal": "Objetivo antigo", "plan_step_ids": ["step_old"], "operation_id": "op-old"},
            },
            "working_context": {"last_operation_id": "op-newer", "current_step_index": 0},
        },
    )
    checks.append({
        "name": "hard_invalid_continue",
        "mode": hard_continue_decision.mode,
        "severity": hard_continue_validity.severity,
        "recommended_action": hard_continue_validity.recommended_action,
        "causes": hard_continue_validity.invalidation_causes,
    })

    return checks


def run_chained_regression():
    module = load_main_module()
    brain = module.brain
    target = PROJECT_DIR / "orchestrator_v3_temp_target.py"
    target.write_text("def ping():\n    return 'ok'\n", encoding="utf-8")

    preview_command = f"simule criar uma classe OrchestratorV3Temp no arquivo {target.name} e depois valide o arquivo"

    async def _run():
        results = []
        try:
            preview_response = await brain.process_command(preview_command)
            preview_details = (preview_response.data or {}).get("details") or {}
            results.append(
                {
                    "step": "preview",
                    "status": (preview_response.data or {}).get("status"),
                    "mode": (preview_response.data or {}).get("mode"),
                    "preview_validity": (preview_details.get("preview_validity") or {}).get("status"),
                    "phase": (preview_details.get("operational_transition") or {}).get("next_phase"),
                    "next_unlock_action": preview_details.get("next_unlock_action"),
                }
            )

            apply_response = await brain.process_command("aplique isso")
            apply_details = (apply_response.data or {}).get("details") or {}
            results.append(
                {
                    "step": "apply",
                    "status": (apply_response.data or {}).get("status"),
                    "mode": (apply_response.data or {}).get("mode"),
                    "execution_status": (apply_details.get("execution_model") or {}).get("execution_status"),
                    "phase": (apply_details.get("operational_transition") or {}).get("next_phase"),
                    "next_unlock_action": apply_details.get("next_unlock_action"),
                }
            )

            preview_again = await brain.process_command(preview_command)
            cancel_response = await brain.process_command("cancelar preview")
            cancel_details = (cancel_response.data or {}).get("details") or {}
            results.append(
                {
                    "step": "cancel",
                    "status": (cancel_response.data or {}).get("status"),
                    "mode": (cancel_response.data or {}).get("mode"),
                    "preview_validity": (cancel_details.get("preview_validity") or {}).get("status"),
                    "phase": (cancel_details.get("operational_transition") or {}).get("next_phase"),
                    "next_unlock_action": cancel_details.get("next_unlock_action"),
                    "repreview_status": (preview_again.data or {}).get("status"),
                }
            )
        finally:
            if target.exists():
                target.unlink()
        return results

    import asyncio

    return asyncio.run(_run())


def run_event_query_regression():
    events = ExecutionEventQuery.query(limit=25)
    summary = ExecutionEventQuery.summarize(events)
    severity_filtered = ExecutionEventQuery.query(severity="error", limit=10)
    preview_filtered = ExecutionEventQuery.query(event_domain="preview", limit=10)
    return [
        {
            "name": "event_query_recent",
            "count": len(events),
            "has_execution_taxonomy": any(event.get("event_code") for event in events),
            "has_preview_domain": any(event.get("event_domain") == "preview" for event in events),
        },
        {
            "name": "event_query_summary",
            "count": summary.get("count"),
            "by_phase": summary.get("by_phase"),
            "by_domain": summary.get("by_domain"),
        },
        {
            "name": "event_query_filters",
            "error_count": len(severity_filtered),
            "preview_count": len(preview_filtered),
        },
    ]


def run_trajectory_regression():
    grouped = TrajectoryCorrelation.query_grouped(limit=40)
    episodes = grouped.get("episodes") or []
    summary = grouped.get("summary") or {}
    return [
        {
            "name": "trajectory_grouping",
            "episode_count": len(episodes),
            "has_goal_episode": any(episode.get("goal_id") for episode in episodes),
            "has_preview_episode": any(episode.get("preview_id") for episode in episodes),
        },
        {
            "name": "trajectory_summary",
            "goal_current": summary.get("goal_current"),
            "dominant_phase": summary.get("dominant_phase"),
            "next_unlock_action": summary.get("next_unlock_action"),
            "blockers_active": summary.get("blockers_active"),
        },
        {
            "name": "trajectory_mixed_history",
            "has_legacy_or_guard": any(
                any(event.get("event_domain") in {"legacy", "guard"} for event in (episode.get("events") or []))
                for episode in episodes
            ),
            "has_new_taxonomy": any(
                any((event.get("event_code") or "").startswith(("preview.", "operation.", "goal.", "step.", "validation.", "guard.")) for event in (episode.get("events") or []))
                for episode in episodes
            ),
        },
    ]


def run_episode_refinement_regression():
    synthetic = [
        {
            "event_id": "evt_goal_preview",
            "event_type": "preview:preview_pending_stored",
            "event_code": "preview.created",
            "event_domain": "preview",
            "event_subject": "preview",
            "event_outcome": "created",
            "severity": "info",
            "phase": "awaiting_confirmation",
            "goal_id": "goal_same",
            "step_id": "step_1",
            "operation_id": "op_1",
            "preview_id": "preview_1",
            "reason_code": "pending_steps_remaining",
            "summary": "Preview criado para op_1",
            "timestamp": "2026-03-22T10:00:00",
            "metadata": {"next_unlock_action": "apply_preview", "preview_validity_status": "valid", "preview_validity_severity": "ok", "blocker_codes": []},
        },
        {
            "event_id": "evt_goal_apply_fail",
            "event_type": "dev:dev_apply_failed",
            "event_code": "operation.failed",
            "event_domain": "operation",
            "event_subject": "operation",
            "event_outcome": "failed",
            "severity": "error",
            "phase": "blocked",
            "goal_id": "goal_same",
            "step_id": "step_1",
            "operation_id": "op_1",
            "preview_id": "preview_1",
            "reason_code": "operation_failed",
            "summary": "Falha na aplicação",
            "timestamp": "2026-03-22T10:03:00",
            "metadata": {"next_unlock_action": "review_preview", "blocker_codes": ["operation_failed"]},
        },
        {
            "event_id": "evt_goal_retry_preview",
            "event_type": "preview:preview_pending_stored",
            "event_code": "preview.created",
            "event_domain": "preview",
            "event_subject": "preview",
            "event_outcome": "created",
            "severity": "warning",
            "phase": "awaiting_confirmation",
            "goal_id": "goal_same",
            "step_id": "step_1",
            "operation_id": "op_1",
            "preview_id": "preview_2",
            "reason_code": "pending_steps_remaining",
            "summary": "Retry do preview",
            "timestamp": "2026-03-22T10:07:00",
            "metadata": {"next_unlock_action": "apply_preview", "preview_validity_status": "valid", "preview_validity_severity": "warning", "blocker_codes": []},
        },
        {
            "event_id": "evt_cancel_replan",
            "event_type": "dev:dev_preview_cancelled",
            "event_code": "preview.cancelled",
            "event_domain": "preview",
            "event_subject": "preview",
            "event_outcome": "cancelled",
            "severity": "warning",
            "phase": "awaiting_preview",
            "goal_id": "goal_same",
            "step_id": "step_1",
            "operation_id": "op_1",
            "preview_id": "preview_2",
            "reason_code": "pending_steps_remaining",
            "summary": "Preview cancelado antes do replan",
            "timestamp": "2026-03-22T10:08:00",
            "metadata": {"next_unlock_action": "generate_preview", "blocker_codes": []},
        },
        {
            "event_id": "evt_guard_lonely",
            "event_type": "orchestrator_decision",
            "event_code": "guard.decided",
            "event_domain": "guard",
            "event_subject": "decision",
            "event_outcome": "recorded",
            "severity": "info",
            "phase": "observing",
            "goal_id": None,
            "step_id": None,
            "operation_id": None,
            "preview_id": None,
            "reason_code": "transition_guard",
            "summary": "Guard isolado",
            "timestamp": "2026-03-22T10:08:30",
            "metadata": {},
        },
        {
            "event_id": "evt_independent_a",
            "event_type": "preview:preview_pending_stored",
            "event_code": "preview.created",
            "event_domain": "preview",
            "event_subject": "preview",
            "event_outcome": "created",
            "severity": "info",
            "phase": "awaiting_confirmation",
            "goal_id": "goal_dual",
            "step_id": "step_a",
            "operation_id": "op_a",
            "preview_id": "preview_a",
            "reason_code": "pending_steps_remaining",
            "summary": "Operação A",
            "timestamp": "2026-03-22T11:00:00",
            "metadata": {"next_unlock_action": "apply_preview", "preview_validity_status": "valid", "preview_validity_severity": "ok"},
        },
        {
            "event_id": "evt_independent_b",
            "event_type": "preview:preview_pending_stored",
            "event_code": "preview.created",
            "event_domain": "preview",
            "event_subject": "preview",
            "event_outcome": "created",
            "severity": "info",
            "phase": "awaiting_confirmation",
            "goal_id": "goal_dual",
            "step_id": "step_b",
            "operation_id": "op_b",
            "preview_id": "preview_b",
            "reason_code": "pending_steps_remaining",
            "summary": "Operação B",
            "timestamp": "2026-03-22T11:30:00",
            "metadata": {"next_unlock_action": "apply_preview", "preview_validity_status": "valid", "preview_validity_severity": "ok"},
        },
        {
            "event_id": "legacy_old",
            "event_type": "preview_created",
            "event_code": "preview.created",
            "event_domain": "legacy",
            "event_subject": "event",
            "event_outcome": "observed",
            "severity": "info",
            "phase": "observing",
            "goal_id": None,
            "step_id": None,
            "operation_id": None,
            "preview_id": None,
            "reason_code": "preview.created",
            "summary": "Legacy preview",
            "timestamp": "2026-03-22T09:59:00",
            "metadata": {},
        },
    ]
    raw = TrajectoryCorrelation.build_episodes(synthetic)
    visible, hidden = TrajectoryCorrelation.refine_episodes(raw)
    refined_all = visible + hidden
    summary = TrajectoryCorrelation._operational_summary(visible, hidden, synthetic)
    return [
        {
            "name": "retry_and_cancel_replan",
            "has_goal_same": any(ep.get("goal_id") == "goal_same" for ep in refined_all),
            "goal_same_next_unlock": next((ep.get("next_unlock_action") for ep in refined_all if ep.get("goal_id") == "goal_same"), None),
        },
        {
            "name": "guard_isolated_hidden",
            "hidden_guard": any(ep.get("noise_reason") == "low_signal_legacy_or_guard" for ep in hidden),
            "hidden_count": len(hidden),
        },
        {
            "name": "same_goal_independent_operations",
            "goal_dual_visible_count": sum(1 for ep in visible if ep.get("goal_id") == "goal_dual"),
        },
        {
            "name": "mixed_legacy_new_flow",
            "has_hidden_legacy": any("legacy" in (ep.get("domains") or []) for ep in hidden),
            "summary_narrative": summary.get("active_goal_narrative"),
        },
        {
            "name": "priority_and_focus",
            "has_primary_episode": any(ep.get("visibility") == "primary" for ep in visible),
            "has_collapsed_or_hidden": any(ep.get("visibility") in {"collapsed", "hidden"} for ep in refined_all),
            "focus_type": summary.get("focus", {}).get("focus_type"),
            "focus_id": summary.get("focus", {}).get("focus_id"),
        },
        {
            "name": "low_confidence_high_priority",
            "has_priority_override": any((ep.get("confidence") or {}).get("label") == "low" and ep.get("priority_score", 0) >= 55 for ep in refined_all),
        },
    ]


if __name__ == "__main__":
    failures = run_decision_harness()
    runtime_results = run_process_harness()
    chained_results = run_chained_regression()
    preview_policy_results = run_preview_policy_regression()
    transition_completion_results = run_transition_and_completion_regression()
    event_query_results = run_event_query_regression()
    trajectory_results = run_trajectory_regression()
    episode_refinement_results = run_episode_refinement_regression()
    print(json.dumps({"runtime_results": runtime_results, "chained_results": chained_results, "preview_policy_results": preview_policy_results, "transition_completion_results": transition_completion_results, "event_query_results": event_query_results, "trajectory_results": trajectory_results, "episode_refinement_results": episode_refinement_results}, ensure_ascii=False, indent=2))
    if failures:
        print(json.dumps({"failures": failures}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
