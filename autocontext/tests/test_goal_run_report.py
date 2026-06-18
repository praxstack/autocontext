from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "docs" / "goal-run-report-parity-fixture.json"


def _cases() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


def _build_args(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal_id": case["goal_id"],
        "goal_run_id": case["goal_run_id"],
        "scenario_name": case["scenario_name"],
        "objective": case["objective"],
        "verifier_ref": case["verifier_ref"],
        "generated_at": case["generated_at"],
        "resume_token": case["resume_token"],
        "budget": case["budget"],
        "usage": case["usage"],
        "actions": case["actions"],
        "verifier_state": case["verifier_state"],
        "next_action_kind": case.get("next_action_kind"),
        "blocked_reason": case.get("blocked_reason"),
        "requested_cancel": case.get("requested_cancel", False),
        "decision_id": case["decision_id"],
    }


def test_build_goal_run_report_matches_shared_fixture() -> None:
    from autocontext.analytics.goal_run_report import build_goal_run_report

    for case in _cases():
        assert build_goal_run_report(**_build_args(case)).to_dict() == case["expected_report"]


def test_goal_run_report_round_trips_shared_json() -> None:
    from autocontext.analytics.goal_run_report import GoalRunReport

    for case in _cases():
        expected = case["expected_report"]
        assert GoalRunReport.from_dict(expected).to_dict() == expected


def test_goal_run_report_covers_terminal_and_continued_statuses() -> None:
    statuses = {case["expected_report"]["status"] for case in _cases()}

    assert statuses == {
        "continued",
        "verified_complete",
        "blocked",
        "budget_exhausted",
        "verifier_failed",
        "no_progress",
        "canceled",
    }


def test_goal_run_report_persists_for_resume(tmp_path: Path) -> None:
    from autocontext.analytics.goal_run_report import GoalRunReport
    from autocontext.storage.goal_run_report_store import read_goal_run_report, write_goal_run_report

    report = GoalRunReport.from_dict(_cases()[0]["expected_report"])
    write_goal_run_report(tmp_path / "knowledge", report.goal_id, report.goal_run_id, report)

    restored = read_goal_run_report(tmp_path / "knowledge", report.goal_id, report.goal_run_id)
    assert isinstance(restored, GoalRunReport)
    assert restored.resume_token == "goal-run-1:1"
    assert restored.to_dict() == report.to_dict()


def test_goal_run_report_file_store_rejects_path_traversal(tmp_path: Path) -> None:
    from autocontext.analytics.goal_run_report import GoalRunReport
    from autocontext.storage.goal_run_report_store import write_goal_run_report

    report = GoalRunReport.from_dict(_cases()[0]["expected_report"])

    for goal_id, goal_run_id in [("../../../outside", report.goal_run_id), (report.goal_id, "../../../outside")]:
        try:
            write_goal_run_report(tmp_path / "knowledge", goal_id, goal_run_id, report)
        except ValueError:
            continue
        raise AssertionError("path-traversing goal identifier was accepted")

    assert not (tmp_path / "outside.json").exists()


def test_goal_run_report_rejects_schema_invalid_data() -> None:
    from autocontext.analytics.goal_run_report import GoalRunReport

    expected = _cases()[0]["expected_report"]
    missing_budget_field = {key: value for key, value in expected["budget"].items() if key != "max_iterations"}
    bad_action = {**expected["actions"][0], "action_kind": "unknown"}
    bad_status = {**expected, "status": "active"}

    for payload in [
        {key: value for key, value in expected.items() if key != "schema_version"},
        {**expected, "surprise": True},
        {**expected, "goal_id": ""},
        {**expected, "budget": missing_budget_field},
        {**expected, "usage": {**expected["usage"], "iterations": -1}},
        {**expected, "actions": [bad_action]},
        bad_status,
    ]:
        try:
            GoalRunReport.from_dict(payload)
        except ValueError:
            continue
        raise AssertionError("schema-invalid goal run report was accepted")
