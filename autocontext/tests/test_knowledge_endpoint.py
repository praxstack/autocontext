"""Tests for the /api/knowledge/{scenario} read + write endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autocontext.server.app import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTOCONTEXT_KNOWLEDGE_ROOT", str(tmp_path / "knowledge"))
    monkeypatch.setenv("AUTOCONTEXT_DB_PATH", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setenv("AUTOCONTEXT_AGENT_PROVIDER", "deterministic")
    return TestClient(create_app())


def test_put_writes_knowledge_files_and_get_round_trips(client: TestClient, tmp_path: Path) -> None:
    payload = {"playbook": "## Plan", "hints": "- keep the flag", "deadEnds": "- brute force"}
    response = client.put("/api/knowledge/grid_ctf", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["scenario"] == "grid_ctf"
    assert sorted(body["written"]) == ["dead_ends.md", "hints.md", "playbook.md"]

    base = tmp_path / "knowledge" / "grid_ctf"
    assert (base / "playbook.md").read_text(encoding="utf-8") == "## Plan"
    assert (base / "dead_ends.md").read_text(encoding="utf-8") == "- brute force"

    got = client.get("/api/knowledge/grid_ctf").json()
    assert got["playbook"] == "## Plan"
    assert got["hints"] == "- keep the flag"
    assert got["deadEnds"] == "- brute force"


def test_put_writes_only_provided_string_fields(client: TestClient, tmp_path: Path) -> None:
    response = client.put("/api/knowledge/grid_ctf", json={"hints": "- only hints", "playbook": 42})
    assert response.status_code == 200
    assert response.json()["written"] == ["hints.md"]
    base = tmp_path / "knowledge" / "grid_ctf"
    assert (base / "hints.md").exists()
    assert not (base / "playbook.md").exists()


def test_put_rejects_invalid_scenario_ids(client: TestClient) -> None:
    assert client.put("/api/knowledge/bad!name", json={"hints": "x"}).status_code == 400
    assert client.put("/api/knowledge/dots..dots", json={"hints": "x"}).status_code == 400
    assert client.put(f"/api/knowledge/{'a' * 129}", json={"hints": "x"}).status_code == 400
