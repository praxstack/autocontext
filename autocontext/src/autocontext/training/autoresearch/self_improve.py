"""Self-improving training loop (ReST-EM / Expert Iteration) for autoresearch.

Each round: train on the current dataset, sample constructions from the trained
model and score them in-scenario (collected during assessment), keep the elite
samples, append them to the dataset, and retrain. This is the outer loop that turns
one-shot distillation into PatternBoost / ReST-EM: the model generates new training
data for itself, biased toward the best of what it can already produce.

The pure helpers (elite selection, sample -> record conversion) are backend-agnostic.
The loop currently drives the MLX backend (sample collection is MLX-only for now).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autocontext.training.autoresearch.data_selection import select_top_fraction


def select_elite_samples(samples: list[dict[str, Any]], *, fraction: float) -> list[dict[str, Any]]:
    """Keep the highest-scoring ``fraction`` of generated samples (the ReST filter)."""
    return select_top_fraction(samples, fraction)


def samples_to_records(
    samples: list[dict[str, Any]], *, scenario_name: str, run_id: str, context: Any = None
) -> list[dict[str, Any]]:
    """Convert collected ``{strategy, score}`` samples into training records."""
    return [
        {
            "run_id": run_id,
            "scenario": scenario_name,
            "context": context if context is not None else {},
            "strategy": s["strategy"],
            "score": float(s.get("score", 0.0)),
        }
        for s in samples
        if "strategy" in s
    ]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def run_self_improving_loop(
    *,
    scenario_name: str,
    data_path: Path,
    output_dir: Path,
    rounds: int = 3,
    samples_per_round: int = 16,
    elite_fraction: float = 0.25,
    train_steps: int = 100,
    batch_size: int = 4,
    seq_len: int = 256,
    assess_temperature: float = 1.0,
    assess_top_k: int = 0,
    score_conditioned: bool = False,
    dedupe: bool = True,
    dedupe_near_threshold: float = 1.0,
    time_budget: int = 600,
    memory_limit_mb: int = 16384,
) -> dict[str, Any]:
    """Run the ReST-EM self-improving loop on the MLX backend.

    Returns a dict with the per-round ``history`` (avg_score, sample/elite counts,
    growing dataset size), the final dataset path, and the best avg_score seen.
    """
    from autocontext.training.autoresearch.train import run_training

    output_dir = Path(output_dir)
    # Diverse sampling is required for ReST-EM (greedy would collect identical samples).
    temperature = assess_temperature if assess_temperature > 0 else 1.0

    # Seed from the FULL dataset (train + val); run_training re-splits internally each round.
    accumulated = _read_jsonl(Path(data_path))
    if not accumulated:
        raise ValueError(f"no seed training records found in {data_path}")
    history: list[dict[str, Any]] = []
    best_avg = float("-inf")

    for r in range(rounds):
        round_dir = output_dir / f"round_{r}"
        dataset_path = round_dir / "dataset.jsonl"
        samples_path = round_dir / "samples.jsonl"
        _write_jsonl(dataset_path, accumulated)

        metrics = run_training(
            scenario_name=scenario_name,
            data_path=dataset_path,
            output_dir=round_dir,
            time_budget=time_budget,
            memory_limit_mb=memory_limit_mb,
            train_steps=train_steps,
            batch_size=batch_size,
            seq_len=seq_len,
            assess_samples=samples_per_round,
            assess_temperature=temperature,
            assess_top_k=assess_top_k,
            score_conditioned=score_conditioned,
            dedupe=dedupe,
            dedupe_near_threshold=dedupe_near_threshold,
            collect_samples_path=samples_path,
            backend="mlx",
        )

        samples = _read_jsonl(samples_path)
        elite = select_elite_samples(samples, fraction=elite_fraction) if samples else []
        new_records = samples_to_records(elite, scenario_name=scenario_name, run_id=f"gen_{r}")
        accumulated = accumulated + new_records

        best_avg = max(best_avg, float(metrics.get("avg_score", 0.0)))
        history.append(
            {
                "round": r,
                "avg_score": float(metrics.get("avg_score", 0.0)),
                "valid_rate": float(metrics.get("valid_rate", 0.0)),
                "num_samples": len(samples),
                "num_elite": len(elite),
                "dataset_size": len(accumulated),
            }
        )

    final_path = output_dir / "final_dataset.jsonl"
    _write_jsonl(final_path, accumulated)
    return {
        "scenario": scenario_name,
        "rounds": rounds,
        "history": history,
        "final_dataset": str(final_path),
        "final_dataset_size": len(accumulated),
        "best_avg_score": best_avg if best_avg != float("-inf") else 0.0,
    }
