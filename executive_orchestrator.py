from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional
from uuid import uuid4
try:
    from stoa_memory import StoaMemory
except Exception:
    StoaMemory = None
try:
    from stoa_guardrail import StoaGuardrail
except Exception:
    StoaGuardrail = None


def _normalized(command: str) -> str:
    return (command or "").strip().lower()


def _contains_any(command: str, terms: list[str]) -> bool:
    return any(term in command for term in terms)


def _is_short_followup(command: str) -> bool:
    return _normalized(command) in {
        "continue",
        "retome isso",
        "próximo passo",
        "proximo passo",
        "use o mesmo arquivo",
        "documente isso também",
        "documente isso tambem",
        "o que falta?",
        "o que falta",
        "o que eu faço agora?",
        "o que eu faço agora",
    }


@dataclass
class IntentDecision:
    name: str
    confidence: str
    signals: list[str]
    requires_mutation: bool = False
    explicit_confirmation: bool = False
    inferred_from_context: bool = False
    ambiguous: bool = False
    hybrid: bool = False


@dataclass
class OperationProfile:
    category: str
    scope: str
    destructive: bool = False
    reversible: bool = True
    mutates_files: bool = False
    requires_context: bool = False
    touches_code: bool = False
    touches_docs: bool = False
    touches_ops: bool = False


@dataclass
class RiskDecision:
    level: str
    reason: str
    requires_preview: bool = False
    flags: list[str] = field(default_factory=list)


@dataclass
class ConfirmationDecision:
    required: bool
    action: str
    reason: str


@dataclass
class TransitionDecision:
    previous_phase: Optional[str]
    next_phase: str
    reason: str
    reason_code: str = "default"
    rule_name: str = "default"
    allowed: bool = True
    allowed_next_phases: list[str] = field(default_factory=list)
    state_changes: dict = field(default_factory=dict)


@dataclass
class PreviewValidityDecision:
    status: str
    severity: str
    can_apply: bool
    reason: str
    invalidation_causes: list[str] = field(default_factory=list)
    recommended_action: str = "none"


@dataclass
class GoalExecutionModel:
    goal_id: Optional[str]
    goal_status: Optional[str]
    current_step_id: Optional[str]
    current_step_status: Optional[str]
    current_operation_id: Optional[str]
    preview_id: Optional[str]
    preview_status: str
    execution_status: str
    linkage_reason: str
    next_unlock_action: str


@dataclass
class GoalProgressDecision:
    total_steps: int
    done_steps: int
    pending_steps: int
    failed_steps: int
    in_progress_steps: int
    progress_ratio: float
    current_step_id: Optional[str]
    current_step_status: Optional[str]


@dataclass
class CompletionDecision:
    can_complete: bool
    reason_code: str
    reason: str
    goal_status_after_completion: str
    progress: GoalProgressDecision


@dataclass
class DecisionExplanation:
    summary: str
    phase_label: str
    blockers: list[str]
    blocker_codes: list[str]
    next_unlock_action: str
    user_message: str
    governance_notes: list[str] = field(default_factory=list)


@dataclass
class ExecutionEvent:
    event_id: str
    event_type: str
    event_code: str
    event_domain: str
    event_subject: str
    event_outcome: str
    severity: str
    phase: str
    goal_id: Optional[str]
    step_id: Optional[str]
    operation_id: Optional[str]
    preview_id: Optional[str]
    reason_code: str
    summary: str
    metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrchestratorDecision:
    decision_id: str
    intent: IntentDecision
    operation_profile: OperationProfile
    mode: str
    risk: RiskDecision
    confirmation: ConfirmationDecision
    effective_command: str
    notes: list[str]
    legacy_mode_hint: str
    forced_mode: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


class IntentClassifier:
    APPLY_TERMS = {"aplique isso", "confirmar", "executar plano", "aplicar patch", "pode aplicar", "agora aplique"}
    CANCEL_TERMS = {"cancelar preview", "descartar plano", "não aplicar", "nao aplicar"}
    PREVIEW_TERMS = ["planeje ", "simule ", "dry run", "mostre o patch", "o que mudaria", "preview "]
    OPS_TERMS = [
        "historico", "histórico", "ultimas operacoes", "últimas operações", "mostrar operacao", "mostrar operação",
        "detalhes da operacao", "detalhes da operação", "status da operacao", "status da operação",
        "saude operacional", "saúde operacional", "metricas", "métricas", "rollbacks", "previews expiraram",
        "arquivos mais mudaram", "funil de preview", "última operação aplicada", "ultima operacao aplicada",
    ]
    PLANNER_TERMS = [
        "organize isso", "monte um plano", "roadmap", "como estruturar esse projeto", "como construir isso",
        "plano para", "continue", "próximo passo", "proximo passo", "o que falta", "retome isso", "essa etapa",
        "marque essa etapa", "o que eu faço agora", "qual o próximo passo real", "qual o proximo passo real",
        "o que está bloqueando", "o que esta bloqueando", "posso concluir isso", "o que falta para concluir",
        "use o mesmo arquivo", "documente isso também", "documente isso tambem",
    ]
    DEV_MUTATION_TERMS = [
        "crie", "adicione", "substitua", "altere", "editar arquivo", "criar arquivo", "substituir bloco",
        "substituir no arquivo", "substituir em arquivo", "renomeie", "renomear", "mova", "mover",
        "delete", "apague", "exclua", "remova", "remove",
    ]
    DEV_SAFE_TERMS = ["listar arquivos", "ler arquivo", "validar arquivo", "validar import", "abrir vscode"]

    @staticmethod
    def classify(command: str, state_snapshot: dict, legacy_mode_hint: str, forced_mode: Optional[str] = None) -> IntentDecision:
        normalized = _normalized(command)
        context_used = bool(state_snapshot.get("contextual_resolution_used"))
        context_fresh = bool(state_snapshot.get("context_fresh"))

        if forced_mode == "dev" and normalized in IntentClassifier.APPLY_TERMS:
            return IntentDecision("apply_preview", "high", ["explicit_apply_confirmation"], explicit_confirmation=True)
        if forced_mode == "dev" and normalized in IntentClassifier.CANCEL_TERMS:
            return IntentDecision("cancel_preview", "high", ["explicit_cancel_confirmation"], explicit_confirmation=True)
        if normalized in IntentClassifier.APPLY_TERMS:
            return IntentDecision("apply_preview", "high", ["explicit_apply_confirmation"], explicit_confirmation=True)
        if normalized in IntentClassifier.CANCEL_TERMS:
            return IntentDecision("cancel_preview", "high", ["explicit_cancel_confirmation"], explicit_confirmation=True)
        if _contains_any(normalized, IntentClassifier.OPS_TERMS):
            return IntentDecision("ops_query", "high", ["ops_keywords"])
        if _contains_any(normalized, IntentClassifier.PREVIEW_TERMS):
            return IntentDecision("preview_change", "high", ["preview_keywords"], inferred_from_context=context_used, hybrid=("readme" in normalized or ".md" in normalized))
        if _contains_any(normalized, IntentClassifier.PLANNER_TERMS):
            signals = ["planner_keywords"]
            if context_used:
                signals.append("contextual_followup")
            return IntentDecision(
                "planner_or_guidance",
                "medium" if context_fresh else "low",
                signals,
                inferred_from_context=context_used,
                ambiguous=_is_short_followup(normalized) and not context_fresh,
            )
        if _contains_any(normalized, IntentClassifier.DEV_SAFE_TERMS):
            return IntentDecision("safe_dev_action", "high", ["dev_safe_keywords"])
        if _contains_any(normalized, IntentClassifier.DEV_MUTATION_TERMS):
            hybrid = ("readme" in normalized or ".md" in normalized or "document" in normalized) and (
                ".py" in normalized or "rota" in normalized or "função" in normalized or "funcao" in normalized or "classe" in normalized
            )
            return IntentDecision(
                "mutation_request",
                "medium",
                ["mutation_keywords"] + (["contextual_mutation"] if context_used else []),
                requires_mutation=True,
                inferred_from_context=context_used,
                ambiguous=(_is_short_followup(normalized) or context_used) and not context_fresh,
                hybrid=hybrid,
            )
        if legacy_mode_hint == "planner":
            return IntentDecision("planner_or_guidance", "low", ["legacy_planner_hint"], inferred_from_context=context_used, ambiguous=not context_fresh and _is_short_followup(normalized))
        return IntentDecision("conversation", "medium", ["fallback_conversation"])


class OperationTaxonomy:
    DESTRUCTIVE_TERMS = ["delete", "apague", "exclua", "remova", "remove", "limpe", "truncate"]
    WORKSPACE_TERMS = ["projeto inteiro", "todo o projeto", "todos os arquivos", "global", "workspace", "repo inteiro"]

    @staticmethod
    def build(intent: IntentDecision, command: str, state_snapshot: dict) -> OperationProfile:
        normalized = _normalized(command)
        file_count = int(state_snapshot.get("working_context_file_count") or 0)
        touches_docs = any(term in normalized for term in ["readme", ".md", "documente", "documentar", "docs"])
        touches_code = any(term in normalized for term in [".py", ".js", ".ts", "rota", "endpoint", "função", "funcao", "classe", "arquivo"])
        destructive = _contains_any(normalized, OperationTaxonomy.DESTRUCTIVE_TERMS)
        requires_context = intent.inferred_from_context or _is_short_followup(normalized)

        if _contains_any(normalized, OperationTaxonomy.WORKSPACE_TERMS):
            scope = "workspace"
        elif intent.hybrid or (" e " in normalized and touches_docs and touches_code):
            scope = "multi_file"
        elif file_count > 1:
            scope = "multi_file"
        elif touches_code or touches_docs or ".py" in normalized or ".md" in normalized:
            scope = "single_file"
        elif state_snapshot.get("active_goal_status"):
            scope = "goal_scoped"
        else:
            scope = "none"

        category = "conversation"
        mutates_files = False
        reversible = True
        if intent.name in {"apply_preview", "cancel_preview"}:
            category = "execution_control"
            mutates_files = intent.name == "apply_preview"
            reversible = intent.name != "apply_preview" or bool(state_snapshot.get("pending_preview_valid"))
        elif intent.name == "preview_change":
            category = "preview"
        elif intent.name == "mutation_request":
            category = "mutation"
            mutates_files = True
            reversible = not destructive
        elif intent.name == "safe_dev_action":
            category = "inspection"
        elif intent.name == "planner_or_guidance":
            category = "planning"
        elif intent.name == "ops_query":
            category = "operations"

        return OperationProfile(category, scope, destructive, reversible, mutates_files, requires_context, touches_code, touches_docs, intent.name == "ops_query")


class RiskPolicy:
    @staticmethod
    def assess(intent: IntentDecision, profile: OperationProfile, state_snapshot: dict) -> RiskDecision:
        flags = []
        if profile.destructive:
            flags.append("destructive")
        if profile.scope in {"multi_file", "workspace"}:
            flags.append("wide_scope")
        if intent.inferred_from_context:
            flags.append("context_inferred")
        if intent.ambiguous:
            flags.append("ambiguous_followup")
        if state_snapshot.get("active_goal_status") == "paused":
            flags.append("goal_paused")
        if state_snapshot.get("has_failed_steps"):
            flags.append("active_goal_has_failed_steps")
        if state_snapshot.get("pending_preview_valid"):
            flags.append("pending_preview_valid")

        if intent.name == "apply_preview":
            if state_snapshot.get("pending_preview_valid"):
                return RiskDecision("high" if {"destructive", "wide_scope"} & set(flags) else "medium", "Há preview pendente pronto para aplicação; a mutação já foi preparada.", False, flags)
            return RiskDecision("low", "Sem preview pendente; o fluxo existente bloqueará o apply.", False, flags)
        if intent.name == "cancel_preview":
            return RiskDecision("low", "Cancelar preview não modifica arquivos.", False, flags)
        if intent.name == "preview_change":
            return RiskDecision("low", "Preview não modifica arquivos e é a trilha segura para mutações.", False, flags)
        if intent.name == "mutation_request":
            if {"goal_paused", "ambiguous_followup", "destructive", "wide_scope"} & set(flags):
                return RiskDecision("high", "Pedido de mutação exige governança forte antes da execução.", True, flags)
            return RiskDecision("medium", "Pedido de mutação controlada que deve passar por preview.", True, flags)
        if intent.name == "safe_dev_action":
            return RiskDecision("low", "Leitura ou validação sem mutação estrutural.", False, flags)
        if intent.name == "planner_or_guidance":
            return RiskDecision("medium" if intent.ambiguous and not state_snapshot.get("context_fresh") else "low", "Continuidade ambígua com contexto fraco." if intent.ambiguous and not state_snapshot.get("context_fresh") else "Planejamento ou guidance sem mutação imediata.", False, flags)
        return RiskDecision("low", "Conversa ou consulta sem mutação operacional.", False, flags)


class ConfirmationPolicy:
    @staticmethod
    def decide(intent: IntentDecision, risk: RiskDecision, profile: OperationProfile, state_snapshot: dict) -> ConfirmationDecision:
        if intent.name == "apply_preview":
            if state_snapshot.get("pending_preview_valid"):
                return ConfirmationDecision(False, "apply_pending_preview", "Há preview válido; aplicar usa o change set armazenado.")
            return ConfirmationDecision(False, "missing_preview", "Não há preview pendente para aplicar.")
        if intent.name == "cancel_preview":
            return ConfirmationDecision(False, "cancel_pending_preview", "Cancelamento é seguro e não muta arquivos.")
        if "goal_paused" in risk.flags and intent.name not in {"ops_query", "conversation"}:
            return ConfirmationDecision(True, "resume_or_confirm_goal", "Há um objetivo pausado; confirme retomada antes de avançar.")
        if intent.name == "mutation_request" and (intent.ambiguous or (profile.requires_context and not state_snapshot.get("context_fresh"))):
            return ConfirmationDecision(True, "clarify_before_mutation", "A mutação depende de contexto insuficiente ou ambíguo.")
        if risk.requires_preview:
            return ConfirmationDecision(True, "preview_before_apply", "Mutação real deve passar por preview antes do apply.")
        return ConfirmationDecision(False, "none", "Nenhuma confirmação extra necessária.")


class ModeRouter:
    @staticmethod
    def route(intent: IntentDecision, confirmation: ConfirmationDecision, legacy_mode_hint: str, forced_mode: Optional[str] = None) -> str:
        if forced_mode:
            return forced_mode
        if confirmation.action in {"clarify_before_mutation", "resume_or_confirm_goal"}:
            return "planner"
        if intent.name in {"apply_preview", "cancel_preview", "safe_dev_action"}:
            return "dev"
        if intent.name == "ops_query":
            return "ops"
        if intent.name == "preview_change":
            return "preview"
        if intent.name == "mutation_request":
            return "preview" if confirmation.action == "preview_before_apply" else "dev"
        if intent.name == "planner_or_guidance":
            return "planner"
        return legacy_mode_hint or "conversation"


class PreviewValidityPolicy:
    @staticmethod
    def assess(decision: OrchestratorDecision, response, state_snapshot: dict, runtime_state: dict) -> PreviewValidityDecision:
        pending = runtime_state.get("pending_preview_status") or {}
        preview = pending.get("preview") or {}
        active_goal = runtime_state.get("active_goal") or {}
        working_context = runtime_state.get("working_context") or {}

        if not pending.get("exists"):
            return PreviewValidityDecision("missing", "soft_invalid", False, "Não há preview pendente armazenado.", ["missing_preview"], "generate_preview")
        if pending.get("expired"):
            return PreviewValidityDecision("expired", "hard_invalid", False, "O preview pendente expirou.", ["preview_expired"], "regenerate_preview")

        causes = []
        preview_goal = (preview.get("goal") or "").strip().lower()
        active_goal_title = (active_goal.get("title") or "").strip().lower()
        if preview_goal and active_goal_title and preview_goal != active_goal_title:
            causes.append("goal_mismatch")
        preview_step_ids = set(preview.get("plan_step_ids") or [])
        active_step_ids = {step.get("id") for step in (active_goal.get("plan_steps") or []) if step.get("id")}
        if preview_step_ids and active_step_ids and not preview_step_ids.intersection(active_step_ids):
            causes.append("step_drift")
        if working_context.get("last_operation_id") and preview.get("operation_id") and working_context.get("last_operation_id") != preview.get("operation_id") and decision.intent.name != "apply_preview":
            causes.append("newer_operation_detected")
        if active_goal.get("status") == "failed":
            causes.append("goal_failed")

        if causes:
            severity = "hard_invalid" if {"goal_mismatch", "step_drift", "goal_failed"} & set(causes) else "soft_invalid"
            action = "replan" if severity == "hard_invalid" else "review_preview"
            return PreviewValidityDecision("invalidated", severity, False, "O preview pendente deixou de ser confiável para aplicação direta.", causes, action)
        can_apply = decision.intent.name == "apply_preview" or decision.confirmation.action == "apply_pending_preview" or pending.get("valid", False)
        warning_causes = []
        if active_goal.get("status") == "paused":
            warning_causes.append("goal_paused")
        if state_snapshot.get("has_failed_steps"):
            warning_causes.append("active_goal_has_failed_steps")
        if decision.operation_profile.scope in {"multi_file", "workspace"}:
            warning_causes.append("wide_scope_preview")
        severity = "warning" if warning_causes else "ok"
        return PreviewValidityDecision(
            "valid",
            severity,
            bool(can_apply),
            "O preview pendente ainda corresponde ao estado operacional atual.",
            warning_causes,
            "apply_preview" if can_apply else "review_preview",
        )


class GoalProgressPolicy:
    @staticmethod
    def evaluate(runtime_state: dict) -> GoalProgressDecision:
        active_goal = runtime_state.get("active_goal") or {}
        plan_steps = active_goal.get("plan_steps") or []
        total_steps = len(plan_steps)
        done_steps = len([step for step in plan_steps if step.get("status") == "done"])
        failed_steps = len([step for step in plan_steps if step.get("status") == "failed"])
        in_progress_steps = len([step for step in plan_steps if step.get("status") == "in_progress"])
        pending_steps = len([step for step in plan_steps if step.get("status") == "pending"])
        current_step = next((step for step in plan_steps if step.get("status") in {"pending", "in_progress", "failed"}), None)
        ratio = (done_steps / total_steps) if total_steps else 0.0
        return GoalProgressDecision(
            total_steps=total_steps,
            done_steps=done_steps,
            pending_steps=pending_steps,
            failed_steps=failed_steps,
            in_progress_steps=in_progress_steps,
            progress_ratio=ratio,
            current_step_id=(current_step or {}).get("id"),
            current_step_status=(current_step or {}).get("status"),
        )


class CompletionPolicy:
    @staticmethod
    def assess(runtime_state: dict, preview_validity: PreviewValidityDecision) -> CompletionDecision:
        active_goal = runtime_state.get("active_goal") or {}
        progress = GoalProgressPolicy.evaluate(runtime_state)

        if not active_goal:
            return CompletionDecision(False, "no_active_goal", "Não há objetivo ativo para concluir.", "none", progress)
        if active_goal.get("status") in {"paused", "failed"}:
            return CompletionDecision(False, f"goal_{active_goal.get('status')}", "O objetivo ativo não está em estado concluível.", active_goal.get("status") or "none", progress)
        if progress.total_steps == 0:
            return CompletionDecision(False, "no_plan_steps", "Não há etapas explícitas suficientes para concluir com segurança.", active_goal.get("status") or "active", progress)
        if progress.failed_steps > 0:
            return CompletionDecision(False, "failed_steps_remaining", "Há etapas falhadas pendentes de resolução.", "failed", progress)
        if progress.pending_steps > 0 or progress.in_progress_steps > 0:
            return CompletionDecision(False, "pending_steps_remaining", "Ainda existem etapas pendentes ou em andamento.", active_goal.get("status") or "active", progress)
        if preview_validity.severity in {"soft_invalid", "hard_invalid"} and runtime_state.get("pending_preview_status", {}).get("exists"):
            return CompletionDecision(False, "invalid_preview_state", "Há um preview inválido associado ao trabalho atual.", active_goal.get("status") or "active", progress)
        return CompletionDecision(True, "all_steps_done", "Todas as etapas relevantes estão concluídas.", "completed", progress)


class StateTransitionModel:
    ALLOWED_TRANSITIONS = {
        "idle": {"conversing", "planning", "awaiting_confirmation", "observing", "awaiting_preview"},
        "conversing": {"conversing", "planning", "observing", "awaiting_confirmation"},
        "planning": {"planning", "clarifying", "awaiting_confirmation", "awaiting_preview", "observing"},
        "clarifying": {"clarifying", "planning", "awaiting_confirmation"},
        "awaiting_preview": {"planning", "awaiting_confirmation", "observing"},
        "awaiting_confirmation": {"applying_preview", "planning", "awaiting_preview", "observing"},
        "applying_preview": {"executing_changes", "validating_changes", "blocked"},
        "executing_changes": {"validating_changes", "ready_to_complete", "planning", "blocked"},
        "validating_changes": {"ready_to_complete", "planning", "blocked"},
        "ready_to_complete": {"planning", "observing", "ready_to_complete"},
        "blocked": {"planning", "clarifying", "awaiting_preview", "observing"},
        "paused": {"planning", "clarifying", "observing", "paused"},
        "observing": {"planning", "conversing", "awaiting_confirmation", "observing"},
    }

    @staticmethod
    def _allowed_next_phases(previous_phase: Optional[str]) -> list[str]:
        return sorted(StateTransitionModel.ALLOWED_TRANSITIONS.get(previous_phase or "idle", []))

    @staticmethod
    def derive(decision: OrchestratorDecision, response, current_state: dict, runtime_state: dict) -> TransitionDecision:
        data = getattr(response, "data", None) or {}
        details = data.get("details") or {}
        status = data.get("status") or "unknown"
        previous_phase = current_state.get("current_phase")
        next_phase = previous_phase or "idle"
        reason = "Nenhuma transição calculada."
        rule_name = "default"

        if data.get("mode") == "preview":
            if status in {"preview_ready", "preview_pending_stored"}:
                next_phase, reason, rule_name = "awaiting_confirmation", "Preview gerado e aguardando apply/cancel.", "preview_stored"
            else:
                next_phase, reason, rule_name = "planning", "Preview não consolidado; fluxo volta para planejamento.", "preview_not_ready"
        elif data.get("mode") == "planner":
            if decision.confirmation.action == "clarify_before_mutation":
                next_phase, reason, rule_name = "clarifying", "Pedido de mutação foi redirecionado para esclarecimento.", "planner_clarify"
            else:
                next_phase, reason, rule_name = "planning", "Plano ou guidance atualizado.", "planner_update"
        elif data.get("mode") == "dev":
            if status == "dev_preview_applied":
                next_phase, reason, rule_name = "applying_preview", "Preview aplicado; a execução entrou na fase de aplicação controlada.", "dev_preview_applied"
            elif status in {"dev_applied", "dev_edit_completed"}:
                next_phase, reason, rule_name = "executing_changes", "Mudanças executadas; o trabalho segue para estabilização.", "dev_executed"
            elif status == "dev_validation_completed":
                next_phase, reason, rule_name = "validating_changes", "Validação concluída; o fluxo está na fase de validação.", "dev_validated"
            elif status in {"dev_apply_failed", "dev_unknown"}:
                next_phase, reason, rule_name = "blocked", "Execução falhou ou ficou inconclusiva.", "dev_failed"
            elif status in {"dev_preview_missing", "dev_preview_expired"}:
                next_phase, reason, rule_name = "awaiting_preview", "É preciso gerar ou renovar preview antes do apply.", "dev_missing_preview"
            elif status == "dev_preview_cancelled":
                pending_steps = runtime_state.get("working_context", {}).get("current_plan_steps") or []
                has_more_work = any(step.get("status") in {"pending", "in_progress", "failed"} for step in pending_steps)
                next_phase, reason, rule_name = (
                    ("awaiting_preview", "Preview cancelado; ainda há trabalho pendente que exige novo preview.", "cancel_with_pending_work")
                    if has_more_work else
                    ("planning", "Preview cancelado; volta ao planejamento.", "cancel_back_to_planning")
                )
        elif data.get("mode") == "ops":
            next_phase, reason, rule_name = "observing", "Consulta operacional.", "ops_observe"
        elif data.get("mode") == "conversation":
            next_phase, reason, rule_name = "conversing", "Interação conversacional.", "conversation"

        active_goal = runtime_state.get("active_goal") or {}
        if active_goal.get("status") == "paused":
            next_phase, reason, rule_name = "paused", "Objetivo ativo está pausado.", "goal_paused"
        elif active_goal.get("status") == "failed" and next_phase not in {"observing", "conversing"}:
            next_phase, reason, rule_name = "blocked", "Objetivo ativo está falhado.", "goal_failed"

        pending_preview_status = runtime_state.get("pending_preview_status") or {}
        working_context = runtime_state.get("working_context") or {}
        next_step = details.get("next_step") or next((step for step in (active_goal.get("plan_steps") or []) if step.get("status") in {"pending", "in_progress", "failed"}), None)
        if next_phase in {"executing_changes", "validating_changes"} and all(step.get("status") == "done" for step in (active_goal.get("plan_steps") or [])) and (active_goal.get("plan_steps") or []):
            next_phase, reason, rule_name = "ready_to_complete", "Todas as etapas relevantes parecem concluídas.", "goal_ready"

        allowed_next_phases = StateTransitionModel._allowed_next_phases(previous_phase)
        allowed = next_phase in allowed_next_phases if allowed_next_phases else True
        if not allowed:
            next_phase, reason, rule_name = "planning", f"Transição {previous_phase or 'idle'} -> {next_phase} não permitida; retornando a planning.", "transition_guard"
            allowed_next_phases = StateTransitionModel._allowed_next_phases(previous_phase)
            allowed = True

        return TransitionDecision(previous_phase, next_phase, reason, rule_name, rule_name, allowed, allowed_next_phases, {
            "active_goal_status": active_goal.get("status"),
            "active_goal_id": active_goal.get("goal_id"),
            "pending_preview_valid": pending_preview_status.get("valid", False),
            "pending_preview_id": (pending_preview_status.get("preview") or {}).get("id"),
            "current_step_index": working_context.get("current_step_index", 0),
            "next_step_id": (next_step or {}).get("id"),
            "next_step_status": (next_step or {}).get("status"),
        })


class GoalExecutionModelBuilder:
    @staticmethod
    def build(decision: OrchestratorDecision, response, runtime_state: dict, transition: TransitionDecision, preview_validity: PreviewValidityDecision) -> GoalExecutionModel:
        data = getattr(response, "data", None) or {}
        details = data.get("details") or {}
        active_goal = runtime_state.get("active_goal") or {}
        working_context = runtime_state.get("working_context") or {}
        pending = runtime_state.get("pending_preview_status") or {}
        preview = pending.get("preview") or {}
        next_step = details.get("next_step") or next((step for step in (active_goal.get("plan_steps") or []) if step.get("status") in {"pending", "in_progress", "failed"}), None)
        operation_id = details.get("operation_id") or details.get("preview_operation_id") or working_context.get("last_operation_id")
        preview_id = details.get("preview_id") or preview.get("id") or working_context.get("last_preview_id")
        linkage_reason = "Preview, operação e objetivo estão correlacionados no estado atual." if preview_id and operation_id else ("Há operação registrada ligada ao objetivo atual." if operation_id else ("Há objetivo ativo com etapas ligadas ao comando atual." if active_goal else "Sem vínculo operacional forte além da decisão corrente."))
        next_unlock_action = preview_validity.recommended_action if preview_validity.recommended_action != "none" else transition.next_phase
        return GoalExecutionModel(active_goal.get("goal_id"), active_goal.get("status"), (next_step or {}).get("id"), (next_step or {}).get("status"), operation_id, preview_id, preview_validity.status, data.get("status") or "unknown", linkage_reason, next_unlock_action)


class DecisionExplanationBuilder:
    PHASE_LABELS = {
        "idle": "Ocioso",
        "conversing": "Conversando",
        "planning": "Planejando",
        "clarifying": "Pedindo clareza",
        "awaiting_preview": "Aguardando preview",
        "awaiting_confirmation": "Aguardando confirmação",
        "applying_preview": "Aplicando preview",
        "executing_changes": "Executando mudanças",
        "validating_changes": "Validando mudanças",
        "ready_to_complete": "Pronto para concluir",
        "blocked": "Bloqueado",
        "paused": "Pausado",
        "observing": "Observando",
    }

    @staticmethod
    def build(
        decision: OrchestratorDecision,
        response,
        transition: TransitionDecision,
        execution_model: GoalExecutionModel,
        preview_validity: PreviewValidityDecision,
        completion: CompletionDecision,
        runtime_state: dict,
    ) -> DecisionExplanation:
        active_goal = runtime_state.get("active_goal") or {}
        blockers = []
        blocker_codes = []
        for flag in decision.risk.flags:
            blocker_codes.append(flag)
            blockers.append({
                "destructive": "Pedido destrutivo requer trilha segura.",
                "wide_scope": "Escopo amplo aumenta risco operacional.",
                "ambiguous_followup": "Continuidade ambígua com contexto fraco.",
                "goal_paused": "Objetivo ativo está pausado.",
                "active_goal_has_failed_steps": "Há etapa falhada no objetivo ativo.",
            }.get(flag, f"Sinal de risco: {flag}."))
        if preview_validity.status in {"expired", "invalidated"}:
            blocker_codes.extend(preview_validity.invalidation_causes or [preview_validity.status])
            blockers.append(preview_validity.reason)
        elif preview_validity.severity == "warning":
            blocker_codes.extend(preview_validity.invalidation_causes or ["preview_warning"])
            blockers.append("O preview continua aplicável, mas exige revisão cuidadosa antes do apply.")
        if active_goal.get("status") == "paused":
            blocker_codes.append("goal_paused")
            blockers.append("Retome o objetivo antes de continuar.")
        if active_goal.get("status") == "failed":
            blocker_codes.append("goal_failed")
            blockers.append("Revisite a etapa falhada ou replaneje.")
        if not completion.can_complete and completion.reason_code not in {"pending_steps_remaining", "all_steps_done"}:
            blocker_codes.append(completion.reason_code)

        governance_notes = []
        if decision.confirmation.action == "preview_before_apply":
            governance_notes.append("A política v3 exigiu preview antes de mutação real.")
        if preview_validity.status == "invalidated":
            governance_notes.append("O preview pendente foi tratado como inválido para evitar apply em estado divergente.")
        if preview_validity.severity == "warning":
            governance_notes.append("O preview pendente segue válido, mas com severidade de atenção.")
        if decision.operation_profile.scope in {"multi_file", "workspace"}:
            governance_notes.append("Escopo multi-arquivo ampliou a governança da decisão.")
        summary = f"Intent={decision.intent.name} | modo={decision.mode} | fase={transition.next_phase} | risco={decision.risk.level} | preview={preview_validity.status}"
        phase_label = DecisionExplanationBuilder.PHASE_LABELS.get(transition.next_phase, transition.next_phase)
        user_message = (
            f"Fase atual: {phase_label}. {transition.reason} "
            f"Validade do preview: {preview_validity.status} ({preview_validity.severity}). "
            f"Próximo destravamento: {execution_model.next_unlock_action}."
        )
        return DecisionExplanation(summary, phase_label, blockers, list(dict.fromkeys(blocker_codes)), execution_model.next_unlock_action, user_message, governance_notes)


class ExecutionEventBuilder:
    @staticmethod
    def _derive_taxonomy(
        decision: OrchestratorDecision,
        response,
        transition: TransitionDecision,
        preview_validity: PreviewValidityDecision,
        completion: CompletionDecision,
        execution_model: GoalExecutionModel,
        explanation: DecisionExplanation,
    ) -> tuple[str, str, str, str, str]:
        response_data = getattr(response, "data", None) or {}
        mode = response_data.get("mode") or decision.mode
        status = response_data.get("status") or "unknown"
        details = response_data.get("details") or {}
        blocker_codes = set(explanation.blocker_codes or [])
        active_goal_status = execution_model.goal_status or details.get("active_goal_status")
        current_step_status = execution_model.current_step_status or details.get("current_step_status")

        if status in {"dev_apply_failed", "changeset_failed", "rollback_failed"}:
            if active_goal_status == "failed":
                return "goal.failed", "goal", "goal", "failed", "goal_failed"
            if current_step_status == "failed" or "active_goal_has_failed_steps" in blocker_codes:
                return "step.failed", "step", "plan_step", "failed", "step_failed"
            return "operation.failed", "operation", "operation", "failed", "operation_failed"
        if status in {"dev_preview_applied", "preview_applied", "changeset_executed", "dev_applied"}:
            return "operation.applied", "operation", "operation", "applied", "operation_applied"
        if status in {"preview_pending_stored", "preview_ready"}:
            return "preview.created", "preview", "preview", "created", "preview_created"
        if status == "dev_preview_cancelled":
            return "preview.cancelled", "preview", "preview", "cancelled", "preview_cancelled"
        if preview_validity.status == "expired":
            return "preview.expired", "preview", "preview", "expired", "preview_expired"
        if preview_validity.status == "invalidated":
            return "preview.invalidated", "preview", "preview", "invalidated", "preview_invalidated"
        if preview_validity.severity == "warning":
            return "preview.warning", "preview", "preview", "warning", "preview_warning"
        if completion.can_complete:
            return "goal.ready_to_complete", "goal", "goal", "ready", "goal_ready_to_complete"
        if transition.rule_name == "transition_guard":
            return "guard.recovered", "guard", "transition", "recovered", "transition_guard_recovery"
        if transition.next_phase == "validating_changes":
            return "validation.running", "validation", "operation", "running", "validation_running"
        if transition.next_phase == "blocked":
            return "guard.blocked", "guard", "transition", "blocked", "transition_blocked"
        if mode == "planner":
            return "step.planned", "step", "plan_step", "planned", "step_planned"
        if mode == "conversation":
            return "conversation.answered", "conversation", "interaction", "answered", "conversation_answered"
        if mode == "ops":
            return "ops.observed", "ops", "history", "observed", "ops_observed"
        return "operation.observed", "operation", "operation", "observed", "operation_observed"

    @staticmethod
    def build(
        decision: OrchestratorDecision,
        response,
        transition: TransitionDecision,
        preview_validity: PreviewValidityDecision,
        completion: CompletionDecision,
        execution_model: GoalExecutionModel,
        explanation: DecisionExplanation,
    ) -> ExecutionEvent:
        response_data = getattr(response, "data", None) or {}
        event_type = f"{response_data.get('mode') or decision.mode}:{response_data.get('status') or 'unknown'}"
        event_code, event_domain, event_subject, event_outcome, default_reason_code = ExecutionEventBuilder._derive_taxonomy(
            decision,
            response,
            transition,
            preview_validity,
            completion,
            execution_model,
            explanation,
        )
        severity = (
            "error" if preview_validity.severity == "hard_invalid" or transition.next_phase == "blocked"
            else "warning" if preview_validity.severity in {"warning", "soft_invalid"}
            else "info"
        )
        reason_code = completion.reason_code if not completion.can_complete else transition.reason_code
        if reason_code in {"default", "", None}:
            reason_code = default_reason_code
        return ExecutionEvent(
            event_id=f"evt_{uuid4().hex[:10]}",
            event_type=event_type,
            event_code=event_code,
            event_domain=event_domain,
            event_subject=event_subject,
            event_outcome=event_outcome,
            severity=severity,
            phase=transition.next_phase,
            goal_id=execution_model.goal_id,
            step_id=execution_model.current_step_id,
            operation_id=execution_model.current_operation_id,
            preview_id=execution_model.preview_id,
            reason_code=reason_code,
            summary=explanation.summary,
            metadata={
                "preview_validity_status": preview_validity.status,
                "preview_validity_severity": preview_validity.severity,
                "completion_reason_code": completion.reason_code,
                "blocker_codes": explanation.blocker_codes,
                "next_unlock_action": explanation.next_unlock_action,
                "event_domain": event_domain,
                "event_subject": event_subject,
                "event_outcome": event_outcome,
            },
        )


class ResponseConsolidator:
    @staticmethod
    def consolidate(response, decision: OrchestratorDecision):
        if not isinstance(getattr(response, "data", None), dict):
            return response
        details = response.data.setdefault("details", {})
        details["orchestration"] = decision.as_dict()
        details["intent"] = decision.intent.name
        details["risk_level"] = decision.risk.level
        details["risk_flags"] = list(decision.risk.flags)
        details["confirmation_action"] = decision.confirmation.action
        details["operation_profile"] = asdict(decision.operation_profile)
        if decision.confirmation.action == "preview_before_apply" and response.data.get("mode") == "preview" and not response.response.startswith("Tratando como preview por segurança."):
            response.response = f"Tratando como preview por segurança.\n\n{response.response}"
        if decision.confirmation.action == "clarify_before_mutation" and response.data.get("mode") == "planner" and not response.response.startswith("Preciso fixar melhor o alvo antes de mutar o projeto."):
            response.response = f"Preciso fixar melhor o alvo antes de mutar o projeto.\n\n{response.response}"
        if decision.confirmation.action == "resume_or_confirm_goal" and response.data.get("mode") == "planner" and not response.response.startswith("Há um objetivo pausado."):
            response.response = f"Há um objetivo pausado.\n\n{response.response}"
        return response


class ExecutiveOrchestrator:
    def __init__(self) -> None:
        try:
            if StoaMemory is None:
                raise RuntimeError("stoa_memory indisponível")
            self.memory = StoaMemory(user_id="default")
        except Exception as e:
            print(f"[STOA MEMORY] Falha ao inicializar: {e}")
            self.memory = None
        try:
            if StoaGuardrail is None:
                raise RuntimeError("stoa_guardrail indisponível")
            self.guardrail = StoaGuardrail()
        except Exception as e:
            print(f"[GUARDRAIL] Falha ao inicializar: {e}")
            self.guardrail = None
        # TODO: O enfileiramento real de ações de device ocorre em main.py; o guardrail de ação é aplicado lá.

    def decide(self, command: str, *, state_snapshot: dict, legacy_mode_hint: str, forced_mode: Optional[str] = None) -> OrchestratorDecision:
        intent = IntentClassifier.classify(command, state_snapshot, legacy_mode_hint, forced_mode=forced_mode)
        operation_profile = OperationTaxonomy.build(intent, command, state_snapshot)
        risk = RiskPolicy.assess(intent, operation_profile, state_snapshot)
        confirmation = ConfirmationPolicy.decide(intent, risk, operation_profile, state_snapshot)
        mode = ModeRouter.route(intent, confirmation, legacy_mode_hint, forced_mode=forced_mode)
        notes = []
        if confirmation.action == "preview_before_apply":
            notes.append("mutation_rerouted_to_preview")
        if confirmation.action == "clarify_before_mutation":
            notes.append("clarify_before_mutation")
        if state_snapshot.get("pending_preview_valid"):
            notes.append("pending_preview_valid")
        if state_snapshot.get("active_goal_status"):
            notes.append(f"active_goal:{state_snapshot.get('active_goal_status')}")
        if operation_profile.scope != "none":
            notes.append(f"scope:{operation_profile.scope}")
        if operation_profile.destructive:
            notes.append("destructive")
        return OrchestratorDecision(f"dec_{uuid4().hex[:10]}", intent, operation_profile, mode, risk, confirmation, command, notes, legacy_mode_hint, forced_mode)

    def derive_transition(self, decision: OrchestratorDecision, response, *, current_state: dict, runtime_state: dict) -> TransitionDecision:
        return StateTransitionModel.derive(decision, response, current_state, runtime_state)

    def assess_preview_validity(self, decision: OrchestratorDecision, response, *, state_snapshot: dict, runtime_state: dict) -> PreviewValidityDecision:
        return PreviewValidityPolicy.assess(decision, response, state_snapshot, runtime_state)

    def build_execution_model(self, decision: OrchestratorDecision, response, *, runtime_state: dict, transition: TransitionDecision, preview_validity: PreviewValidityDecision) -> GoalExecutionModel:
        return GoalExecutionModelBuilder.build(decision, response, runtime_state, transition, preview_validity)

    def build_decision_explanation(self, decision: OrchestratorDecision, response, *, transition: TransitionDecision, execution_model: GoalExecutionModel, preview_validity: PreviewValidityDecision, runtime_state: dict) -> DecisionExplanation:
        completion = self.assess_completion(runtime_state, preview_validity)
        return DecisionExplanationBuilder.build(decision, response, transition, execution_model, preview_validity, completion, runtime_state)

    def assess_completion(self, runtime_state: dict, preview_validity: PreviewValidityDecision) -> CompletionDecision:
        return CompletionPolicy.assess(runtime_state, preview_validity)

    def build_execution_event(
        self,
        decision: OrchestratorDecision,
        response,
        *,
        transition: TransitionDecision,
        preview_validity: PreviewValidityDecision,
        completion: CompletionDecision,
        execution_model: GoalExecutionModel,
        explanation: DecisionExplanation,
    ) -> ExecutionEvent:
        return ExecutionEventBuilder.build(decision, response, transition, preview_validity, completion, execution_model, explanation)
