"""Pending playbook approval gate helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from difflib import unified_diff
from pathlib import Path
from typing import Any, Protocol

from autocontext.storage.scenario_paths import resolve_scenario_root
from autocontext.util.json_io import read_json, write_json


class LessonApprovalStore(Protocol):
    def read_lessons(self, scenario: str) -> list[Any]: ...
    def write_lessons(self, scenario: str, lessons: list[Any]) -> None: ...


class PlaybookApprovalHost(Protocol):
    knowledge_root: Path

    @property
    def lesson_store(self) -> LessonApprovalStore: ...

    def write_playbook(self, scenario_name: str, content: str) -> None: ...
    def _append_mutation(
        self,
        scenario_name: str,
        *,
        mutation_type: str,
        payload: dict[str, Any],
        generation: int = 0,
        run_id: str = "",
        description: str = "",
    ) -> None: ...


class PlaybookApprovalMethods:
    def write_or_stage_playbook(
        self: PlaybookApprovalHost,
        scenario_name: str,
        content: str,
        *,
        require_playbook_approval: bool,
        source_run_id: str,
        generation: int,
        curator_decision: str = "advance",
    ) -> str:
        if not require_playbook_approval:
            self.write_playbook(scenario_name, content)
            return "live"
        result = stage_pending_playbook(
            self.knowledge_root,
            scenario_name,
            content,
            source_run_id=source_run_id,
            generation=generation,
            curator_decision=curator_decision,
        )
        self._append_mutation(
            scenario_name,
            mutation_type="playbook_pending",
            payload={"generation": generation, "source_run_id": source_run_id},
            description="Playbook update pending approval",
        )
        return result

    def read_pending_playbook(self: PlaybookApprovalHost, scenario_name: str) -> dict[str, Any]:
        return read_pending_playbook(self.knowledge_root, scenario_name)

    def approve_pending_playbook(self: PlaybookApprovalHost, scenario_name: str) -> dict[str, Any]:
        result = approve_pending_playbook(self.knowledge_root, scenario_name, self.write_playbook, self.lesson_store)
        if result["ok"]:
            self._append_mutation(scenario_name, mutation_type="playbook_approved", payload={}, description="Playbook approved")
        return result

    def reject_pending_playbook(self: PlaybookApprovalHost, scenario_name: str) -> dict[str, Any]:
        result = reject_pending_playbook(self.knowledge_root, scenario_name, self.lesson_store)
        if result["ok"]:
            self._append_mutation(scenario_name, mutation_type="playbook_rejected", payload={}, description="Playbook rejected")
        return result


def stage_pending_playbook(
    knowledge_root: Path,
    scenario_name: str,
    content: str,
    *,
    source_run_id: str,
    generation: int,
    curator_decision: str,
    created_at: str | None = None,
) -> str:
    scenario_dir = resolve_scenario_root(knowledge_root, scenario_name)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    normalized = content.strip() + "\n"
    _pending_md(scenario_dir).write_text(normalized, encoding="utf-8")
    write_json(
        _pending_json(scenario_dir),
        {
            "schema_version": 1,
            "scenario_name": scenario_name,
            "source_run_id": source_run_id,
            "generation": generation,
            "curator_decision": curator_decision,
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "status": "pending",
        },
    )
    return "pending"


def read_pending_playbook(knowledge_root: Path, scenario_name: str) -> dict[str, Any]:
    scenario_dir = resolve_scenario_root(knowledge_root, scenario_name)
    pending_path = _pending_md(scenario_dir)
    provenance_path = _pending_json(scenario_dir)
    if not pending_path.exists() or not provenance_path.exists():
        return {"has_pending": False, "content": "", "diff": "", "provenance": None}
    content = pending_path.read_text(encoding="utf-8")
    live_path = scenario_dir / "playbook.md"
    live = live_path.read_text(encoding="utf-8") if live_path.exists() else ""
    diff = "".join(
        unified_diff(
            live.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile="playbook.md",
            tofile="playbook.pending.md",
        )
    )
    return {
        "has_pending": True,
        "content": content,
        "diff": diff,
        "provenance": read_json(provenance_path),
    }


def approve_pending_playbook(
    knowledge_root: Path,
    scenario_name: str,
    write_live_playbook: Callable[[str, str], None],
    lesson_store: LessonApprovalStore | None = None,
) -> dict[str, Any]:
    pending = read_pending_playbook(knowledge_root, scenario_name)
    if not pending["has_pending"]:
        return {"ok": False, "status": "missing"}
    provenance = pending["provenance"] or {}
    write_live_playbook(scenario_name, str(pending["content"]))
    if lesson_store is not None:
        _approve_lessons(lesson_store, scenario_name, int(provenance.get("generation", -1)))
    _clear_pending(resolve_scenario_root(knowledge_root, scenario_name))
    return {"ok": True, "status": "approved"}


def reject_pending_playbook(
    knowledge_root: Path,
    scenario_name: str,
    lesson_store: LessonApprovalStore | None = None,
) -> dict[str, Any]:
    pending = read_pending_playbook(knowledge_root, scenario_name)
    if not pending["has_pending"]:
        return {"ok": False, "status": "missing"}
    provenance = pending["provenance"] or {}
    if lesson_store is not None:
        _drop_lessons(lesson_store, scenario_name, int(provenance.get("generation", -1)))
    _clear_pending(resolve_scenario_root(knowledge_root, scenario_name))
    return {"ok": True, "status": "rejected"}


def _approve_lessons(lesson_store: LessonApprovalStore, scenario_name: str, generation: int) -> None:
    lessons = lesson_store.read_lessons(scenario_name)
    changed = False
    for lesson in lessons:
        if lesson.meta.approval_status == "pending" and lesson.meta.generation == generation:
            lesson.meta.approval_status = "active"
            lesson.meta.last_validated_gen = max(lesson.meta.last_validated_gen, generation)
            changed = True
    if changed:
        lesson_store.write_lessons(scenario_name, lessons)


def _drop_lessons(lesson_store: LessonApprovalStore, scenario_name: str, generation: int) -> None:
    lessons = lesson_store.read_lessons(scenario_name)
    kept = [
        lesson for lesson in lessons if not (lesson.meta.approval_status == "pending" and lesson.meta.generation == generation)
    ]
    if len(kept) != len(lessons):
        lesson_store.write_lessons(scenario_name, kept)


def _clear_pending(scenario_dir: Path) -> None:
    for path in (_pending_md(scenario_dir), _pending_json(scenario_dir)):
        path.unlink(missing_ok=True)


def _pending_md(scenario_dir: Path) -> Path:
    return scenario_dir / "playbook.pending.md"


def _pending_json(scenario_dir: Path) -> Path:
    return scenario_dir / "playbook.pending.json"


__all__ = [
    "PlaybookApprovalMethods",
    "approve_pending_playbook",
    "read_pending_playbook",
    "reject_pending_playbook",
    "stage_pending_playbook",
]
