from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from autocontext.cli import app  # type: ignore[import-untyped]
from autocontext.config.settings import AppSettings, load_settings  # type: ignore[import-untyped]
from autocontext.execution.simple_agent_task_workflow import (  # type: ignore[import-untyped]
    build_simple_agent_task_revision_prompt,
    build_simple_agent_task_user_prompt,
)
from autocontext.knowledge.export import SkillPackage  # type: ignore[import-untyped]
from autocontext.knowledge.solver import SolveJob  # type: ignore[import-untyped]
from autocontext.prompts.templates import build_prompt_bundle  # type: ignore[import-untyped]
from autocontext.scenarios.agent_task import AgentTaskResult  # type: ignore[import-untyped]
from autocontext.scenarios.base import Observation  # type: ignore[import-untyped]
from autocontext.simplicity import SIMPLICITY_GUIDANCE_MARKER  # type: ignore[import-untyped]

runner = CliRunner()


class _RecordingProvider:
    def __init__(self, text: str = "generated output") -> None:
        self._text = text
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        **_: object,
    ) -> SimpleNamespace:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "model": model})
        return SimpleNamespace(text=self._text, model=model)

    def default_model(self) -> str:
        return "recording-model"


class _MetadataLoop:
    last_metadata: dict[str, object] | None = None

    def __init__(self, *args: object, metadata: dict[str, object] | None = None, **kwargs: object) -> None:
        del args, kwargs
        type(self).last_metadata = metadata
        self._metadata = metadata or {}

    def run(self, *args: object, **kwargs: object) -> SimpleNamespace:
        del args, kwargs
        return SimpleNamespace(
            best_score=0.91,
            best_round=1,
            total_rounds=1,
            met_threshold=True,
            best_output="generated output",
            metadata=dict(self._metadata),
        )


class _CapturingSolveManager:
    last_settings: AppSettings | None = None

    def __init__(self, settings: AppSettings) -> None:
        type(self).last_settings = settings

    def solve_sync(
        self,
        description: str,
        generations: int = 5,
        family_override: str | None = None,
        verbatim_task_prompt: str | None = None,
    ) -> SolveJob:
        del generations, family_override, verbatim_task_prompt
        pkg = SkillPackage(
            scenario_name="lean_task",
            display_name="Lean Task",
            description="Solve result",
            playbook="## Playbook",
            lessons=["Be concise"],
            best_strategy={"answer": "short"},
            best_score=0.81,
            best_elo=1512.0,
            hints="Use the shortest correct proof",
        )
        return SolveJob(
            job_id="solve_814",
            description=description,
            scenario_name="lean_task",
            family_name="agent_task",
            status="completed",
            generations=1,
            progress=1,
            result=pkg,
        )


def _settings(tmp_path: Path, **overrides: object) -> AppSettings:
    return AppSettings(
        db_path=tmp_path / "runs" / "autocontext.sqlite3",
        runs_root=tmp_path / "runs",
        knowledge_root=tmp_path / "knowledge",
        skills_root=tmp_path / "skills",
        claude_skills_path=tmp_path / ".claude" / "skills",
        judge_provider="anthropic",
        judge_model="judge-default",
        agent_provider="pi",
        simplicity_mode=cast(Literal["off", "guide", "enforce"], overrides.get("simplicity_mode", "off")),
    )


def test_simplicity_mode_defaults_env_and_rejects_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOCONTEXT_SIMPLICITY_MODE", raising=False)
    assert AppSettings().simplicity_mode == "off"

    monkeypatch.setenv("AUTOCONTEXT_SIMPLICITY_MODE", "guide")
    assert load_settings().simplicity_mode == "guide"

    with pytest.raises(ValidationError):
        AppSettings.model_validate({"simplicity_mode": "strict"})


def test_simple_agent_prompts_inject_simplicity_guidance_once() -> None:
    user_prompt = build_simple_agent_task_user_prompt(
        task_prompt=f"Draft the answer.\n\n{SIMPLICITY_GUIDANCE_MARKER}\nAlready guided.",
        simplicity_mode="guide",
    )
    assert user_prompt.count(SIMPLICITY_GUIDANCE_MARKER) == 1

    revision_prompt = build_simple_agent_task_revision_prompt(
        task_prompt="Draft the answer.",
        output="too much prose",
        judge_result=AgentTaskResult(score=0.5, reasoning="Shorten it"),
        simplicity_mode="guide",
    )
    assert revision_prompt.count(SIMPLICITY_GUIDANCE_MARKER) == 1


def test_generation_prompt_bundle_injects_simplicity_guidance_once_per_role() -> None:
    bundle = build_prompt_bundle(
        scenario_rules="Rules",
        strategy_interface="Return params",
        evaluation_criteria="Correctness",
        previous_summary="None",
        observation=Observation(narrative="Task", state={}, constraints=[]),
        current_playbook="Playbook",
        available_tools="None",
        simplicity_mode="guide",
    )

    for prompt in (bundle.competitor, bundle.analyst, bundle.coach, bundle.architect):
        assert prompt.count(SIMPLICITY_GUIDANCE_MARKER) == 1


def test_improve_simplicity_mode_guides_prompt_and_records_metadata(tmp_path: Path) -> None:
    provider = _RecordingProvider()
    settings = _settings(tmp_path)

    with (
        patch("autocontext.cli.load_settings", return_value=settings),
        patch("autocontext.providers.registry.get_provider", return_value=provider),
        patch("autocontext.execution.improvement_loop.ImprovementLoop", _MetadataLoop),
    ):
        result = runner.invoke(
            app,
            [
                "improve",
                "-p",
                "Draft a migration note",
                "-r",
                "Score correctness 0-1.",
                "--simplicity-mode",
                "enforce",
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    user_prompt = provider.calls[0]["user_prompt"]
    assert isinstance(user_prompt, str)
    assert user_prompt.count(SIMPLICITY_GUIDANCE_MARKER) == 1
    payload = json.loads(result.stdout)
    assert payload["optimizer_metadata"]["simplicity_mode"] == "enforce"
    assert payload["optimizer_metadata"]["simplicity_effective_mode"] == "guide"
    assert "guide-only" in result.stderr


def test_improve_rejects_invalid_simplicity_mode(tmp_path: Path) -> None:
    with patch("autocontext.cli.load_settings", return_value=_settings(tmp_path)):
        result = runner.invoke(
            app,
            [
                "improve",
                "-p",
                "Draft a migration note",
                "-r",
                "Score correctness 0-1.",
                "--simplicity-mode",
                "strict",
                "--json",
            ],
        )

    assert result.exit_code == 2
    assert "simplicity-mode" in result.stderr


def test_solve_simplicity_mode_overrides_settings_and_json_metadata(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with (
        patch("autocontext.cli.load_settings", return_value=settings),
        patch("autocontext.knowledge.solver.SolveManager", _CapturingSolveManager),
    ):
        result = runner.invoke(
            app,
            [
                "solve",
                "Draft a compact proof",
                "--gens",
                "1",
                "--simplicity-mode",
                "guide",
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    assert _CapturingSolveManager.last_settings is not None
    assert _CapturingSolveManager.last_settings.simplicity_mode == "guide"
    payload = json.loads(result.stdout)
    assert payload["optimizer_metadata"]["simplicity_mode"] == "guide"
