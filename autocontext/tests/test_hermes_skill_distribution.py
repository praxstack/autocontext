"""AC-712: distribution path for the Hermes ``autocontext`` skill.

The single source of truth for the Hermes SKILL.md content lives in
:func:`autocontext.hermes.skill.render_autocontext_skill`. AC-712
ships a committed snapshot of that under ``skills/autocontext/`` at
the repo root so Hermes users can install via:

* a stable raw URL (``hermes skills install <url>`` or ``curl + cp``),
* a shallow clone of just that path,
* the existing :code:`autoctx hermes export-skill` CLI (which writes
  the same content).

The tests pin two invariants:

1. The committed ``SKILL.md`` matches :func:`render_autocontext_skill`
   byte-for-byte (DRY: there is only one source of truth, the
   committed file is a snapshot of it).
2. Every reference returned by
   :func:`autocontext.hermes.references.list_references` has a
   matching committed file under ``skills/autocontext/references/``
   whose content equals :func:`render_reference(name)`.

A pre-commit / CI failure here means the renderer drifted from the
committed snapshot. Re-run ``autoctx hermes export-skill --output
skills/autocontext/SKILL.md --with-references --force`` from the
repo root to regenerate.
"""

from __future__ import annotations

from pathlib import Path

from autocontext.hermes.references import list_references, render_reference
from autocontext.hermes.skill import render_autocontext_skill


def _repo_root() -> Path:
    """Locate the repo root from the test file (parents[2] = repo root)."""
    return Path(__file__).resolve().parents[2]


def test_committed_skill_md_exists() -> None:
    """The committed snapshot must exist at the documented location."""
    path = _repo_root() / "skills" / "autocontext" / "SKILL.md"
    assert path.is_file(), f"missing committed skill at {path}"


def test_committed_skill_md_matches_rendered() -> None:
    """The committed snapshot must equal :func:`render_autocontext_skill`
    byte-for-byte. Re-run ``autoctx hermes export-skill --output
    skills/autocontext/SKILL.md --force`` to regenerate."""
    path = _repo_root() / "skills" / "autocontext" / "SKILL.md"
    committed = path.read_text(encoding="utf-8")
    rendered = render_autocontext_skill()
    assert committed == rendered, (
        "committed skills/autocontext/SKILL.md drifted from "
        "render_autocontext_skill(); re-run `autoctx hermes export-skill "
        "--output skills/autocontext/SKILL.md --with-references --force`."
    )


def test_every_reference_has_a_committed_snapshot() -> None:
    """Every reference returned by list_references() must have a
    corresponding file in skills/autocontext/references/."""
    references_dir = _repo_root() / "skills" / "autocontext" / "references"
    assert references_dir.is_dir(), f"missing references dir at {references_dir}"
    for name in list_references():
        ref_path = references_dir / f"{name}.md"
        assert ref_path.is_file(), f"missing committed reference {ref_path}"


def test_committed_references_match_rendered() -> None:
    """Each committed reference equals :func:`render_reference(name)`."""
    references_dir = _repo_root() / "skills" / "autocontext" / "references"
    for name in list_references():
        ref_path = references_dir / f"{name}.md"
        committed = ref_path.read_text(encoding="utf-8")
        rendered = render_reference(name)
        assert committed == rendered, (
            f"committed reference {ref_path.name} drifted from "
            f"render_reference({name!r}); re-export via "
            "`autoctx hermes export-skill --output skills/autocontext/SKILL.md "
            "--with-references --force`."
        )


def test_no_extra_reference_files_committed() -> None:
    """Reject orphan references that aren't listed by
    :func:`list_references`. Catches the case where a reference was
    renamed but the old file stayed behind."""
    references_dir = _repo_root() / "skills" / "autocontext" / "references"
    if not references_dir.is_dir():
        return  # covered by other tests; nothing to enforce here.
    expected = {f"{name}.md" for name in list_references()}
    actual = {p.name for p in references_dir.glob("*.md")}
    extras = actual - expected
    assert not extras, f"orphan reference files: {sorted(extras)}"
