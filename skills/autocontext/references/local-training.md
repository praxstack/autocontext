# Local Training

How autocontext-exported datasets feed local MLX or CUDA training. Use
this when the user asks "can I train a model from my Hermes data" or
when an agent needs to scope training expectations.

> **Command availability.** `autoctx hermes export-dataset` (AC-705)
> ships on a follow-up PR in the Hermes-integration cluster.
> `autoctx train` is shipped today. Run `autoctx hermes --help` and
> `autoctx train --help` to confirm what is installed locally before
> recommending the end-to-end flow below.

## Scope (read this first)

`autoctx train` produces **narrow advisor classifiers**, not full
agent replacements. The expected use is: should this curator decision
have been made? Should this skill be active vs archived? Was this
consolidation good?

**Small personal Hermes homes will not produce frontier-quality
models.** The size and diversity of the dataset matter more than the
training pipeline. If the user has < 100 curator runs, propose a
shadow-evaluation loop instead of training.

## End-to-end flow

1. Export a labeled dataset:

   ```bash
   autoctx hermes export-dataset        --kind curator-decisions        --home ~/.hermes        --output training/hermes-curator-decisions.jsonl
   ```

2. Inspect the dataset shape:

   ```bash
   head -1 training/hermes-curator-decisions.jsonl | jq .
   ```

   Each row is a flat feature vector + label + confidence. See the
   AC-705 module docstring for the canonical schema.

3. (Future) Train an advisor model:

   ```bash
   autoctx train --backend mlx --dataset training/hermes-curator-decisions.jsonl
   autoctx train --backend cuda --dataset training/hermes-curator-decisions.jsonl
   ```

   The training pipeline adapter for this dataset shape is a follow-up
   (AC-708); for now the dataset shape ships and an external trainer
   can consume the JSONL directly.

4. (Future) Surface advisor predictions back to Hermes Curator as
   **read-only recommendations** (AC-709). Curator stays the mutation
   owner.

## Backend selection

- **MLX**: Apple Silicon laptops with plenty of RAM. Quick iteration.
- **CUDA**: x86 + NVIDIA. Faster wall-clock for the same dataset.

Both backends produce models in the same on-disk format that the
advisor surface (AC-709) will consume.

## What the advisor predicts

Per the AC-708 design, the initial advisor tasks are:

- classify whether a skill is `active` / `stale` / `prunable` /
  `pinned` / `patch-worthy`,
- recommend likely umbrella consolidation targets,
- rank candidate skills for a task/session summary,
- detect low-confidence Curator actions (so an operator can review
  before the decision is durable).

None of these mutate Hermes state. They are evidence + scores;
Curator decides what to do with them.
