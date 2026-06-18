"""Generation artifact persistence mixin."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class GenerationPersistenceHost(Protocol):
    def generation_dir(self, run_id: str, generation_index: int) -> Path: ...
    def _scenario_dir(self, scenario_name: str) -> Path: ...
    def buffered_write_json(self, path: Path, payload: dict[str, Any]) -> None: ...
    def buffered_write_markdown(self, path: Path, content: str) -> None: ...
    def buffered_append_markdown(self, path: Path, content: str, heading: str) -> None: ...
    def write_or_stage_playbook(
        self,
        scenario_name: str,
        content: str,
        *,
        require_playbook_approval: bool,
        source_run_id: str,
        generation: int,
        curator_decision: str = "advance",
    ) -> str: ...


class ArtifactGenerationPersistenceMethods:
    def persist_generation(
        self: GenerationPersistenceHost,
        run_id: str,
        generation_index: int,
        metrics: dict[str, Any],
        replay_payload: dict[str, Any],
        analysis_md: str,
        coach_md: str,
        architect_md: str,
        scenario_name: str,
        coach_playbook: str = "",
        require_playbook_approval: bool = False,
    ) -> str:
        gen_dir = self.generation_dir(run_id, generation_index)
        scenario_dir = self._scenario_dir(scenario_name)
        self.buffered_write_json(gen_dir / "metrics.json", metrics)
        self.buffered_write_json(gen_dir / "replays" / f"{scenario_dir.name}_{generation_index}.json", replay_payload)
        self.buffered_write_markdown(scenario_dir / "analysis" / f"gen_{generation_index}.md", analysis_md)
        self.buffered_append_markdown(scenario_dir / "coach_history.md", coach_md, heading=f"generation_{generation_index}")
        playbook_result = "skipped"
        if coach_playbook:
            playbook_result = self.write_or_stage_playbook(
                scenario_name,
                coach_playbook,
                require_playbook_approval=require_playbook_approval,
                source_run_id=run_id,
                generation=generation_index,
            )
        self.buffered_append_markdown(
            scenario_dir / "architect" / "changelog.md",
            architect_md,
            heading=f"generation_{generation_index}",
        )
        return playbook_result


__all__ = ["ArtifactGenerationPersistenceMethods"]
