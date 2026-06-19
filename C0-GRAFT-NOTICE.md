# C0 held-out gate — graft notice

This fork of `greyhaven-ai/autocontext` (Apache-2.0) adds agent-org's **C0 held-out
gate** to close the gameable LLM-judge hole on the plain-language-task path.

## Changes (branch `feat/c0-heldout-gate`, 2026-06-19)
- **NEW** `autocontext/src/autocontext/execution/heldout_gate.py` — clean-room Python
  port of agent-org's `lib/heldout-gate.sh`. Enforces C0 (grader outside the agent's
  write scope; no `../` reach; no symlink swap; optional pinned sha256), runs the grader
  from a clean cwd with scrubbed `PYTHON*`, parses a held-out `SCORE:` line, enforces
  threshold + ratchet. Structural violation is never a silent pass.
- **MODIFIED** `autocontext/src/autocontext/execution/judge.py` — `LLMJudge.evaluate()`
  now calls `_maybe_heldout()` first; if `AUTOCONTEXT_HELDOUT_GRADER` +
  `AUTOCONTEXT_HELDOUT_WORKDIR` are set, scoring goes through the C0 gate **instead of**
  the LLM judge. Opt-in: unset env => unchanged behavior.
- **NEW** `autocontext/tests/test_heldout_gate_redteam.py` — falsify-don't-demo red-team.
  **7/7 PASS:** refuses grader-in-write-scope (auto-harness vector), `../`-reachable
  grader (sia vector), sitecustomize poison (E2 vector), tampered-vs-pinned grader (C2),
  and honors honest pass/fail/ratchet.

## Why
agent-org's reproduce-first study (2026-06-19) found autocontext's `agent_task` path
scores via an LLM judging its own provider's output — gameable by a self-improving
optimizer. The C0 gate is the one piece agent-org verified it is ahead of the field on;
this graft combines autocontext's strong engine with that gate.

Upstream remains Apache-2.0; this NOTICE documents the modification per the license.
