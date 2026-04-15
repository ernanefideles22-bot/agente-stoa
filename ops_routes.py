from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter


def make_ops_router(brain, config) -> APIRouter:
    router = APIRouter(tags=["ops"])

    @router.get("/api/health")
    async def health():
        return {
            "status": "online",
            "agent": "STOA Quantum Brain",
            "timestamp": datetime.now().isoformat(),
            "location": config.LOCATION,
            "devices_registered": len(brain.device_control.list_devices()),
        }

    @router.get("/status")
    async def status():
        return {"status": "ok"}

    @router.get("/api/events/timeline")
    async def get_execution_timeline(
        goal_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        phase: Optional[str] = None,
        severity: Optional[str] = None,
        event_domain: Optional[str] = None,
        limit: int = 30,
    ):
        from execution_event_query import ExecutionEventQuery
        events = ExecutionEventQuery.query(
            goal_id=goal_id,
            operation_id=operation_id,
            phase=phase,
            severity=severity,
            event_domain=event_domain,
            limit=limit,
        )
        return {
            "items": events,
            "summary": ExecutionEventQuery.summarize(events),
            "filters": {
                "goal_id": goal_id,
                "operation_id": operation_id,
                "phase": phase,
                "severity": severity,
                "event_domain": event_domain,
                "limit": limit,
            },
        }

    @router.get("/api/events/summary")
    async def get_execution_event_summary(
        goal_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        phase: Optional[str] = None,
        severity: Optional[str] = None,
        event_domain: Optional[str] = None,
        limit: int = 100,
    ):
        from execution_event_query import ExecutionEventQuery
        events = ExecutionEventQuery.query(
            goal_id=goal_id,
            operation_id=operation_id,
            phase=phase,
            severity=severity,
            event_domain=event_domain,
            limit=limit,
        )
        return {
            "summary": ExecutionEventQuery.summarize(events),
            "count": len(events),
            "filters": {
                "goal_id": goal_id,
                "operation_id": operation_id,
                "phase": phase,
                "severity": severity,
                "event_domain": event_domain,
                "limit": limit,
            },
        }

    @router.get("/api/events/trajectories")
    async def get_execution_trajectories(
        goal_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        phase: Optional[str] = None,
        severity: Optional[str] = None,
        event_domain: Optional[str] = None,
        visibility: Optional[str] = None,
        limit: int = 50,
    ):
        from trajectory_correlation import TrajectoryCorrelation
        return TrajectoryCorrelation.query_grouped(
            goal_id=goal_id,
            operation_id=operation_id,
            phase=phase,
            severity=severity,
            event_domain=event_domain,
            visibility=visibility,
            limit=limit,
        )

    @router.get("/api/events/operational-summary")
    async def get_operational_trajectory_summary(
        goal_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        phase: Optional[str] = None,
        severity: Optional[str] = None,
        event_domain: Optional[str] = None,
        visibility: Optional[str] = None,
        limit: int = 50,
    ):
        from trajectory_correlation import TrajectoryCorrelation
        grouped = TrajectoryCorrelation.query_grouped(
            goal_id=goal_id,
            operation_id=operation_id,
            phase=phase,
            severity=severity,
            event_domain=event_domain,
            visibility=visibility,
            limit=limit,
        )
        return {
            "summary": grouped.get("summary") or {},
            "episode_count": len(grouped.get("episodes") or []),
            "filters": grouped.get("filters") or {},
        }

    return router
