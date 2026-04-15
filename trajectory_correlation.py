from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from execution_event_query import ExecutionEventQuery


class TrajectoryConfidence:
    @staticmethod
    def score(events: list[dict], episode: dict) -> tuple[float, str]:
        score = 0.0
        if episode.get("goal_id"):
            score += 0.4
        if episode.get("operation_id"):
            score += 0.25
        if episode.get("preview_id"):
            score += 0.15
        if episode.get("step_id"):
            score += 0.1

        domains = {event.get("event_domain") for event in events if event.get("event_domain")}
        if len(domains) >= 2:
            score += 0.05

        non_legacy = [event for event in events if event.get("event_domain") not in {"legacy", "guard", None}]
        if non_legacy:
            score += 0.05

        score = max(0.0, min(1.0, score))
        if score >= 0.75:
            label = "high"
        elif score >= 0.45:
            label = "medium"
        else:
            label = "low"
        return round(score, 2), label


class EpisodeRefinementPolicy:
    MERGE_WINDOW_SECONDS = 900

    @staticmethod
    def _parse_ts(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    @staticmethod
    def should_merge(target: dict, candidate: dict) -> bool:
        if target["trajectory_id"] == candidate["trajectory_id"]:
            return False
        if target.get("goal_id") and candidate.get("goal_id") and target.get("goal_id") == candidate.get("goal_id"):
            if target.get("operation_id") and candidate.get("operation_id") and target.get("operation_id") != candidate.get("operation_id"):
                return False
            return True
        shared_ids = [
            ("operation_id", target.get("operation_id"), candidate.get("operation_id")),
            ("preview_id", target.get("preview_id"), candidate.get("preview_id")),
            ("step_id", target.get("step_id"), candidate.get("step_id")),
        ]
        if any(left and right and left == right for _, left, right in shared_ids):
            return True

        target_ts = EpisodeRefinementPolicy._parse_ts(target.get("latest_timestamp"))
        candidate_ts = EpisodeRefinementPolicy._parse_ts(candidate.get("latest_timestamp"))
        if target_ts and candidate_ts:
            close_in_time = abs((target_ts - candidate_ts).total_seconds()) <= EpisodeRefinementPolicy.MERGE_WINDOW_SECONDS
        else:
            close_in_time = False

        target_domains = set(target.get("domains") or [])
        candidate_domains = set(candidate.get("domains") or [])
        if close_in_time and target.get("goal_id") and not candidate.get("goal_id") and candidate_domains <= {"guard", "legacy"}:
            return True
        if close_in_time and candidate.get("goal_id") and not target.get("goal_id") and target_domains <= {"guard", "legacy"}:
            return True
        return False

    @staticmethod
    def hide_episode(episode: dict) -> tuple[bool, int, str]:
        domains = set(episode.get("domains") or [])
        noise_score = 0
        if domains <= {"guard"}:
            noise_score += 3
        elif domains <= {"legacy"}:
            noise_score += 2
        elif domains <= {"guard", "legacy"}:
            noise_score += 2

        if episode.get("event_count", 0) == 1:
            noise_score += 2
        if not any(episode.get(key) for key in ("goal_id", "operation_id", "preview_id", "step_id")):
            noise_score += 2
        if (episode.get("confidence") or {}).get("label") == "low":
            noise_score += 1

        hidden = noise_score >= 5
        reason = "low_signal_legacy_or_guard" if hidden else "visible"
        return hidden, noise_score, reason


class ActiveGoalNarrativeBuilder:
    @staticmethod
    def build(episodes: list[dict], summary: dict) -> str:
        if not episodes:
            return "Nenhuma trajetória operacional ativa foi correlacionada."
        active = next((episode for episode in episodes if episode.get("goal_id")), episodes[0])
        parts = [
            f"Goal ativo: {active.get('goal_id') or '-'}",
            f"fase dominante: {active.get('dominant_phase') or '-'}",
        ]
        blockers = active.get("blockers_active") or summary.get("blockers_active") or []
        if blockers:
            parts.append(f"bloqueios: {', '.join(blockers)}")
        preview = active.get("last_applicable_preview") or summary.get("last_applicable_preview")
        if preview and preview.get("preview_id"):
            parts.append(f"preview aplicável: {preview['preview_id']} ({preview.get('severity', 'ok')})")
        if "device" in (active.get("domains") or []):
            parts.append("há execução de device correlacionada")
        if active.get("next_unlock_action") or summary.get("next_unlock_action"):
            parts.append(f"próximo destravamento: {active.get('next_unlock_action') or summary.get('next_unlock_action')}")
        confidence = (active.get("confidence") or {}).get("label")
        if confidence:
            parts.append(f"confiança da correlação: {confidence}")
        return " | ".join(parts)


class EpisodePriorityPolicy:
    @staticmethod
    def evaluate(episode: dict) -> tuple[int, str, str, str]:
        score = 0
        reasons = []
        status = episode.get("status")
        blockers = set(episode.get("blockers_active") or [])
        preview = episode.get("last_applicable_preview") or {}
        confidence = (episode.get("confidence") or {}).get("label")
        noise_score = episode.get("noise_score", 0)

        if status in {"goal_failed", "step_failed", "operation_failed"}:
            score += 90
            reasons.append("failure_state")
        elif status == "ready_to_complete":
            score += 70
            reasons.append("ready_to_complete")
        elif blockers:
            score += 65
            reasons.append("active_blockers")
        elif preview.get("preview_id"):
            score += 55
            reasons.append("applicable_preview")
            if preview.get("severity") == "warning":
                score += 10
                reasons.append("preview_warning")

        if episode.get("goal_id"):
            score += 20
            reasons.append("goal_scoped")
        if episode.get("operation_id"):
            score += 10
            reasons.append("operation_scoped")
        if episode.get("event_count", 0) >= 4:
            score += 10
            reasons.append("complex_episode")
        if confidence == "high":
            score += 8
            reasons.append("high_confidence")
        elif confidence == "medium":
            score += 4
            reasons.append("medium_confidence")
        score -= noise_score * 6

        if score >= 85:
            label = "critical"
            visibility = "primary"
        elif score >= 55:
            label = "high"
            visibility = "primary"
        elif score >= 30:
            label = "medium"
            visibility = "secondary"
        elif score >= 10:
            label = "low"
            visibility = "collapsed"
        else:
            label = "low"
            visibility = "hidden"
        return score, label, visibility, ",".join(reasons) or "baseline"


class FocusContext:
    @staticmethod
    def build(episodes: list[dict], summary: dict) -> dict:
        if not episodes:
            return {"focus_type": "none", "focus_id": None, "focus_reason": "no_visible_episodes"}
        primary = [episode for episode in episodes if episode.get("visibility") == "primary"]
        target = primary[0] if primary else episodes[0]
        if target.get("goal_id"):
            return {
                "focus_type": "goal",
                "focus_id": target.get("goal_id"),
                "focus_reason": "dominant_goal_episode",
                "operation_id": target.get("operation_id"),
                "blockers": target.get("blockers_active") or [],
                "next_unlock_action": target.get("next_unlock_action"),
            }
        if target.get("operation_id"):
            return {
                "focus_type": "operation",
                "focus_id": target.get("operation_id"),
                "focus_reason": "dominant_operation_episode",
                "blockers": target.get("blockers_active") or [],
                "next_unlock_action": target.get("next_unlock_action"),
            }
        if summary.get("blockers_active"):
            return {
                "focus_type": "blocker",
                "focus_id": summary.get("blockers_active")[0],
                "focus_reason": "active_blocker",
                "blockers": summary.get("blockers_active") or [],
                "next_unlock_action": summary.get("next_unlock_action"),
            }
        preview = summary.get("last_applicable_preview") or {}
        if preview.get("preview_id"):
            return {
                "focus_type": "preview",
                "focus_id": preview.get("preview_id"),
                "focus_reason": "applicable_preview",
                "next_unlock_action": summary.get("next_unlock_action"),
            }
        return {"focus_type": "trajectory", "focus_id": target.get("trajectory_id"), "focus_reason": "fallback"}


class TrajectoryCorrelation:
    @staticmethod
    def _trajectory_key(event: dict) -> str:
        if event.get("goal_id") and event.get("operation_id"):
            return f"goal:{event['goal_id']}|op:{event['operation_id']}"
        if event.get("goal_id") and event.get("preview_id"):
            return f"goal:{event['goal_id']}|preview:{event['preview_id']}"
        if event.get("goal_id") and event.get("step_id"):
            return f"goal:{event['goal_id']}|step:{event['step_id']}"
        if event.get("goal_id"):
            return f"goal:{event['goal_id']}"
        if event.get("operation_id"):
            return f"operation:{event['operation_id']}"
        if event.get("preview_id"):
            return f"preview:{event['preview_id']}"
        if event.get("step_id"):
            return f"step:{event['step_id']}"
        return f"event:{event.get('event_id') or event.get('timestamp') or 'unknown'}"

    @staticmethod
    def _dominant_phase(events: list[dict]) -> Optional[str]:
        phases = [event.get("phase") or "unknown" for event in events]
        return Counter(phases).most_common(1)[0][0] if phases else None

    @staticmethod
    def _active_blockers(events: list[dict]) -> list[str]:
        blockers = []
        seen = set()
        for event in events:
            metadata = event.get("metadata") or {}
            for blocker in metadata.get("blocker_codes") or []:
                if blocker not in seen:
                    seen.add(blocker)
                    blockers.append(blocker)
            if event.get("reason_code") in {"goal_failed", "step_failed", "operation_failed", "invalid_preview_state"} and event.get("reason_code") not in seen:
                seen.add(event["reason_code"])
                blockers.append(event["reason_code"])
        return blockers

    @staticmethod
    def _latest_applicable_preview(events: list[dict]) -> Optional[dict]:
        for event in events:
            metadata = event.get("metadata") or {}
            if event.get("event_domain") == "preview" and metadata.get("preview_validity_status") == "valid":
                return {
                    "preview_id": event.get("preview_id"),
                    "severity": metadata.get("preview_validity_severity", "ok"),
                    "summary": event.get("summary"),
                    "timestamp": event.get("timestamp"),
                }
        return None

    @staticmethod
    def _next_unlock_action(events: list[dict]) -> Optional[str]:
        for event in events:
            metadata = event.get("metadata") or {}
            if metadata.get("next_unlock_action"):
                return metadata["next_unlock_action"]
        return None

    @staticmethod
    def _trajectory_status(events: list[dict]) -> str:
        codes = {event.get("event_code") for event in events}
        if "goal.failed" in codes:
            return "goal_failed"
        if "step.failed" in codes:
            return "step_failed"
        if "operation.failed" in codes or "validation.failed" in codes:
            return "operation_failed"
        if "device.failed" in codes or "device.timeout_failed" in codes:
            return "operation_failed"
        if "goal.ready_to_complete" in codes:
            return "ready_to_complete"
        if "operation.applied" in codes:
            return "applied"
        if "device.completed" in codes:
            return "applied"
        if "device.dispatched" in codes or "device.retrying" in codes:
            return "executing"
        if "preview.created" in codes:
            return "awaiting_confirmation"
        if "device.confirmation_requested" in codes:
            return "awaiting_confirmation"
        return "observed"

    @staticmethod
    def _episode_from_events(trajectory_id: str, items: list[dict]) -> dict:
        ordered = sorted(items, key=lambda item: item.get("timestamp") or "", reverse=True)
        latest = ordered[0]
        episode = {
            "trajectory_id": trajectory_id,
            "goal_id": latest.get("goal_id"),
            "operation_id": latest.get("operation_id"),
            "preview_id": latest.get("preview_id"),
            "step_id": latest.get("step_id"),
            "status": TrajectoryCorrelation._trajectory_status(ordered),
            "dominant_phase": TrajectoryCorrelation._dominant_phase(ordered),
            "blockers_active": TrajectoryCorrelation._active_blockers(ordered),
            "last_applicable_preview": TrajectoryCorrelation._latest_applicable_preview(ordered),
            "next_unlock_action": TrajectoryCorrelation._next_unlock_action(ordered),
            "latest_summary": latest.get("summary"),
            "latest_timestamp": latest.get("timestamp"),
            "event_count": len(ordered),
            "domains": sorted({event.get("event_domain") or "unknown" for event in ordered}),
            "events": ordered,
        }
        score, label = TrajectoryConfidence.score(ordered, episode)
        episode["confidence"] = {"score": score, "label": label}
        hidden, noise_score, noise_reason = EpisodeRefinementPolicy.hide_episode(episode)
        episode["hidden"] = hidden
        episode["noise_score"] = noise_score
        episode["noise_reason"] = noise_reason
        priority_score, priority_label, visibility, priority_reason = EpisodePriorityPolicy.evaluate(episode)
        episode["priority_score"] = priority_score
        episode["priority_label"] = priority_label
        episode["priority_reason"] = priority_reason
        episode["visibility"] = "hidden" if hidden else visibility
        return episode

    @staticmethod
    def build_episodes(events: list[dict]) -> list[dict]:
        grouped = defaultdict(list)
        for event in events:
            grouped[TrajectoryCorrelation._trajectory_key(event)].append(event)
        episodes = [TrajectoryCorrelation._episode_from_events(trajectory_id, items) for trajectory_id, items in grouped.items()]
        episodes.sort(key=lambda item: item.get("latest_timestamp") or "", reverse=True)
        return episodes

    @staticmethod
    def _merge_episode_data(target: dict, candidate: dict) -> dict:
        merged_events = sorted((target.get("events") or []) + (candidate.get("events") or []), key=lambda item: item.get("timestamp") or "", reverse=True)
        trajectory_id = target.get("trajectory_id")
        if target.get("goal_id") and candidate.get("operation_id"):
            trajectory_id = f"{trajectory_id}+op:{candidate['operation_id']}"
        elif target.get("goal_id") and candidate.get("preview_id"):
            trajectory_id = f"{trajectory_id}+preview:{candidate['preview_id']}"
        return TrajectoryCorrelation._episode_from_events(trajectory_id, merged_events)

    @staticmethod
    def refine_episodes(episodes: list[dict]) -> tuple[list[dict], list[dict]]:
        visible = []
        hidden = []
        consumed = set()

        for index, episode in enumerate(episodes):
            if index in consumed:
                continue
            merged = episode
            for other_index in range(index + 1, len(episodes)):
                if other_index in consumed:
                    continue
                candidate = episodes[other_index]
                if EpisodeRefinementPolicy.should_merge(merged, candidate):
                    merged = TrajectoryCorrelation._merge_episode_data(merged, candidate)
                    consumed.add(other_index)
            hidden_flag, noise_score, noise_reason = EpisodeRefinementPolicy.hide_episode(merged)
            merged["hidden"] = hidden_flag
            merged["noise_score"] = noise_score
            merged["noise_reason"] = noise_reason
            priority_score, priority_label, visibility, priority_reason = EpisodePriorityPolicy.evaluate(merged)
            merged["priority_score"] = priority_score
            merged["priority_label"] = priority_label
            merged["priority_reason"] = priority_reason
            merged["visibility"] = "hidden" if hidden_flag else visibility
            if hidden_flag:
                hidden.append(merged)
            else:
                visible.append(merged)

        visible.sort(key=lambda item: (item.get("priority_score", 0), item.get("latest_timestamp") or ""), reverse=True)
        hidden.sort(key=lambda item: item.get("latest_timestamp") or "", reverse=True)
        return visible, hidden

    @staticmethod
    def _operational_summary(episodes: list[dict], hidden_episodes: list[dict], events: list[dict]) -> dict:
        if not episodes:
            return {
                "goal_current": None,
                "dominant_phase": "idle",
                "blockers_active": [],
                "last_applicable_preview": None,
                "next_unlock_action": None,
                "episode_count": 0,
                "hidden_episode_count": len(hidden_episodes),
                "active_goal_narrative": "Nenhuma trajetória operacional ativa foi correlacionada.",
            }
        latest_episode = episodes[0]
        latest_preview = None
        for episode in episodes:
            if episode.get("last_applicable_preview"):
                latest_preview = episode["last_applicable_preview"]
                break
        blockers = []
        seen = set()
        for episode in episodes:
            for blocker in episode.get("blockers_active") or []:
                if blocker not in seen:
                    seen.add(blocker)
                    blockers.append(blocker)
        summary = {
            "goal_current": latest_episode.get("goal_id"),
            "dominant_phase": latest_episode.get("dominant_phase"),
            "blockers_active": blockers,
            "last_applicable_preview": latest_preview,
            "next_unlock_action": latest_episode.get("next_unlock_action"),
            "episode_count": len(episodes),
            "hidden_episode_count": len(hidden_episodes),
            "latest_operation_id": latest_episode.get("operation_id"),
            "priority_headline": latest_episode.get("priority_label"),
        }
        summary["active_goal_narrative"] = ActiveGoalNarrativeBuilder.build(episodes, summary)
        summary["focus"] = FocusContext.build(episodes, summary)
        return summary

    @staticmethod
    def query_grouped(
        *,
        goal_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        phase: Optional[str] = None,
        severity: Optional[str] = None,
        event_domain: Optional[str] = None,
        visibility: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        events = ExecutionEventQuery.query(
            goal_id=goal_id,
            operation_id=operation_id,
            phase=phase,
            severity=severity,
            event_domain=event_domain,
            limit=limit,
        )
        raw_episodes = TrajectoryCorrelation.build_episodes(events)
        visible_episodes, hidden_episodes = TrajectoryCorrelation.refine_episodes(raw_episodes)
        if visibility:
            visible_episodes = [episode for episode in visible_episodes if episode.get("visibility") == visibility]
        return {
            "episodes": visible_episodes,
            "hidden_episodes": hidden_episodes,
            "summary": TrajectoryCorrelation._operational_summary(visible_episodes, hidden_episodes, events),
            "filters": {
                "goal_id": goal_id,
                "operation_id": operation_id,
                "phase": phase,
                "severity": severity,
                "event_domain": event_domain,
                "visibility": visibility,
                "limit": limit,
            },
        }
