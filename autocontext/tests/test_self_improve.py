"""Tests for the ReST-EM self-improving training loop (PR7).

The pure helpers (elite selection, sample -> record conversion) run in CI.
The full loop is an MLX end-to-end test, gated behind HAS_MLX like the other
backend smoke tests, and runs two rounds so the dataset-growth invariant is real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autocontext.training import HAS_MLX
from autocontext.training.autoresearch.self_improve import (
    samples_to_records,
    select_elite_samples,
)


def test_select_elite_samples_keeps_top_fraction() -> None:
    samples = [{"strategy": {"a": i}, "score": float(i)} for i in range(8)]
    elite = select_elite_samples(samples, fraction=0.25)
    assert len(elite) == 2
    assert {s["score"] for s in elite} == {7.0, 6.0}


def test_select_elite_samples_empty() -> None:
    assert select_elite_samples([], fraction=0.5) == []


def test_samples_to_records_shapes_training_records() -> None:
    samples = [
        {"strategy": {"aggression": 0.5}, "score": 0.9},
        {"strategy": {"aggression": 0.1}, "score": 0.2},
    ]
    records = samples_to_records(samples, scenario_name="grid_ctf", run_id="gen_0")
    assert len(records) == 2
    for rec, src in zip(records, samples, strict=True):
        assert rec["run_id"] == "gen_0"
        assert rec["scenario"] == "grid_ctf"
        assert rec["strategy"] == src["strategy"]
        assert rec["score"] == src["score"]
        assert rec["context"] == {}


def test_samples_to_records_skips_entries_without_strategy() -> None:
    samples = [{"score": 0.5}, {"strategy": {"x": 1}, "score": 0.7}]
    records = samples_to_records(samples, scenario_name="grid_ctf", run_id="gen_1")
    assert len(records) == 1
    assert records[0]["strategy"] == {"x": 1}


def test_run_training_collect_samples_path_non_mlx_raises(tmp_path: str) -> None:
    """The collect-samples plumbing is MLX-only; other backends reject it loudly."""
    from autocontext.training.autoresearch.train import run_training

    records = [
        {"run_id": f"r{i % 2}", "scenario": "grid_ctf", "context": {}, "strategy": {"a": 0.5}, "score": 0.5 + 0.01 * i}
        for i in range(6)
    ]
    data_path = Path(tmp_path) / "data.jsonl"
    data_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    with pytest.raises(NotImplementedError, match="MLX-only"):
        run_training(
            scenario_name="grid_ctf",
            data_path=data_path,
            output_dir=Path(tmp_path) / "out",
            time_budget=30,
            memory_limit_mb=4096,
            train_steps=1,
            batch_size=1,
            seq_len=16,
            backend="cuda",
            collect_samples_path=Path(tmp_path) / "samples.jsonl",
        )


@pytest.mark.skipif(not HAS_MLX, reason="MLX not installed")
def test_self_improving_loop_two_rounds_grows_dataset(tmp_path: str) -> None:
    """Two ReST-EM rounds: the loop trains, collects+filters samples, and the
    dataset strictly grows when elite samples are kept (or stays equal if a round
    produced no valid samples). History length and accounting are pinned."""
    from autocontext.training.autoresearch.self_improve import run_self_improving_loop

    records = [
        {
            "run_id": f"r{i % 2}",
            "scenario": "grid_ctf",
            "context": {"playbook": "p"},
            "strategy": {"aggression": 0.5, "defense": 0.3},
            "score": 0.5 + 0.01 * i,
        }
        for i in range(6)
    ]
    data_path = Path(tmp_path) / "seed.jsonl"
    data_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    result = run_self_improving_loop(
        scenario_name="grid_ctf",
        data_path=data_path,
        output_dir=Path(tmp_path) / "loop",
        rounds=2,
        samples_per_round=2,
        elite_fraction=0.5,
        train_steps=1,
        batch_size=1,
        seq_len=16,
        time_budget=30,
        memory_limit_mb=4096,
    )

    assert result["rounds"] == 2
    assert len(result["history"]) == 2
    # Dataset is monotone non-decreasing across rounds and never below the seed size.
    sizes = [h["dataset_size"] for h in result["history"]]
    assert sizes[0] >= len(records)
    assert sizes[1] >= sizes[0]
    assert result["final_dataset_size"] == sizes[-1]
    assert Path(result["final_dataset"]).exists()
    for h in result["history"]:
        assert h["num_elite"] <= h["num_samples"]
