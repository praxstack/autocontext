from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync_release_surfaces.py"


def _load_sync_module() -> Any:
    spec = importlib.util.spec_from_file_location("sync_release_surfaces", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_manifest_syncs_public_surfaces() -> None:
    sync = _load_sync_module()
    manifest = sync.load_release_manifest()
    issues = sync.check_release_surfaces(manifest)

    assert issues == []


def test_release_manifest_renders_whats_new_asset() -> None:
    sync = _load_sync_module()
    manifest = sync.ReleaseManifest(
        core_version="1.2.3",
        pi_version="0.8.0",
        pi_autoctx_dependency="^0.8.0",
        whats_new=("**One** thing.", "**Two** thing."),
    )

    assert sync.render_whats_new_asset(manifest) == "**One** thing.\n**Two** thing.\n"
    assert sync.render_whats_new_heading(manifest) == "What's New in 1.2.3"
