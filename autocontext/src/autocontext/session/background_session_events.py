from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeAlias

from autocontext.session.runtime_events import RuntimeSessionEvent, RuntimeSessionEventLog

NormalizedSessionEventName: TypeAlias = Literal[
    "session_created",
    "session_queued",
    "executor_starting",
    "executor_ready",
    "prompt_queued",
    "prompt_started",
    "runtime_event",
    "artifact_created",
    "child_session_created",
    "session_status",
    "session_completed",
]
NormalizedSessionEventStatus: TypeAlias = Literal["queued", "running", "completed", "failed", "canceled", "skipped", "unknown"]
NormalizedSessionEventSummaryValue: TypeAlias = str | int | float | bool
NormalizedSessionEvent: TypeAlias = dict[str, Any]


def normalize_background_session_timeline(log: RuntimeSessionEventLog) -> list[NormalizedSessionEvent]:
    return [normalize_runtime_session_event(event) for event in sorted(log.events, key=lambda event: event.sequence)]


def normalize_runtime_session_event(event: RuntimeSessionEvent) -> NormalizedSessionEvent:
    if event.event_type == "prompt_submitted":
        return _base_event(
            event,
            normalized_event="prompt_started",
            status="running",
            title="Prompt started",
            payload_summary=_pick_payload(event.payload, {"request_id": "requestId", "role": "role"}),
        )
    if event.event_type == "assistant_message":
        return _base_event(
            event,
            normalized_event="runtime_event",
            status="completed",
            title="Assistant message",
            payload_summary=_pick_payload(event.payload, {"request_id": "requestId", "role": "role"}),
        )
    if event.event_type == "shell_command":
        exit_code = event.payload.get("exitCode")
        return _base_event(
            event,
            normalized_event="runtime_event",
            status="running" if not isinstance(exit_code, int) else "completed" if exit_code == 0 else "failed",
            title="Shell command",
            payload_summary=_pick_payload(event.payload, {"command": "command", "cwd": "cwd", "exit_code": "exitCode"}),
        )
    if event.event_type == "tool_call":
        return _base_event(
            event,
            normalized_event="runtime_event",
            status="failed" if event.payload.get("isError") is True else "completed",
            title="Tool call",
            payload_summary=_pick_payload(event.payload, {"tool": "tool", "name": "name"}),
        )
    if event.event_type == "child_task_started":
        return _base_event(
            event,
            normalized_event="child_session_created",
            status="running",
            title="Child session created",
            payload_summary=_pick_payload(
                event.payload,
                {"child_session_id": "childSessionId", "role": "role", "task_id": "taskId"},
            ),
        )
    if event.event_type == "child_task_completed":
        failed = event.payload.get("isError") is True
        return _base_event(
            event,
            normalized_event="session_status",
            status="failed" if failed else "completed",
            title="Child session failed" if failed else "Child session completed",
            payload_summary=_pick_payload(event.payload, {"task_id": "taskId"}),
        )
    return _base_event(
        event,
        normalized_event="runtime_event",
        status="completed",
        title="Compaction recorded",
        payload_summary=_pick_payload(event.payload, {"summary_artifact_id": "summaryArtifactId"}),
    )


def build_lifecycle_session_event(
    *,
    session_id: str,
    sequence: int,
    timestamp: str,
    hook: str,
    phase: str,
) -> NormalizedSessionEvent:
    failed = phase in {"failed", "timeout"}
    completed = phase == "completed"
    skipped = phase == "skipped"
    normalized_event: NormalizedSessionEventName
    if completed and hook == "start":
        normalized_event = "executor_ready"
    elif failed or skipped:
        normalized_event = "session_status"
    else:
        normalized_event = "executor_starting"
    return {
        "event_id": f"lifecycle:{session_id}:{hook}:{phase}:{sequence}",
        "session_id": session_id,
        "sequence": sequence,
        "ts": timestamp,
        "event": normalized_event,
        "source_event_type": "lifecycle_hook",
        "status": "skipped" if skipped else "failed" if failed else "completed" if completed else "running",
        "title": f"Lifecycle hook {hook} {phase}",
        "payload_summary": {"hook": hook, "phase": phase},
    }


def build_artifact_created_session_event(
    *,
    session_id: str,
    sequence: int,
    timestamp: str,
    artifact_id: str,
    kind: str,
    label: str | None = None,
    url: str | None = None,
    path: str | None = None,
) -> NormalizedSessionEvent:
    return {
        "event_id": f"artifact:{session_id}:{artifact_id}:{sequence}",
        "session_id": session_id,
        "sequence": sequence,
        "ts": timestamp,
        "event": "artifact_created",
        "source_event_type": "artifact",
        "status": "completed",
        "title": "Artifact created",
        "payload_summary": _sanitize_summary(
            {"artifact_id": artifact_id, "kind": kind, "label": label, "path": path, "url": url}
        ),
    }


def build_session_status_event(
    *,
    session_id: str,
    sequence: int,
    timestamp: str,
    status: NormalizedSessionEventStatus,
    reason: str | None = None,
) -> NormalizedSessionEvent:
    terminal = status in {"completed", "failed", "canceled", "skipped"}
    return {
        "event_id": f"status:{session_id}:{status}:{sequence}",
        "session_id": session_id,
        "sequence": sequence,
        "ts": timestamp,
        "event": "session_completed" if terminal else "session_status",
        "source_event_type": "session_status",
        "status": status,
        "title": f"Session {status}",
        "payload_summary": _sanitize_summary({"reason": reason}),
    }


def _base_event(
    event: RuntimeSessionEvent,
    *,
    normalized_event: NormalizedSessionEventName,
    status: NormalizedSessionEventStatus,
    title: str,
    payload_summary: dict[str, NormalizedSessionEventSummaryValue],
) -> NormalizedSessionEvent:
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "sequence": event.sequence,
        "ts": event.timestamp,
        "event": normalized_event,
        "source_event_type": event.event_type.value,
        "status": status,
        "title": title,
        "payload_summary": payload_summary,
    }


def _pick_payload(
    payload: Mapping[str, Any],
    mapping: Mapping[str, str],
) -> dict[str, NormalizedSessionEventSummaryValue]:
    summary: dict[str, NormalizedSessionEventSummaryValue] = {}
    for output_key, input_key in mapping.items():
        value = payload.get(input_key)
        if isinstance(value, str | int | float | bool):
            summary[output_key] = value
    return summary


def _sanitize_summary(value: Mapping[str, Any]) -> dict[str, NormalizedSessionEventSummaryValue]:
    summary: dict[str, NormalizedSessionEventSummaryValue] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str | int | float | bool):
            summary[key] = item
    return summary
