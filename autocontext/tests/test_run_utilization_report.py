from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "docs" / "run-utilization-report-parity-fixture.json"


def _cases() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


def test_build_run_utilization_report_matches_shared_fixture() -> None:
    from autocontext.analytics.run_utilization_report import build_run_utilization_report

    for case in _cases():
        report = build_run_utilization_report(
            run_id=case["run_id"],
            events=case["events"],
            role_usage=case["role_usage"],
            generated_at=case["generated_at"],
        )

        assert report.to_dict() == case["expected_report"]


def test_run_utilization_report_round_trips_from_shared_json() -> None:
    from autocontext.analytics.run_utilization_report import RunUtilizationReport

    for case in _cases():
        expected = case["expected_report"]
        assert RunUtilizationReport.from_dict(expected).to_dict() == expected


def test_run_utilization_report_rejects_schema_invalid_data() -> None:
    from autocontext.analytics.run_utilization_report import RunUtilizationReport

    expected = _cases()[1]["expected_report"]
    for payload in [
        {**expected, "surprise": True},
        {**expected, "run_id": ""},
        {**expected, "generated_at": ""},
    ]:
        try:
            RunUtilizationReport.from_dict(payload)
        except ValueError:
            continue
        raise AssertionError("schema-invalid utilization report was accepted")
