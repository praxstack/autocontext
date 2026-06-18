from __future__ import annotations

from pathlib import Path


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
