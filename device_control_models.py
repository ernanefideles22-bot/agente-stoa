from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DevicePlatform(str, Enum):
    WINDOWS = "windows"
    ANDROID = "android"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


class DeviceStatus(str, Enum):
    ONLINE = "online"
    BUSY = "busy"
    STALE = "stale"
    OFFLINE = "offline"


class CapabilityRisk(str, Enum):
    SAFE = "safe"
    SENSITIVE = "sensitive"


class ActionStatus(str, Enum):
    AWAITING_CONFIRMATION = "waiting_confirmation"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "cancelled"


class DeviceCapability(BaseModel):
    capability_id: str
    action_type: str
    title: str
    description: str
    platform: DevicePlatform = DevicePlatform.UNKNOWN
    risk: CapabilityRisk = CapabilityRisk.SAFE
    requires_confirmation: bool = False
    parameters_schema: dict[str, Any] = Field(default_factory=dict)


class DeviceRegistration(BaseModel):
    device_id: str
    device_name: str
    platform: DevicePlatform = DevicePlatform.UNKNOWN
    hostname: Optional[str] = None
    os_version: Optional[str] = None
    agent_version: str = "1.0.0"
    aliases: list[str] = Field(default_factory=list)
    capabilities: list[DeviceCapability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceRecord(BaseModel):
    device_id: str
    device_name: str
    platform: DevicePlatform = DevicePlatform.UNKNOWN
    hostname: Optional[str] = None
    os_version: Optional[str] = None
    agent_version: str = "1.0.0"
    aliases: list[str] = Field(default_factory=list)
    capabilities: list[DeviceCapability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: DeviceStatus = DeviceStatus.ONLINE
    registered_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_seen_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_heartbeat_at: Optional[str] = None
    queue_depth: int = 0
    last_action_id: Optional[str] = None
    current_action_id: Optional[str] = None
    last_result: Optional[dict[str, Any]] = None


class ActionRequest(BaseModel):
    device_id: str
    action_type: str
    target: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    command_text: Optional[str] = None
    requested_by: str = "stoa_core"
    confirmed: bool = False
    reason: Optional[str] = None


class ActionEnvelope(BaseModel):
    action_id: str
    device_id: str
    action_type: str
    target: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    command_text: Optional[str] = None
    requested_by: str = "stoa_core"
    goal_id: Optional[str] = None
    context_key: Optional[str] = None
    risk: CapabilityRisk = CapabilityRisk.SAFE
    requires_confirmation: bool = False
    status: ActionStatus = ActionStatus.QUEUED
    summary: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    dispatched_at: Optional[str] = None
    completed_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    confirmation_reason: Optional[str] = None
    confirmation_expires_at: Optional[str] = None
    confirmation_prompt: Optional[str] = None
    timeout_seconds: int = 30
    retry_count: int = 0
    max_retries: int = 0
    retryable: bool = False
    terminal_failure: bool = False
    last_error: Optional[str] = None
    last_error_code: Optional[str] = None
    terminal_reason_code: Optional[str] = None
    result: Optional[dict[str, Any]] = None


class ActionResult(BaseModel):
    action_id: str
    device_id: str
    success: bool
    status: ActionStatus
    output: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    artifacts: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceHeartbeat(BaseModel):
    device_id: str
    status: DeviceStatus = DeviceStatus.ONLINE
    current_action_id: Optional[str] = None
    last_result: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
