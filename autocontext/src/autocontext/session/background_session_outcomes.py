from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeAlias
from urllib.parse import quote

from autocontext.session.background_session_events import NormalizedSessionEvent, build_artifact_created_session_event
from autocontext.session.background_session_read_model import BackgroundSessionArtifact

SessionOutcomeKind: TypeAlias = Literal[
    "branch",
    "commit",
    "pull_request",
    "screenshot",
    "report",
    "trace",
    "dataset",
    "verification_result",
]
SessionOutcomeStatus: TypeAlias = Literal["available", "pending", "unavailable"]
SessionOutcomeMetadataValue: TypeAlias = str | int | float | bool
SessionOutcome: TypeAlias = dict[str, Any]

_OUTCOME_KINDS: set[str] = {
    "branch",
    "commit",
    "pull_request",
    "screenshot",
    "report",
    "trace",
    "dataset",
    "verification_result",
}
_OUTCOME_STATUSES: set[str] = {"available", "pending", "unavailable"}


def build_session_outcome(
    *,
    session_id: str,
    kind: SessionOutcomeKind,
    created_at: str,
    outcome_id: str | None = None,
    status: SessionOutcomeStatus = "available",
    title: str = "",
    url: str = "",
    path: str = "",
    ref: str = "",
    sha: str = "",
    summary: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SessionOutcome:
    _assert_outcome_kind(kind)
    _assert_outcome_status(status)
    return {
        "outcome_id": outcome_id or _derive_outcome_id(kind=kind, ref=ref, sha=sha, path=path, url=url, title=title),
        "session_id": session_id,
        "kind": kind,
        "status": status,
        "title": title or _label_for_kind(kind),
        "created_at": created_at,
        "url": url,
        "path": path,
        "ref": ref,
        "sha": sha,
        "summary": summary,
        "metadata": _sanitize_metadata(metadata or {}),
    }


def build_missing_host_capability_outcome(
    *,
    session_id: str,
    kind: SessionOutcomeKind,
    required_capability: str,
    created_at: str,
) -> SessionOutcome:
    _assert_outcome_kind(kind)
    return {
        "outcome_id": f"{kind}:missing:{required_capability}",
        "session_id": session_id,
        "kind": kind,
        "status": "unavailable",
        "title": f"{_label_for_kind(kind)} unavailable",
        "created_at": created_at,
        "url": "",
        "path": "",
        "ref": "",
        "sha": "",
        "summary": f"Host capability {required_capability} is unavailable for {kind} outcomes.",
        "metadata": {
            "reason": "missing_host_capability",
            "required_capability": required_capability,
        },
    }


def session_outcome_to_artifact(outcome: Mapping[str, Any]) -> BackgroundSessionArtifact:
    _assert_available_outcome(outcome, "artifacts")
    return {
        "artifact_id": _read_str(outcome, "outcome_id"),
        "kind": _read_str(outcome, "kind"),
        "label": _read_str(outcome, "title"),
        "path": _read_str(outcome, "path"),
        "url": _read_str(outcome, "url"),
    }


def build_session_outcome_artifact_event(
    outcome: Mapping[str, Any],
    *,
    sequence: int,
    timestamp: str,
) -> NormalizedSessionEvent:
    _assert_available_outcome(outcome, "artifact events")
    return build_artifact_created_session_event(
        session_id=_read_str(outcome, "session_id"),
        sequence=sequence,
        timestamp=timestamp,
        artifact_id=_read_str(outcome, "outcome_id"),
        kind=_read_str(outcome, "kind"),
        label=_read_str(outcome, "title") or None,
        path=_read_str(outcome, "path") or None,
        url=_read_str(outcome, "url") or None,
    )


def _derive_outcome_id(
    *,
    kind: SessionOutcomeKind,
    ref: str,
    sha: str,
    path: str,
    url: str,
    title: str,
) -> str:
    identity = ref or sha or path or url or title or kind
    return f"{kind}:{quote(identity, safe='')}"


def _sanitize_metadata(record: Mapping[str, Any]) -> dict[str, SessionOutcomeMetadataValue]:
    clean: dict[str, SessionOutcomeMetadataValue] = {}
    for key, value in record.items():
        if not isinstance(key, str) or _is_sensitive_key(key):
            continue
        if isinstance(value, str | int | float | bool):
            clean[key] = value
    return clean


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(
        marker in normalized
        for marker in ("secret", "token", "password", "credential", "api_key", "apikey", "private_key")
    )


def _read_str(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    return value if isinstance(value, str) else ""


def _label_for_kind(kind: SessionOutcomeKind) -> str:
    if kind == "branch":
        return "Branch"
    if kind == "commit":
        return "Commit"
    if kind == "pull_request":
        return "Pull request"
    if kind == "screenshot":
        return "Screenshot"
    if kind == "report":
        return "Report"
    if kind == "trace":
        return "Trace"
    if kind == "dataset":
        return "Dataset"
    return "Verification result"


def _assert_available_outcome(outcome: Mapping[str, Any], target: str) -> None:
    kind = _read_str(outcome, "kind")
    status = _read_str(outcome, "status")
    _assert_outcome_kind(kind)
    _assert_outcome_status(status)
    if status != "available":
        raise ValueError(f"Only available session outcomes can be converted to {target}")


def _assert_outcome_kind(kind: str) -> None:
    if kind not in _OUTCOME_KINDS:
        raise ValueError(f"Unsupported session outcome kind: {kind}")


def _assert_outcome_status(status: str) -> None:
    if status not in _OUTCOME_STATUSES:
        raise ValueError(f"Unsupported session outcome status: {status}")
