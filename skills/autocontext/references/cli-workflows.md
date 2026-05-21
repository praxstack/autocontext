# CLI Workflows

Concrete `autoctx` commands for Hermes terminal usage. Use this when an
agent needs the exact command + flag form for a common workflow.

> **Command availability.** `inspect` and `export-skill` are always
> present in releases that include this reference. `ingest-curator` and
> `export-dataset` ship on follow-up Hermes-integration PRs; run
> `autoctx hermes --help` to confirm what is installed locally before
> recommending one of them.

## Inventory: what does my Hermes home contain?

```bash
autoctx hermes inspect --home ~/.hermes --json
```

Output: JSON summary with `skills`, `bundled_skill_count`,
`hub_skill_count`, `pinned_skill_count`, `archived_skill_count`,
`curator.run_count`, and `curator.latest`. Read-only.

## Install the autocontext skill into Hermes

```bash
autoctx hermes export-skill     --output ~/.hermes/skills/autocontext/SKILL.md     --json
```

Add `--force` to overwrite. Add `--with-references` (when this
release is on the user's machine) to also write the reference files
described here.

## Ingest curator reports as ProductionTrace JSONL

```bash
autoctx hermes ingest-curator     --home ~/.hermes     --output traces/hermes-curator.jsonl     [--since 2026-05-01T00:00:00Z]     [--limit 100]     [--json]
```

Privacy defaults: `--include-llm-final` and `--include-tool-args` are
**off by default**. Pass them explicitly if the user wants the LLM
final summary as an assistant message, or raw tool args preserved.

## Export curator decisions as training JSONL

```bash
autoctx hermes export-dataset     --kind curator-decisions     --home ~/.hermes     --output training/hermes-curator-decisions.jsonl     [--since 2026-05-01T00:00:00Z]     [--limit 1000]     [--json]
```

Each row carries strong labels from curator action lists
(`consolidated` / `pruned` / `archived` / `added`), feature-engineered
skill stats, and run-level context. Pinned, bundled, and hub skills
are never mutation targets.

## Evaluate an agent output

```bash
autoctx judge -p "$PROMPT" -o "$OUTPUT" -r "$RUBRIC" --json
```

Or run an improvement loop:

```bash
autoctx improve --scenario my_saved_task -o "$OUTPUT" --json
```

## Inspect a finished run

```bash
autoctx list
autoctx show <run-id>
autoctx replay <run-id> --generation 1
```
