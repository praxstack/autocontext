"""Tests for train.py format_summary (runs without MLX)."""

from __future__ import annotations

import importlib
from typing import Any


def _train() -> Any:
    return importlib.import_module("autocontext.training.autoresearch.train")


def test_format_summary_no_mlx() -> None:
    """format_summary works even without MLX installed."""
    result = _train().format_summary(
        avg_score=0.85,
        valid_rate=0.99,
        training_seconds=60.0,
        peak_memory_mb=512.0,
        num_steps=500,
        num_params_m=2.0,
        depth=4,
    )
    assert "avg_score: 0.8500" in result
    assert "valid_rate: 0.9900" in result
    assert "depth: 4" in result
    # val_loss omitted when not provided (keeps existing callers unchanged)
    assert "val_loss" not in result


def test_format_summary_includes_val_loss_when_provided() -> None:
    """When val_loss is provided it is emitted so the runner/CLI can surface it."""
    result = _train().format_summary(
        avg_score=0.85,
        valid_rate=0.99,
        training_seconds=60.0,
        peak_memory_mb=512.0,
        num_steps=500,
        num_params_m=2.0,
        depth=4,
        val_loss=1.2345,
    )
    assert "val_loss: 1.2345" in result


def test_parse_summary_picks_up_val_loss() -> None:
    """TrainingRunner.parse_summary surfaces the val_loss line from the block."""
    TrainingRunner = importlib.import_module("autocontext.training.runner").TrainingRunner

    block = _train().format_summary(
        avg_score=0.5,
        valid_rate=1.0,
        training_seconds=1.0,
        peak_memory_mb=10.0,
        num_steps=3,
        num_params_m=0.1,
        depth=4,
        val_loss=0.789,
    )
    runner = TrainingRunner.__new__(TrainingRunner)  # parse_summary is pure; skip __init__
    parsed = TrainingRunner.parse_summary(runner, block)
    assert parsed is not None
    assert parsed["val_loss"] == 0.789


def test_default_train_steps_distinguishes_from_scratch_vs_adapter() -> None:
    """A from-scratch GPT converges in a few steps; pretrained-adapter backends need far more,
    so the unset (<=0) sentinel must resolve to different defaults per backend family."""
    train = _train()
    assert train._default_train_steps("mlx") == 8
    assert train._default_train_steps("cuda") == 8
    for adapter in ("mlxlm", "opd", "grpo", "trl"):
        assert train._default_train_steps(adapter) == 100, adapter


def test_train_parser_accepts_trl_prompt_count() -> None:
    args = _train()._build_parser().parse_args(
        [
            "--scenario",
            "gsm8k",
            "--data",
            "data/gsm8k.jsonl",
            "--output-dir",
            "runs/out",
            "--backend",
            "trl",
            "--trl-mode",
            "gkd",
            "--n-prompts",
            "384",
        ]
    )

    assert args.n_prompts == 384


def test_trl_backend_receives_prompt_count(monkeypatch, tmp_path) -> None:
    train = _train()
    trl_backend = importlib.import_module("autocontext.training.autoresearch.trl_backend")
    captured = {}

    def fake_run_trl_training(**kwargs):
        captured.update(kwargs)
        return {
            "avg_score": 0.0,
            "valid_rate": 0.0,
            "training_seconds": 0.0,
            "peak_memory_mb": 0.0,
            "num_steps": 1.0,
            "num_params_m": 0.0,
            "depth": 0.0,
        }

    monkeypatch.setattr(train, "_preflight_backend_deps", lambda _backend: None)
    monkeypatch.setattr(trl_backend, "run_trl_training", fake_run_trl_training)

    train.run_training(
        scenario_name="gsm8k",
        data_path=tmp_path / "data.jsonl",
        output_dir=tmp_path / "out",
        time_budget=1,
        memory_limit_mb=1024,
        backend="trl",
        n_prompts=384,
    )

    assert captured["n_prompts"] == 384


def test_default_learning_rate_per_backend() -> None:
    """A from-scratch LR (1e-3) diverges a LoRA adapter; each adapter backend resolves to the
    rate its own entry point is tuned for when --learning-rate is left unset."""
    train = _train()
    assert train._default_learning_rate("mlx") == 1e-3
    assert train._default_learning_rate("cuda") == 1e-3
    assert train._default_learning_rate("mlxlm") == 1e-4
    for rlvr in ("opd", "grpo", "trl"):
        assert train._default_learning_rate(rlvr) == 1e-5, rlvr
