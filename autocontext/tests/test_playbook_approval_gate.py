from __future__ import annotations

from pathlib import Path

import pytest


def _store(tmp_path: Path):
    from autocontext.storage.artifacts import ArtifactStore

    return ArtifactStore(
        runs_root=tmp_path / "runs",
        knowledge_root=tmp_path / "knowledge",
        skills_root=tmp_path / "skills",
        claude_skills_path=tmp_path / "claude-skills",
    )


def _persist_args() -> dict[str, object]:
    return {
        "run_id": "run-approval",
        "generation_index": 2,
        "metrics": {},
        "replay_payload": {},
        "analysis_md": "analysis",
        "coach_md": "coach",
        "architect_md": "architect",
        "scenario_name": "grid_ctf",
        "coach_playbook": "pending playbook",
    }


def test_playbook_approval_default_off_writes_live(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_playbook("grid_ctf", "approved playbook")

    store.persist_generation(**_persist_args())

    assert store.read_playbook("grid_ctf") == "pending playbook\n"
    assert store.read_pending_playbook("grid_ctf")["has_pending"] is False


def test_playbook_approval_stages_pending_without_touching_live(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_playbook("grid_ctf", "approved playbook")

    result = store.persist_generation(**_persist_args(), require_playbook_approval=True)

    assert result == "pending"
    assert store.read_playbook("grid_ctf") == "approved playbook\n"
    pending = store.read_pending_playbook("grid_ctf")
    assert pending["has_pending"] is True
    assert pending["content"] == "pending playbook\n"
    assert "-approved playbook" in pending["diff"]
    assert "+pending playbook" in pending["diff"]
    assert pending["provenance"]["source_run_id"] == "run-approval"
    assert pending["provenance"]["generation"] == 2


def test_approve_pending_playbook_promotes_and_activates_same_generation_lessons(tmp_path: Path) -> None:
    from autocontext.knowledge.lessons import ApplicabilityMeta

    store = _store(tmp_path)
    store.write_playbook("grid_ctf", "approved playbook")
    store.lesson_store.add_lesson(
        "grid_ctf",
        "held lesson",
        ApplicabilityMeta(created_at="", generation=2, best_score=0.7, approval_status="pending"),
    )
    store.persist_generation(**_persist_args(), require_playbook_approval=True)

    assert store.approve_pending_playbook("grid_ctf") == {"ok": True, "status": "approved"}

    assert store.read_playbook("grid_ctf") == "pending playbook\n"
    assert store.read_pending_playbook("grid_ctf")["has_pending"] is False
    lessons = store.lesson_store.read_lessons("grid_ctf")
    assert [lesson.text for lesson in lessons] == ["held lesson"]
    assert lessons[0].meta.approval_status == "active"


def test_pending_playbook_cannot_be_overwritten_before_review(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_playbook("grid_ctf", "approved playbook")
    store.persist_generation(**_persist_args(), require_playbook_approval=True)
    args = _persist_args() | {"generation_index": 3, "coach_playbook": "new pending playbook"}

    with pytest.raises(ValueError, match="pending playbook already exists"):
        store.persist_generation(**args, require_playbook_approval=True)

    pending = store.read_pending_playbook("grid_ctf")
    assert pending["content"] == "pending playbook\n"
    assert pending["provenance"]["generation"] == 2


def test_pending_skill_lessons_do_not_reach_skill_prompt_until_approval(tmp_path: Path) -> None:
    from autocontext.agents.types import AgentOutputs
    from autocontext.config.settings import AppSettings
    from autocontext.harness.evaluation.types import EvaluationSummary
    from autocontext.loop.stage_helpers.persistence_helpers import _persist_skill_note
    from autocontext.loop.stage_types import GenerationContext
    from autocontext.scenarios.grid_ctf.scenario import GridCtfScenario

    store = _store(tmp_path)
    store.write_playbook("grid_ctf", "approved playbook")
    playbook_result = store.persist_generation(**_persist_args(), require_playbook_approval=True)
    ctx = GenerationContext(
        run_id="run-approval",
        scenario_name="grid_ctf",
        scenario=GridCtfScenario(),
        generation=2,
        settings=AppSettings(),
        previous_best=0.7,
        challenger_elo=1000.0,
        score_history=[],
        gate_decision_history=[],
        coach_competitor_hints="",
        replay_narrative="",
        require_playbook_approval=True,
    )
    ctx.gate_decision = "advance"
    ctx.gate_delta = 0.1
    ctx.outputs = AgentOutputs(
        strategy={},
        analysis_markdown="",
        coach_markdown="",
        coach_playbook="pending playbook",
        coach_lessons="- unapproved lesson",
        coach_competitor_hints="",
        architect_markdown="",
        architect_tools=[],
        role_executions=[],
    )
    ctx.tournament = EvaluationSummary(mean_score=0.7, best_score=0.7, wins=1, losses=0, elo_after=1000.0, results=[])

    _persist_skill_note(ctx, artifacts=store, playbook_result=playbook_result)

    assert "unapproved lesson" not in store.read_skills("grid_ctf")
    [lesson] = store.lesson_store.read_lessons("grid_ctf")
    assert lesson.text == "- unapproved lesson"
    assert lesson.meta.approval_status == "pending"

    store.approve_pending_playbook("grid_ctf")

    assert "unapproved lesson" in store.read_skills("grid_ctf")
    assert store.lesson_store.read_lessons("grid_ctf")[0].meta.approval_status == "active"


def test_reject_pending_playbook_discards_and_drops_same_generation_lessons(tmp_path: Path) -> None:
    from autocontext.knowledge.lessons import ApplicabilityMeta

    store = _store(tmp_path)
    store.write_playbook("grid_ctf", "approved playbook")
    store.lesson_store.add_lesson(
        "grid_ctf",
        "held lesson",
        ApplicabilityMeta(created_at="", generation=2, best_score=0.7, approval_status="pending"),
    )
    store.persist_generation(**_persist_args(), require_playbook_approval=True)

    assert store.reject_pending_playbook("grid_ctf") == {"ok": True, "status": "rejected"}

    assert store.read_playbook("grid_ctf") == "approved playbook\n"
    assert store.read_pending_playbook("grid_ctf")["has_pending"] is False
    assert store.lesson_store.read_lessons("grid_ctf") == []
