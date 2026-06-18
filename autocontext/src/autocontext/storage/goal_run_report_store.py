"""File helpers for goal-run reports."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Protocol

from autocontext.analytics.goal_run_report import GoalRunReport
from autocontext.util.json_io import read_json, write_json


class DictSerializable(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


def goal_run_report_path(knowledge_root: Path, goal_id: str, goal_run_id: str) -> Path:
    return knowledge_root / "goal_runs" / _path_segment(goal_id, "goal_id") / f"{_path_segment(goal_run_id, 'goal_run_id')}.json"


def _path_segment(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    if "/" in normalized or "\\" in normalized:
        raise ValueError(f"{label} must be a single path segment: {value!r}")
    for path_cls in (PurePosixPath, PureWindowsPath):
        candidate = path_cls(normalized)
        if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.parts[0] in {".", ".."}:
            raise ValueError(f"{label} must be a single path segment: {value!r}")
    return normalized


def write_goal_run_report(knowledge_root: Path, goal_id: str, goal_run_id: str, report: DictSerializable) -> Path:
    path = goal_run_report_path(knowledge_root, goal_id, goal_run_id)
    write_json(path, report.to_dict())
    return path


def read_goal_run_report(knowledge_root: Path, goal_id: str, goal_run_id: str) -> GoalRunReport | None:
    path = goal_run_report_path(knowledge_root, goal_id, goal_run_id)
    return GoalRunReport.from_dict(read_json(path)) if path.exists() else None


__all__ = [
    "goal_run_report_path",
    "read_goal_run_report",
    "write_goal_run_report",
]
