from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autocontext.config.settings import AppSettings
from autocontext.server.cockpit_api import cockpit_router
from autocontext.storage.sqlite_store import SQLiteStore

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _make_store(tmp_path: Path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "test.db")
    store.migrate(MIGRATIONS_DIR)
    return store


def _persist_background_sessions(db_path: Path) -> None:
    from autocontext.session.runtime_events import RuntimeSessionEventLog, RuntimeSessionEventStore, RuntimeSessionEventType

    log = RuntimeSessionEventLog.create(
        session_id="run:test-run-1:runtime",
        task_id="task-1",
        worker_id="worker-1",
        metadata={"goal": "autoctx run grid_ctf", "runId": "test-run-1", "status": "running"},
    )
    log.append(
        RuntimeSessionEventType.PROMPT_SUBMITTED,
        {"requestId": "req-1", "role": "competitor", "prompt": "SECRET_VALUE"},
    )
    child = RuntimeSessionEventLog.create(
        session_id="task:run:test-run-1:runtime:child-1",
        parent_session_id="run:test-run-1:runtime",
        task_id="child-1",
        worker_id="worker-child",
        metadata={"goal": "Inspect failing test", "runId": "test-run-1", "status": "completed"},
    )
    store = RuntimeSessionEventStore(db_path)
    try:
        store.save(log)
        store.save(child)
    finally:
        store.close()


@pytest.fixture()
def cockpit_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    store = _make_store(tmp_path)
    settings = AppSettings(
        db_path=tmp_path / "test.db",
        runs_root=tmp_path / "runs",
        knowledge_root=tmp_path / "knowledge",
        skills_root=tmp_path / "skills",
        claude_skills_path=tmp_path / ".claude" / "skills",
        event_stream_path=tmp_path / "runs" / "events.ndjson",
    )

    app = FastAPI()
    app.state.store = store
    app.state.app_settings = settings
    app.include_router(cockpit_router)
    yield {"client": TestClient(app), "settings": settings}


def test_cockpit_lists_background_sessions(cockpit_env: dict[str, Any]) -> None:
    _persist_background_sessions(cockpit_env["settings"].db_path)

    response = cockpit_env["client"].get("/api/cockpit/background-sessions?limit=5")

    assert response.status_code == 200
    assert response.json()["sessions"] == [
        {
            "session_id": "task:run:test-run-1:runtime:child-1",
            "runtime_session_id": "task:run:test-run-1:runtime:child-1",
            "run_id": "test-run-1",
            "task_id": "child-1",
            "parent_session_id": "run:test-run-1:runtime",
            "status": "completed",
            "goal": "Inspect failing test",
            "event_count": 0,
            "artifact_count": 0,
            "child_session_count": 0,
            "created_at": response.json()["sessions"][0]["created_at"],
            "updated_at": response.json()["sessions"][0]["updated_at"],
            "result_url": "/api/cockpit/background-sessions/task%3Arun%3Atest-run-1%3Aruntime%3Achild-1",
            "runtime_session_url": "/api/cockpit/runtime-sessions/task%3Arun%3Atest-run-1%3Aruntime%3Achild-1",
        },
        {
            "session_id": "run:test-run-1:runtime",
            "runtime_session_id": "run:test-run-1:runtime",
            "run_id": "test-run-1",
            "task_id": "task-1",
            "parent_session_id": "",
            "status": "running",
            "goal": "autoctx run grid_ctf",
            "event_count": 1,
            "artifact_count": 0,
            "child_session_count": 1,
            "created_at": response.json()["sessions"][1]["created_at"],
            "updated_at": response.json()["sessions"][1]["updated_at"],
            "result_url": "/api/cockpit/background-sessions/run%3Atest-run-1%3Aruntime",
            "runtime_session_url": "/api/cockpit/runtime-sessions/run%3Atest-run-1%3Aruntime",
        },
    ]


def test_cockpit_reads_background_session_detail(cockpit_env: dict[str, Any]) -> None:
    _persist_background_sessions(cockpit_env["settings"].db_path)
    session_id = quote("run:test-run-1:runtime", safe="")

    response = cockpit_env["client"].get(f"/api/cockpit/background-sessions/{session_id}")

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["summary"]["session_id"] == "run:test-run-1:runtime"
    assert body["child_sessions"][0]["session_id"] == "task:run:test-run-1:runtime:child-1"
    assert body["normalized_events"] == [
        {
            "event_id": body["normalized_events"][0]["event_id"],
            "session_id": "run:test-run-1:runtime",
            "sequence": 0,
            "ts": body["normalized_events"][0]["ts"],
            "event": "prompt_started",
            "source_event_type": "prompt_submitted",
            "status": "running",
            "title": "Prompt started",
            "payload_summary": {"request_id": "req-1", "role": "competitor"},
        }
    ]
    assert "SECRET_VALUE" not in str(body)


def test_cockpit_background_session_validation_and_not_found(cockpit_env: dict[str, Any]) -> None:
    invalid_limit = cockpit_env["client"].get("/api/cockpit/background-sessions?limit=0")
    assert invalid_limit.status_code == 422
    assert invalid_limit.json()["detail"] == "limit must be a positive integer"

    missing = cockpit_env["client"].get("/api/cockpit/background-sessions/missing")
    assert missing.status_code == 404
    assert missing.json()["detail"] == {
        "detail": "Background session 'missing' not found",
        "session_id": "missing",
    }
