"""C0 held-out gate — a grader the optimizer cannot reach or write.

GRAFTED FROM agent-org (lib/heldout-gate.sh), 2026-06-19, on the fork branch
feat/c0-heldout-gate. Clean-room Python port of agent-org's own gate — NOT derived
from any non-permissive source.

WHY THIS EXISTS IN THE FORK
---------------------------
autocontext's LLMJudge (execution/judge.py) scores an agent's plain-language-task
output by having an LLM rate that same provider's output. agent-org's reproduce-first
study (2026-06-19) flagged this as the gameable hole: a self-improving optimizer can
learn to satisfy the judge without satisfying the task (Goodhart), and the judge has
no execution check and no held-out answer key. This module is the opt-in fix: when a
task declares a held-out grader, scoring goes through THIS gate (execution-based,
agent-unreachable) instead of the LLM judge.

The C0 property (constitution C0, proven in agent-org's E2 red-team): the optimizer
never has write access to its evaluator. Enforced here as a PRE-FLIGHT check before
any score is trusted:
  1. grader must live OUTSIDE the agent's write scope (work_dir),
  2. grader's dir must NOT be an ancestor of work_dir (blocks a ``../`` walk),
  3. grader must not be a swappable symlink,
  4. optional pinned sha256 (content-address; a changed grader = violation),
then the grader runs from a CLEAN cwd with scrubbed PYTHON* env (defeats a poisoned
sitecustomize/conftest in work_dir) and must emit a final ``SCORE: <float>`` line.

A structural violation returns ``ok=False, structural=True`` — treated as worse than
a low score: NEVER silently mapped to a pass. Reporting a score when C0 cannot be
guaranteed would itself be greenwash.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass

_SCORE_RE = re.compile(r"^\s*SCORE:\s*(-?\d+(?:\.\d+)?)\s*$", re.MULTILINE)


@dataclass(slots=True)
class HeldoutResult:
    """Outcome of a held-out gate run."""

    ok: bool                      # True iff score >= threshold AND no structural violation
    score: float | None           # parsed held-out score, or None if unparseable/violation
    structural_violation: bool     # True iff C0 could not be guaranteed (worse than FAIL)
    reason: str                    # human-readable finding


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def preflight(work_dir: str, grader_path: str) -> str | None:
    """Return None if C0 holds, else a string describing the violation."""
    if not os.path.exists(grader_path):
        return f"grader not found: {grader_path}"
    if not os.access(grader_path, os.X_OK):
        return f"grader not executable: {grader_path}"
    if not os.path.isdir(work_dir):
        return f"work_dir not a directory: {work_dir}"
    if os.path.islink(grader_path):
        return f"grader is a symlink ({grader_path}) — target is swappable"

    awork = os.path.realpath(work_dir)
    agrader = os.path.realpath(grader_path)
    gdir = os.path.dirname(agrader)

    # V1 — grader inside the optimizer write scope (it could edit its own grader).
    if agrader == awork or agrader.startswith(awork + os.sep):
        return (
            f"C0 VIOLATION: grader ({agrader}) is INSIDE the optimizer write scope "
            f"({awork}) — it could edit its own grader"
        )
    # V2 — grader's dir is an ancestor of work_dir (reachable by a ../ walk: the sia hole).
    if awork == gdir or awork.startswith(gdir + os.sep):
        return (
            f"C0 VIOLATION: grader dir ({gdir}) is an ANCESTOR of work_dir ({awork}) "
            f"— reachable by a ../ walk"
        )
    return None


def run_heldout_gate(
    work_dir: str,
    grader_path: str,
    grader_args: list[str] | None = None,
    *,
    min_score: float = 1.0,
    baseline: float | None = None,
    pin_sha: str | None = None,
    timeout: float = 600.0,
) -> HeldoutResult:
    """Run the C0 held-out gate. See module docstring for the guarantee.

    The grader is invoked by ABSOLUTE path from cwd=``/`` with PYTHONPATH/
    PYTHONSTARTUP/PYTHONHOME stripped, so nothing in ``work_dir`` is importable
    or on the path. Threshold + ratchet are enforced here, outside the agent's reach.
    """
    grader_args = grader_args or []

    # 1) C0 pre-flight — prove unreachability before trusting any score.
    violation = preflight(work_dir, grader_path)
    if violation is not None:
        return HeldoutResult(False, None, True, f"STRUCTURAL: {violation}")

    # 2) content-address (C2) — a changed grader is a violation.
    if pin_sha is not None:
        got = _sha256(grader_path)
        if got != pin_sha:
            return HeldoutResult(
                False, None, True,
                f"STRUCTURAL: grader sha256 {got} != pinned {pin_sha} — evaluator modified",
            )

    # 3) run from clean cwd + scrubbed env.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME")}
    try:
        proc = subprocess.run(
            [os.path.realpath(grader_path), *grader_args],
            cwd="/", env=env, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return HeldoutResult(False, None, False, f"grader timed out after {timeout}s")

    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        tail = " ".join(out.splitlines()[-5:])
        return HeldoutResult(False, None, False, f"grader exited {proc.returncode}: {tail}")

    # 4) parse the held-out score (last SCORE: line wins).
    matches = _SCORE_RE.findall(out)
    if not matches:
        return HeldoutResult(False, None, True,
                             "grader emitted no parseable 'SCORE: <float>' line")
    score = float(matches[-1])

    # 5) threshold + ratchet, enforced outside the agent's reach.
    need = max(min_score, baseline) if baseline is not None else min_score
    if score >= need:
        return HeldoutResult(True, score, False,
                             f"held-out score {score} >= threshold {need} (grader unreachable, clean cwd)")
    return HeldoutResult(False, score, False, f"held-out score {score} < threshold {need}")
