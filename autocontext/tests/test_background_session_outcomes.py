from __future__ import annotations

from autocontext.session.background_session_outcomes import (
    build_missing_host_capability_outcome,
    build_session_outcome,
    build_session_outcome_artifact_event,
    session_outcome_to_artifact,
)

_SESSION_ID = "run:run-123:runtime"
_CREATED_AT = "2026-06-01T00:08:00.000Z"


def test_session_outcomes_serialize_portable_artifact_kinds_without_provider_payloads() -> None:
    outcomes = [
        build_session_outcome(
            session_id=_SESSION_ID,
            kind="branch",
            title="Feature branch",
            ref="feature/ac-785-outcomes",
            url="https://git.example/compare/feature/ac-785-outcomes",
            created_at=_CREATED_AT,
            metadata={"base": "main", "token": "SECRET_VALUE"},
        ),
        build_session_outcome(
            session_id=_SESSION_ID,
            kind="commit",
            title="Implementation commit",
            sha="abc1234",
            url="https://git.example/commit/abc1234",
            created_at=_CREATED_AT,
        ),
        build_session_outcome(
            session_id=_SESSION_ID,
            kind="pull_request",
            title="Review PR",
            ref="42",
            url="https://git.example/pull/42",
            created_at=_CREATED_AT,
            metadata={"provider": "github", "installation_token": "SECRET_VALUE"},
        ),
        build_session_outcome(
            session_id=_SESSION_ID,
            kind="screenshot",
            title="Cockpit screenshot",
            path="artifacts/cockpit.png",
            created_at=_CREATED_AT,
        ),
        build_session_outcome(
            session_id=_SESSION_ID,
            kind="report",
            title="Session report",
            path="reports/session.md",
            summary="Operator-facing run summary",
            created_at=_CREATED_AT,
        ),
        build_session_outcome(
            session_id=_SESSION_ID,
            kind="trace",
            title="Execution trace",
            path="traces/run.jsonl",
            created_at=_CREATED_AT,
        ),
        build_session_outcome(
            session_id=_SESSION_ID,
            kind="dataset",
            title="Failure examples",
            path="datasets/failures.jsonl",
            created_at=_CREATED_AT,
        ),
        build_session_outcome(
            session_id=_SESSION_ID,
            kind="verification_result",
            title="Verification result",
            path="verification/result.json",
            created_at=_CREATED_AT,
            metadata={"passed": True, "failures": 0},
        ),
    ]

    assert outcomes == [
        {
            "outcome_id": "branch:feature%2Fac-785-outcomes",
            "session_id": _SESSION_ID,
            "kind": "branch",
            "status": "available",
            "title": "Feature branch",
            "created_at": _CREATED_AT,
            "url": "https://git.example/compare/feature/ac-785-outcomes",
            "path": "",
            "ref": "feature/ac-785-outcomes",
            "sha": "",
            "summary": "",
            "metadata": {"base": "main"},
        },
        {
            "outcome_id": "commit:abc1234",
            "session_id": _SESSION_ID,
            "kind": "commit",
            "status": "available",
            "title": "Implementation commit",
            "created_at": _CREATED_AT,
            "url": "https://git.example/commit/abc1234",
            "path": "",
            "ref": "",
            "sha": "abc1234",
            "summary": "",
            "metadata": {},
        },
        {
            "outcome_id": "pull_request:42",
            "session_id": _SESSION_ID,
            "kind": "pull_request",
            "status": "available",
            "title": "Review PR",
            "created_at": _CREATED_AT,
            "url": "https://git.example/pull/42",
            "path": "",
            "ref": "42",
            "sha": "",
            "summary": "",
            "metadata": {"provider": "github"},
        },
        {
            "outcome_id": "screenshot:artifacts%2Fcockpit.png",
            "session_id": _SESSION_ID,
            "kind": "screenshot",
            "status": "available",
            "title": "Cockpit screenshot",
            "created_at": _CREATED_AT,
            "url": "",
            "path": "artifacts/cockpit.png",
            "ref": "",
            "sha": "",
            "summary": "",
            "metadata": {},
        },
        {
            "outcome_id": "report:reports%2Fsession.md",
            "session_id": _SESSION_ID,
            "kind": "report",
            "status": "available",
            "title": "Session report",
            "created_at": _CREATED_AT,
            "url": "",
            "path": "reports/session.md",
            "ref": "",
            "sha": "",
            "summary": "Operator-facing run summary",
            "metadata": {},
        },
        {
            "outcome_id": "trace:traces%2Frun.jsonl",
            "session_id": _SESSION_ID,
            "kind": "trace",
            "status": "available",
            "title": "Execution trace",
            "created_at": _CREATED_AT,
            "url": "",
            "path": "traces/run.jsonl",
            "ref": "",
            "sha": "",
            "summary": "",
            "metadata": {},
        },
        {
            "outcome_id": "dataset:datasets%2Ffailures.jsonl",
            "session_id": _SESSION_ID,
            "kind": "dataset",
            "status": "available",
            "title": "Failure examples",
            "created_at": _CREATED_AT,
            "url": "",
            "path": "datasets/failures.jsonl",
            "ref": "",
            "sha": "",
            "summary": "",
            "metadata": {},
        },
        {
            "outcome_id": "verification_result:verification%2Fresult.json",
            "session_id": _SESSION_ID,
            "kind": "verification_result",
            "status": "available",
            "title": "Verification result",
            "created_at": _CREATED_AT,
            "url": "",
            "path": "verification/result.json",
            "ref": "",
            "sha": "",
            "summary": "",
            "metadata": {"failures": 0, "passed": True},
        },
    ]
    assert "SECRET_VALUE" not in str(outcomes)


def test_missing_host_capability_outcome_matches_typescript_contract() -> None:
    assert build_missing_host_capability_outcome(
        session_id=_SESSION_ID,
        kind="pull_request",
        required_capability="hosted_pull_request_creation",
        created_at=_CREATED_AT,
    ) == {
        "outcome_id": "pull_request:missing:hosted_pull_request_creation",
        "session_id": _SESSION_ID,
        "kind": "pull_request",
        "status": "unavailable",
        "title": "Pull request unavailable",
        "created_at": _CREATED_AT,
        "url": "",
        "path": "",
        "ref": "",
        "sha": "",
        "summary": "Host capability hosted_pull_request_creation is unavailable for pull_request outcomes.",
        "metadata": {
            "reason": "missing_host_capability",
            "required_capability": "hosted_pull_request_creation",
        },
    }


def test_session_outcome_artifact_and_event_are_sanitized() -> None:
    report = build_session_outcome(
        session_id=_SESSION_ID,
        kind="report",
        title="Session report",
        path="reports/session.md",
        created_at=_CREATED_AT,
        metadata={"api_key": "SECRET_VALUE"},
    )

    assert session_outcome_to_artifact(report) == {
        "artifact_id": "report:reports%2Fsession.md",
        "kind": "report",
        "label": "Session report",
        "path": "reports/session.md",
        "url": "",
    }

    assert build_session_outcome_artifact_event(
        report,
        sequence=70,
        timestamp="2026-06-01T00:09:00.000Z",
    ) == {
        "event_id": "artifact:run:run-123:runtime:report:reports%2Fsession.md:70",
        "session_id": _SESSION_ID,
        "sequence": 70,
        "ts": "2026-06-01T00:09:00.000Z",
        "event": "artifact_created",
        "source_event_type": "artifact",
        "status": "completed",
        "title": "Artifact created",
        "payload_summary": {
            "artifact_id": "report:reports%2Fsession.md",
            "kind": "report",
            "label": "Session report",
            "path": "reports/session.md",
        },
    }
