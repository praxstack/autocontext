# Documentation verification log

This documentation tree was authored Fumadocs-ready (MDX + per-folder `meta.json`)
and verified section by section against the autocontext repo source. The Next.js +
Fumadocs application is intentionally not built here; this is content only.

## Site-wide audits (final consistency pass)

- Page count: 43 `.mdx` pages.
- Frontmatter: every page begins with valid frontmatter carrying `title` and `description`.
- Style: zero em dashes across the tree (house rule); "autocontext" lowercase in prose,
  with `AutoContext` retained only as the literal Python class identifier.
- Navigation: every section directory has a `meta.json`; all are valid JSON and list every
  sibling page and subdirectory (no orphan pages).
- Links: all 37 distinct internal `/docs/...` links resolve to an existing page or folder index.

## Per-section source verification

- **Get Started / Concepts / CLI**: command and flag claims verified against the repo CLI
  source (`autocontext/src/autocontext/cli.py`, `cli_run_inspect.py`, `cli_solve.py`,
  `cli_queue.py`, `ts/src/cli/index.ts`, `ts/src/cli/command-registry.ts`). The installed
  `autoctx` binary is a stale older version, so the repo source was treated as the source of
  truth. Corrections made during authoring: `queue add` uses `--rounds`/`-n` (not
  `--max-rounds`); `show`/`watch` exist on both runtimes; `ab-test` uses `--baseline`/
  `--treatment` env-override flags; redundant identical Python/TS tabs were collapsed.
- **On-disk layout** (concepts, get-started): verified against `storage/artifacts.py`,
  `knowledge/lessons.py`, `knowledge/research_hub.py`. Per-generation artifacts at
  `runs/<run_id>/generations/gen_<N>/`; knowledge at `knowledge/<scenario>/` with
  `playbook.md`, `hints.md`, `lessons.json` (JSON), `snapshots/<run_id>/`, and
  `reports/<run_id>.md`. There is no top-level `runs/<run_id>/trace.jsonl` or `report.md`.
- **Providers**: provider enum, defaults, and env vars verified against
  `agents/llm_client.py` (`build_client_from_settings`), `providers/registry.py`,
  `config/settings.py`, `.env.example`, and `runtimes/pi_cli.py` / `pi_rpc.py`. The code
  default provider is `anthropic` (`.env.example` ships `deterministic` as a template only).
  `pi-rpc` is a JSONL subprocess, not HTTP (the docs match source over a stale CLAUDE.md).
  gemini/mistral/groq/openrouter/azure are reachable via `openai-compatible`, not enum values.
- **Agent integration**: MCP tool names verified against `autocontext/src/autocontext/mcp/`
  and `ts/src/mcp/`; `pi install npm:pi-autocontext` verified against `pi/package.json`; the
  Claude Code `mcpServers` JSON verified runnable.
- **SDK**: `AutoContext` method signatures verified against `sdk.py` / `sdk_models.py`; TS
  exports verified against `ts/src/index.ts`; all 12 hook events verified against the
  `HookEvents` enum in `extensions/hooks.py`.
- **Guides**: faithful rewrites of `docs/mlx-training.md`, `docs/sandbox.md`,
  `docs/persistent-host.md`, `docs/fixture-loader.md` (scripts, systemd units, plists, and
  manifests reproduced); `production-traces` subcommands verified against
  `ts/src/production-traces/cli/index.ts` (init, ingest, list, show, stats, build-dataset,
  datasets, export, policy, rotate-salt, prune).
- **Reference**: 46 environment variables generated row-by-row from `.env.example` (names and
  defaults match the file 1:1); MCP tool catalog generated from source (72 Python tools, 76
  TypeScript tools, cross-checked against the registrations); glossary terms link to their
  fuller treatments.

## Deferred (out of scope for this pass)

- The Next.js + Fumadocs application (`source.config.ts`, theming, search, deploy).
- Marketing-site linking.
- Auto-generated API reference tooling and versioned docs.
