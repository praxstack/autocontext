from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from autocontext.analytics.artifact_rendering import render_scenario_curation_html, scenario_curation_view_from_artifacts
from autocontext.consultation.runner import ConsultationRunner
from autocontext.consultation.types import ConsultationRequest as ConsReq
from autocontext.consultation.types import ConsultationTrigger
from autocontext.knowledge.context_selection_report import build_context_selection_report
from autocontext.notebook.context_provider import NotebookContextProvider
from autocontext.notebook.types import SessionNotebook
from autocontext.providers.base import LLMProvider
from autocontext.providers.registry import create_provider
from autocontext.providers.retry import RetryProvider
from autocontext.server.changelog import build_changelog
from autocontext.server.writeup import generate_writeup, generate_writeup_html
from autocontext.session.background_session_events import normalize_background_session_timeline
from autocontext.session.background_session_read_model import build_background_session_detail, build_background_session_summary
from autocontext.session.runtime_events import RuntimeSessionEventLog, RuntimeSessionEventStore
from autocontext.session.runtime_session_ids import runtime_session_id_for_run
from autocontext.session.runtime_session_read_model import (
    RuntimeSessionSummary,
    read_runtime_session_by_id,
    read_runtime_session_by_run_id,
    read_runtime_session_summaries,
    summarize_runtime_session,
)
from autocontext.session.runtime_session_timeline import (
    read_runtime_session_timeline_by_id,
    read_runtime_session_timeline_by_run_id,
)
from autocontext.storage import ArtifactStore, SQLiteStore, artifact_store_from_settings
from autocontext.storage.context_selection_store import load_context_selection_decisions
from autocontext.storage.scenario_paths import normalize_scenario_name_segment

logger = logging.getLogger(__name__)

cockpit_router = APIRouter(prefix="/api/cockpit", tags=["cockpit"])
_NOTEBOOK_CONTEXT_PROVIDER = NotebookContextProvider()


def _get_store(request: Request) -> SQLiteStore:
    store = getattr(request.app.state, "store", None)
    if not isinstance(store, SQLiteStore):
        raise HTTPException(status_code=500, detail="Application store is not configured")
    return store


def _get_artifacts(request: Request) -> ArtifactStore:
    settings = getattr(request.app.state, "app_settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="Application settings are not configured")
    return artifact_store_from_settings(settings)


def _build_effective_notebook_preview(
    store: SQLiteStore,
    session_id: str,
) -> dict[str, Any] | None:
    notebook_row = store.get_notebook(session_id)
    if notebook_row is None:
        return None
    notebook = SessionNotebook.from_dict(notebook_row)
    current_best_score = store.get_run_best_score(session_id)
    return _NOTEBOOK_CONTEXT_PROVIDER.build_effective_preview(
        notebook,
        current_best_score=current_best_score,
    ).to_dict()


def _get_runtime_session_store(request: Request) -> RuntimeSessionEventStore:
    settings = getattr(request.app.state, "app_settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="Application settings are not configured")
    return RuntimeSessionEventStore(settings.db_path)


def _runtime_session_url_for_run(run_id: str) -> str:
    return f"/api/cockpit/runs/{quote(run_id, safe='')}/runtime-session"


def _runtime_session_discovery(
    runtime_store: RuntimeSessionEventStore,
    run_id: str,
) -> dict[str, RuntimeSessionSummary | str | None]:
    log = read_runtime_session_by_run_id(runtime_store, run_id)
    return {
        "runtime_session": summarize_runtime_session(log) if log is not None else None,
        "runtime_session_url": _runtime_session_url_for_run(run_id),
    }


def _runtime_session_not_found(message: str, session_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"detail": message, "session_id": session_id})


def _background_session_not_found(message: str, session_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"detail": message, "session_id": session_id})


def _background_session_summary(
    runtime_store: RuntimeSessionEventStore,
    runtime_session: RuntimeSessionEventLog,
    store: SQLiteStore,
    task_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str | int]:
    task = _task_for_runtime_session(store, runtime_session, task_index)
    return build_background_session_summary(
        runtime_session=runtime_session,
        task=task,
        run=_run_for_runtime_session(store, runtime_session, task),
        child_sessions=runtime_store.list_children(runtime_session.session_id),
    )


def _task_for_runtime_session(
    store: SQLiteStore,
    runtime_session: RuntimeSessionEventLog,
    task_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not runtime_session.task_id:
        return None
    if task_index is not None and runtime_session.task_id in task_index:
        return task_index[runtime_session.task_id]
    return store.get_task(runtime_session.task_id)


def _run_for_runtime_session(
    store: SQLiteStore,
    runtime_session: RuntimeSessionEventLog,
    task: dict[str, Any] | None,
) -> dict[str, Any] | None:
    run_id = _read_str(runtime_session.metadata.get("runId")) or _run_id_from_task(task)
    return store.get_run(run_id) if run_id else None


def _run_id_from_task(task: dict[str, Any] | None) -> str:
    if not task:
        return ""
    config_json = task.get("config_json")
    if not isinstance(config_json, str) or not config_json:
        return ""
    try:
        parsed = json.loads(config_json)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    return _read_str(parsed.get("run_id")) or _read_str(parsed.get("runId"))


def _read_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _task_id_from_background_session_id(session_id: str) -> str:
    return session_id.removeprefix("task:") if session_id.startswith("task:") else ""


def _sort_background_session_summaries(summaries: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    ordered = list(summaries)
    ordered.sort(key=lambda summary: str(summary.get("session_id", "")))
    ordered.sort(key=lambda summary: str(summary.get("created_at", "")), reverse=True)
    ordered.sort(
        key=lambda summary: str(summary.get("updated_at") or summary.get("created_at") or ""),
        reverse=True,
    )
    return ordered


class NotebookUpdateBody(BaseModel):
    """Request body for creating or updating a cockpit notebook."""

    scenario_name: str | None = None
    current_objective: str | None = None
    current_hypotheses: list[str] | None = None
    best_run_id: str | None = None
    best_generation: int | None = None
    best_score: float | None = None
    unresolved_questions: list[str] | None = None
    operator_observations: list[str] | None = None
    follow_ups: list[str] | None = None


def _emit_cockpit_notebook_event(request: Request, session_id: str, scenario_name: str) -> None:
    """Emit notebook_updated event with cockpit source if event stream is configured."""
    settings = getattr(request.app.state, "app_settings", None)
    if settings is None:
        return
    event_path: Path = settings.event_stream_path
    event_path.parent.mkdir(parents=True, exist_ok=True)
    from autocontext.loop.events import EventStreamEmitter

    emitter = EventStreamEmitter(event_path)
    emitter.emit(
        "notebook_updated",
        {"session_id": session_id, "scenario_name": scenario_name, "source": "cockpit"},
        channel="cockpit",
    )


# ---------------------------------------------------------------------------
# Notebook endpoints (cockpit context)
# ---------------------------------------------------------------------------


@cockpit_router.get("/notebooks")
def cockpit_list_notebooks(request: Request) -> list[dict[str, Any]]:
    """List all session notebooks from cockpit."""
    store = _get_store(request)
    return store.list_notebooks()


@cockpit_router.get("/notebooks/{session_id}")
def cockpit_get_notebook(session_id: str, request: Request) -> dict[str, Any]:
    """Get a specific notebook from cockpit."""
    store = _get_store(request)
    nb = store.get_notebook(session_id)
    if nb is None:
        raise HTTPException(status_code=404, detail=f"Notebook not found: {session_id}")
    return nb


@cockpit_router.get("/notebooks/{session_id}/effective-context")
def cockpit_get_effective_notebook_context(session_id: str, request: Request) -> dict[str, Any]:
    """Preview the notebook context that would be injected into runtime prompts."""
    store = _get_store(request)
    preview = _build_effective_notebook_preview(store, session_id)
    if preview is None:
        raise HTTPException(status_code=404, detail=f"Notebook not found: {session_id}")
    return preview


@cockpit_router.put("/notebooks/{session_id}")
def cockpit_update_notebook(session_id: str, body: NotebookUpdateBody, request: Request) -> dict[str, Any]:
    """Create or update a notebook from cockpit context."""
    store = _get_store(request)
    # Require scenario_name on creation
    existing = store.get_notebook(session_id)
    scenario_name = body.scenario_name or (str(existing["scenario_name"]) if existing else None)
    if not scenario_name:
        raise HTTPException(status_code=400, detail="scenario_name required when creating a notebook")

    store.upsert_notebook(
        session_id=session_id,
        scenario_name=scenario_name,
        current_objective=body.current_objective,
        current_hypotheses=body.current_hypotheses,
        best_run_id=body.best_run_id,
        best_generation=body.best_generation,
        best_score=body.best_score,
        unresolved_questions=body.unresolved_questions,
        operator_observations=body.operator_observations,
        follow_ups=body.follow_ups,
    )
    # Sync to filesystem
    nb = store.get_notebook(session_id)
    if nb is not None:
        artifacts = _get_artifacts(request)
        artifacts.write_notebook(session_id, nb)

    # Emit event
    _emit_cockpit_notebook_event(request, session_id, scenario_name)

    return nb or {"session_id": session_id}


@cockpit_router.delete("/notebooks/{session_id}")
def cockpit_delete_notebook(session_id: str, request: Request) -> dict[str, str]:
    """Delete a notebook from cockpit."""
    store = _get_store(request)
    existing = store.get_notebook(session_id)
    scenario_name = str(existing["scenario_name"]) if existing is not None else ""
    deleted = store.delete_notebook(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Notebook not found: {session_id}")
    artifacts = _get_artifacts(request)
    artifacts.delete_notebook(session_id)
    if scenario_name:
        settings = getattr(request.app.state, "app_settings", None)
        if settings is not None:
            event_path: Path = settings.event_stream_path
            event_path.parent.mkdir(parents=True, exist_ok=True)
            from autocontext.loop.events import EventStreamEmitter

            emitter = EventStreamEmitter(event_path)
            emitter.emit(
                "notebook_deleted",
                {"session_id": session_id, "scenario_name": scenario_name, "source": "cockpit"},
                channel="cockpit",
            )
    return {"status": "deleted", "session_id": session_id}


# ---------------------------------------------------------------------------
# Background-session endpoints (operator-facing read model)
# ---------------------------------------------------------------------------


@cockpit_router.get("/background-sessions")
def list_background_sessions(request: Request, limit: int = 50) -> dict[str, Any]:
    """List operator-facing background-session summaries."""
    if limit <= 0:
        raise HTTPException(status_code=422, detail="limit must be a positive integer")
    store = _get_store(request)
    runtime_store = _get_runtime_session_store(request)
    try:
        runtime_sessions = runtime_store.list(limit=limit)
        tasks = store.list_tasks(limit=limit)
        task_index = {str(task["id"]): task for task in tasks if isinstance(task.get("id"), str)}
        runtime_task_ids = {runtime_session.task_id for runtime_session in runtime_sessions if runtime_session.task_id}
        summaries = [
            _background_session_summary(runtime_store, runtime_session, store, task_index)
            for runtime_session in runtime_sessions
        ]
        summaries.extend(
            build_background_session_summary(task=task)
            for task in tasks
            if isinstance(task.get("id"), str) and task["id"] not in runtime_task_ids
        )
        return {"sessions": _sort_background_session_summaries(summaries)[:limit]}
    finally:
        runtime_store.close()


@cockpit_router.get("/background-sessions/{session_id}")
def get_background_session(session_id: str, request: Request) -> dict[str, Any]:
    """Read an operator-facing background-session detail by session id."""
    clean_session_id = session_id.strip()
    if not clean_session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    store = _get_store(request)
    runtime_store = _get_runtime_session_store(request)
    try:
        log = read_runtime_session_by_id(runtime_store, clean_session_id)
        if log is not None:
            task = _task_for_runtime_session(store, log)
            return {
                **build_background_session_detail(
                    runtime_session=log,
                    task=task,
                    run=_run_for_runtime_session(store, log, task),
                    child_sessions=runtime_store.list_children(log.session_id),
                ),
                "normalized_events": normalize_background_session_timeline(log),
            }
        task_id = _task_id_from_background_session_id(clean_session_id)
        task = store.get_task(task_id) if task_id else None
        if task is not None:
            return {**build_background_session_detail(task=task), "normalized_events": []}
        raise _background_session_not_found(
            f"Background session '{clean_session_id}' not found",
            clean_session_id,
        )
    finally:
        runtime_store.close()


# ---------------------------------------------------------------------------
# Runtime-session endpoints (provider runtime observability)
# ---------------------------------------------------------------------------


@cockpit_router.get("/runtime-sessions")
def list_runtime_sessions(request: Request, limit: int = 50) -> dict[str, Any]:
    """List recorded runtime-session event logs."""
    if limit <= 0:
        raise HTTPException(status_code=422, detail="limit must be a positive integer")
    runtime_store = _get_runtime_session_store(request)
    try:
        return {"sessions": read_runtime_session_summaries(runtime_store, limit=limit)}
    finally:
        runtime_store.close()


@cockpit_router.get("/runtime-sessions/{session_id}/timeline")
def get_runtime_session_timeline(session_id: str, request: Request) -> dict[str, Any]:
    """Read an operator-facing runtime-session timeline by session id."""
    clean_session_id = session_id.strip()
    if not clean_session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    runtime_store = _get_runtime_session_store(request)
    try:
        timeline = read_runtime_session_timeline_by_id(runtime_store, clean_session_id)
        if timeline is None:
            raise _runtime_session_not_found(
                f"Runtime session timeline '{clean_session_id}' not found",
                clean_session_id,
            )
        return timeline
    finally:
        runtime_store.close()


@cockpit_router.get("/runtime-sessions/{session_id}")
def get_runtime_session(session_id: str, request: Request) -> dict[str, Any]:
    """Read a recorded runtime-session event log by session id."""
    clean_session_id = session_id.strip()
    if not clean_session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    runtime_store = _get_runtime_session_store(request)
    try:
        log = read_runtime_session_by_id(runtime_store, clean_session_id)
        if log is None:
            raise _runtime_session_not_found(
                f"Runtime session '{clean_session_id}' not found",
                clean_session_id,
            )
        return log.to_dict()
    finally:
        runtime_store.close()


@cockpit_router.get("/runs/{run_id}/runtime-session/timeline")
def get_run_runtime_session_timeline(run_id: str, request: Request) -> dict[str, Any]:
    """Resolve a run id to its runtime-session timeline."""
    clean_run_id = run_id.strip()
    if not clean_run_id:
        raise HTTPException(status_code=422, detail="run_id is required")
    resolved_session_id = runtime_session_id_for_run(clean_run_id)
    runtime_store = _get_runtime_session_store(request)
    try:
        timeline = read_runtime_session_timeline_by_run_id(runtime_store, clean_run_id)
        if timeline is None:
            raise _runtime_session_not_found(
                f"Runtime session timeline for run '{clean_run_id}' not found",
                resolved_session_id,
            )
        return timeline
    finally:
        runtime_store.close()


@cockpit_router.get("/runs/{run_id}/runtime-session")
def get_run_runtime_session(run_id: str, request: Request) -> dict[str, Any]:
    """Resolve a run id to its runtime-session event log."""
    clean_run_id = run_id.strip()
    if not clean_run_id:
        raise HTTPException(status_code=422, detail="run_id is required")
    resolved_session_id = runtime_session_id_for_run(clean_run_id)
    runtime_store = _get_runtime_session_store(request)
    try:
        log = read_runtime_session_by_run_id(runtime_store, clean_run_id)
        if log is None:
            raise _runtime_session_not_found(
                f"Runtime session for run '{clean_run_id}' not found",
                resolved_session_id,
            )
        return log.to_dict()
    finally:
        runtime_store.close()


# ---------------------------------------------------------------------------
# Run endpoints (read-only)
# ---------------------------------------------------------------------------


@cockpit_router.get("/runs")
def list_runs(request: Request) -> list[dict[str, Any]]:
    """List recent runs with summary info."""
    store = _get_store(request)
    runs = store.list_runs(limit=50)
    runtime_store = _get_runtime_session_store(request)

    result: list[dict[str, Any]] = []
    try:
        for run_dict in runs:
            run_id = run_dict["run_id"]
            scenario = run_dict["scenario"]

            # Get generation summary
            with store.connect() as conn:
                gen_rows = conn.execute(
                    "SELECT generation_index, best_score, elo, duration_seconds "
                    "FROM generations WHERE run_id = ? ORDER BY generation_index",
                    (run_id,),
                ).fetchall()

            generations_completed = len(gen_rows)
            best_score = max((g["best_score"] for g in gen_rows), default=0.0)
            best_elo = max((g["elo"] for g in gen_rows), default=0.0)
            total_duration = sum(g["duration_seconds"] or 0.0 for g in gen_rows)

            result.append(
                {
                    "run_id": run_id,
                    "scenario_name": scenario,
                    "generations_completed": generations_completed,
                    "best_score": best_score,
                    "best_elo": best_elo,
                    "status": run_dict["status"],
                    "created_at": run_dict["created_at"],
                    "duration_seconds": round(total_duration, 1),
                    **_runtime_session_discovery(runtime_store, run_id),
                }
            )
    finally:
        runtime_store.close()

    return result


@cockpit_router.get("/runs/{run_id}/status")
def run_status(run_id: str, request: Request) -> dict[str, Any]:
    """Detailed run status with generation-level breakdown."""
    store = _get_store(request)

    with store.connect() as conn:
        run_row = conn.execute(
            "SELECT run_id, scenario, target_generations, status, created_at FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    if not run_row:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run_dict = dict(run_row)

    with store.connect() as conn:
        gen_rows = conn.execute(
            "SELECT generation_index, mean_score, best_score, elo, wins, losses, "
            "gate_decision, status, duration_seconds "
            "FROM generations WHERE run_id = ? ORDER BY generation_index ASC",
            (run_id,),
        ).fetchall()

    generations = []
    for g in gen_rows:
        gd = dict(g)
        generations.append(
            {
                "generation": gd["generation_index"],
                "mean_score": gd["mean_score"],
                "best_score": gd["best_score"],
                "elo": gd["elo"],
                "wins": gd["wins"],
                "losses": gd["losses"],
                "gate_decision": gd["gate_decision"],
                "status": gd["status"],
                "duration_seconds": gd["duration_seconds"],
            }
        )

    runtime_store = _get_runtime_session_store(request)
    try:
        runtime_session_discovery = _runtime_session_discovery(runtime_store, run_id)
    finally:
        runtime_store.close()

    return {
        "run_id": run_id,
        "scenario_name": run_dict["scenario"],
        "target_generations": run_dict["target_generations"],
        "status": run_dict["status"],
        "created_at": run_dict["created_at"],
        "generations": generations,
        **runtime_session_discovery,
    }


@cockpit_router.get("/runs/{run_id}/context-selection")
def run_context_selection_report(run_id: str, request: Request) -> dict[str, Any]:
    """Context-selection telemetry report for cockpit inspection."""
    settings = getattr(request.app.state, "app_settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="Application settings are not configured")
    clean_run_id = run_id.strip()
    if not clean_run_id:
        raise HTTPException(status_code=422, detail="run_id is required")
    try:
        decisions = load_context_selection_decisions(settings.runs_root, clean_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not decisions:
        raise HTTPException(status_code=404, detail=f"No context selection artifacts found for run '{clean_run_id}'")
    return build_context_selection_report(decisions).to_dict()


@cockpit_router.get("/runs/{run_id}/changelog")
def changelog(run_id: str, request: Request) -> dict[str, Any]:
    """What changed between consecutive generations."""
    store = _get_store(request)
    artifacts = _get_artifacts(request)
    return build_changelog(run_id, store, artifacts)


@cockpit_router.get("/runs/{run_id}/compare/{gen_a}/{gen_b}")
def compare_generations(run_id: str, gen_a: int, gen_b: int, request: Request) -> dict[str, Any]:
    """Compare two generations side-by-side."""
    store = _get_store(request)

    with store.connect() as conn:
        row_a = conn.execute(
            "SELECT generation_index, mean_score, best_score, elo, gate_decision "
            "FROM generations WHERE run_id = ? AND generation_index = ?",
            (run_id, gen_a),
        ).fetchone()
        row_b = conn.execute(
            "SELECT generation_index, mean_score, best_score, elo, gate_decision "
            "FROM generations WHERE run_id = ? AND generation_index = ?",
            (run_id, gen_b),
        ).fetchone()

    if not row_a:
        raise HTTPException(status_code=404, detail=f"Generation {gen_a} not found for run '{run_id}'")
    if not row_b:
        raise HTTPException(status_code=404, detail=f"Generation {gen_b} not found for run '{run_id}'")

    da = dict(row_a)
    db = dict(row_b)

    return {
        "gen_a": {
            "generation": da["generation_index"],
            "mean_score": da["mean_score"],
            "best_score": da["best_score"],
            "elo": da["elo"],
            "gate_decision": da["gate_decision"],
        },
        "gen_b": {
            "generation": db["generation_index"],
            "mean_score": db["mean_score"],
            "best_score": db["best_score"],
            "elo": db["elo"],
            "gate_decision": db["gate_decision"],
        },
        "score_delta": round(db["best_score"] - da["best_score"], 6),
        "elo_delta": round(db["elo"] - da["elo"], 6),
    }


@cockpit_router.get("/runs/{run_id}/resume")
def resume_info(run_id: str, request: Request) -> dict[str, Any]:
    """Resume affordances for a run."""
    store = _get_store(request)

    with store.connect() as conn:
        run_row = conn.execute(
            "SELECT run_id, scenario, target_generations, status FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    if not run_row:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run_dict = dict(run_row)
    status = run_dict["status"]
    target = run_dict["target_generations"]

    with store.connect() as conn:
        gen_rows = conn.execute(
            "SELECT generation_index, gate_decision FROM generations WHERE run_id = ? ORDER BY generation_index DESC LIMIT 1",
            (run_id,),
        ).fetchall()

    last_gen = gen_rows[0]["generation_index"] if gen_rows else 0
    last_gate = gen_rows[0]["gate_decision"] if gen_rows else ""

    can_resume = status == "running" and last_gen < target
    if status == "completed":
        hint = "Run completed successfully. Start a new run to continue exploration."
    elif status == "running" and last_gen >= target:
        hint = "All target generations completed. Mark as complete or increase target."
        can_resume = False
    elif status == "running":
        hint = f"Run in progress. Resume from generation {last_gen + 1}."
    else:
        hint = f"Run status is '{status}'."

    notebook_preview = _build_effective_notebook_preview(store, run_id)
    runtime_store = _get_runtime_session_store(request)
    try:
        runtime_session_discovery = _runtime_session_discovery(runtime_store, run_id)
    finally:
        runtime_store.close()

    return {
        "run_id": run_id,
        "status": status,
        "last_generation": last_gen,
        "last_gate_decision": last_gate,
        "can_resume": can_resume,
        "resume_hint": hint,
        "effective_notebook_context": notebook_preview,
        **runtime_session_discovery,
    }


@cockpit_router.get("/writeup/{run_id}")
def writeup(run_id: str, request: Request) -> dict[str, Any]:
    """Lightweight writeup assembled from existing artifacts."""
    store = _get_store(request)
    artifacts = _get_artifacts(request)

    with store.connect() as conn:
        run_row = conn.execute(
            "SELECT run_id, scenario FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    if not run_row:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run_dict = dict(run_row)
    md = generate_writeup(run_id, store, artifacts)
    html = generate_writeup_html(run_id, store, artifacts)
    html_path = artifacts.write_run_writeup_html(run_dict["scenario"], run_id, html)

    return {
        "run_id": run_id,
        "scenario_name": run_dict["scenario"],
        "writeup_markdown": md,
        "writeup_html": html,
        "writeup_html_path": str(html_path),
    }


@cockpit_router.get("/scenarios/{scenario_name}/curation")
def scenario_curation(scenario_name: str, request: Request) -> dict[str, Any]:
    """Render and persist a read-only scenario curation HTML artifact."""
    try:
        clean_scenario = normalize_scenario_name_segment(scenario_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    artifacts = _get_artifacts(request)
    view = scenario_curation_view_from_artifacts(artifacts, clean_scenario)
    html = render_scenario_curation_html(view)
    html_path = artifacts.write_scenario_curation_html(clean_scenario, html)

    return {
        "scenario_name": clean_scenario,
        "curation_html": html,
        "curation_html_path": str(html_path),
    }


# ---------------------------------------------------------------------------
# Operator-requested consultation (AC-220)
# ---------------------------------------------------------------------------


class ConsultationRequestBody(BaseModel):
    context_summary: str = ""
    generation: int | None = None


def _create_cockpit_consultation_provider(settings: Any) -> LLMProvider | None:
    """Create consultation provider from settings, or None if not configured."""
    if not settings.consultation_api_key:
        return None
    return create_provider(
        provider_type=settings.consultation_provider,
        api_key=settings.consultation_api_key,
        base_url=settings.consultation_base_url or None,
        model=settings.consultation_model,
    )


@cockpit_router.post("/runs/{run_id}/consult")
def request_consultation(run_id: str, body: ConsultationRequestBody, request: Request) -> dict[str, Any]:
    """Request an explicit operator consultation for a run."""
    store = _get_store(request)
    settings = getattr(request.app.state, "app_settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="Settings not configured")

    if not settings.consultation_enabled:
        raise HTTPException(status_code=400, detail="Consultation is not enabled")

    # Validate run exists
    with store.connect() as conn:
        run_row = conn.execute("SELECT run_id, scenario FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if not run_row:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    # Determine generation
    generation = body.generation
    if generation is None:
        with store.connect() as conn:
            gen_row = conn.execute(
                "SELECT MAX(generation_index) as max_gen FROM generations WHERE run_id = ?", (run_id,)
            ).fetchone()
            if gen_row is None or gen_row["max_gen"] is None:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot request consultation for a run with no generations yet",
                )
            generation = int(gen_row["max_gen"])
    else:
        with store.connect() as conn:
            existing_generation = conn.execute(
                "SELECT 1 FROM generations WHERE run_id = ? AND generation_index = ?",
                (run_id, generation),
            ).fetchone()
        if existing_generation is None:
            raise HTTPException(
                status_code=404,
                detail=f"Generation {generation} not found for run '{run_id}'",
            )

    # Check cost budget
    if settings.consultation_cost_budget > 0:
        spent = store.get_total_consultation_cost(run_id)
        if spent >= settings.consultation_cost_budget:
            raise HTTPException(
                status_code=429,
                detail=f"Consultation budget exceeded (spent ${spent:.2f} of ${settings.consultation_cost_budget:.2f})",
            )

    # Build provider
    provider = _create_cockpit_consultation_provider(settings)
    if provider is None:
        raise HTTPException(status_code=503, detail="Consultation provider not configured (missing API key)")

    # Gather context from generations
    with store.connect() as conn:
        gen_rows = conn.execute(
            "SELECT generation_index, mean_score, best_score, elo, gate_decision "
            "FROM generations WHERE run_id = ? ORDER BY generation_index ASC",
            (run_id,),
        ).fetchall()

    score_history = [float(g["best_score"]) for g in gen_rows]
    gate_history = [str(g["gate_decision"]) for g in gen_rows]

    # Get current best strategy summary
    strategy_summary = ""
    with store.connect() as conn:
        strat_row = conn.execute(
            """
            SELECT ao.content
            FROM agent_outputs ao
            JOIN (
                SELECT run_id, generation_index, MAX(rowid) AS max_rowid
                FROM agent_outputs
                WHERE run_id = ? AND role = 'competitor'
                GROUP BY run_id, generation_index
            ) latest ON ao.run_id = latest.run_id
                AND ao.generation_index = latest.generation_index
                AND ao.rowid = latest.max_rowid
            WHERE ao.run_id = ? AND ao.role = 'competitor'
            ORDER BY ao.generation_index DESC
            LIMIT 1
            """,
            (run_id, run_id),
        ).fetchone()
        if strat_row:
            strategy_summary = str(strat_row["content"])[:500]

    # Build consultation request
    context = body.context_summary or f"Operator-requested consultation for run {run_id} at generation {generation}"

    cons_request = ConsReq(
        run_id=run_id,
        generation=generation,
        trigger=ConsultationTrigger.OPERATOR_REQUEST,
        context_summary=context,
        current_strategy_summary=strategy_summary,
        score_history=score_history,
        gate_history=gate_history,
    )

    runner = ConsultationRunner(RetryProvider(provider))

    try:
        result = runner.consult(cons_request)
    except Exception as exc:
        logger.debug("server.cockpit_api: caught Exception", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Consultation call failed: {exc}") from exc

    # Persist
    row_id = store.insert_consultation(
        run_id=run_id,
        generation_index=generation,
        trigger=ConsultationTrigger.OPERATOR_REQUEST.value,
        context_summary=context,
        critique=result.critique,
        alternative_hypothesis=result.alternative_hypothesis,
        tiebreak_recommendation=result.tiebreak_recommendation,
        suggested_next_action=result.suggested_next_action,
        raw_response=result.raw_response,
        model_used=result.model_used,
        cost_usd=result.cost_usd,
    )

    # Write advisory artifact
    artifacts = _get_artifacts(request)
    advisory_dir = artifacts.generation_dir(run_id, generation)
    advisory_path = advisory_dir / "consultation.md"
    advisory_markdown = result.to_advisory_markdown()
    if advisory_path.exists():
        artifacts.append_markdown(advisory_path, advisory_markdown, heading="Operator Requested Consultation")
    else:
        artifacts.write_markdown(advisory_path, advisory_markdown)

    return {
        "consultation_id": row_id,
        "run_id": run_id,
        "generation": generation,
        "trigger": "operator_request",
        "critique": result.critique,
        "alternative_hypothesis": result.alternative_hypothesis,
        "tiebreak_recommendation": result.tiebreak_recommendation,
        "suggested_next_action": result.suggested_next_action,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
        "advisory_markdown": result.to_advisory_markdown(),
    }


@cockpit_router.get("/runs/{run_id}/consultations")
def list_consultations(run_id: str, request: Request) -> list[dict[str, Any]]:
    """List all consultations for a run."""
    store = _get_store(request)
    return store.get_consultations_for_run(run_id)
