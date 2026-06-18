from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import autocontext.server.knowledge_api as api

    monkeypatch.setenv("AUTOCONTEXT_KNOWLEDGE_ROOT", str(tmp_path / "knowledge"))
    monkeypatch.setenv("AUTOCONTEXT_SKILLS_ROOT", str(tmp_path / "skills"))
    api._ctx = None
    api._solve_mgr = None
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _playbook(*lessons: str) -> str:
    bullets = "\n".join(f"- {lesson}" for lesson in lessons)
    return f"intro\n<!-- LESSONS_START -->\n{bullets}\n<!-- LESSONS_END -->\noutro"


def _seed(client: TestClient) -> None:
    import autocontext.server.knowledge_api as api

    ctx = api._get_ctx()
    ctx.artifacts.write_playbook("scn", _playbook("fresh", "held"))


def test_lifecycle_endpoint_derives_from_playbook(client: TestClient) -> None:
    _seed(client)
    resp = client.get("/api/knowledge/scn/lifecycle")
    assert resp.status_code == 200
    body = resp.json()
    assert {les["text"] for les in body["active"]} == {"fresh", "held"}
    assert body["pending"] == []


def test_approve_endpoint_is_noop_for_live_lesson(client: TestClient) -> None:
    _seed(client)
    lesson_id = client.get("/api/knowledge/scn/lifecycle").json()["active"][0]["id"]
    resp = client.post(f"/api/knowledge/scn/lessons/{lesson_id}/approve")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "active"}


def test_reject_endpoint_removes_live_lesson(client: TestClient) -> None:
    _seed(client)
    lesson = next(
        les for les in client.get("/api/knowledge/scn/lifecycle").json()["active"] if les["text"] == "held"
    )
    resp = client.post(f"/api/knowledge/scn/lessons/{lesson['id']}/reject")
    assert resp.status_code == 200 and resp.json()["ok"] is True
    after = client.get("/api/knowledge/scn/lifecycle").json()
    assert {les["text"] for les in after["active"]} == {"fresh"}


def test_curate_delete_endpoint(client: TestClient) -> None:
    _seed(client)
    lesson_id = client.get("/api/knowledge/scn/lifecycle").json()["active"][0]["id"]
    resp = client.post(f"/api/knowledge/scn/lessons/{lesson_id}/curate", json={"action": "delete"})
    assert resp.status_code == 200 and resp.json() == {"ok": True, "status": "deleted"}


def test_curate_stale_endpoint(client: TestClient) -> None:
    _seed(client)
    lesson_id = client.get("/api/knowledge/scn/lifecycle").json()["active"][0]["id"]
    resp = client.post(f"/api/knowledge/scn/lessons/{lesson_id}/curate", json={"action": "stale"})
    assert resp.status_code == 200 and resp.json() == {"ok": True, "status": "stale"}
    after = client.get("/api/knowledge/scn/lifecycle").json()
    assert after["stale"]


def test_curate_dead_end_endpoint(client: TestClient) -> None:
    _seed(client)
    lesson_id = client.get("/api/knowledge/scn/lifecycle").json()["active"][0]["id"]
    resp = client.post(f"/api/knowledge/scn/lessons/{lesson_id}/curate", json={"action": "deadEnd"})
    assert resp.status_code == 200 and resp.json() == {"ok": True, "status": "deadEnd"}
    assert client.get("/api/knowledge/scn/lifecycle").json()["deadEnd"]


def test_curate_missing_is_404(client: TestClient) -> None:
    _seed(client)
    resp = client.post("/api/knowledge/scn/lessons/nope/curate", json={"action": "delete"})
    assert resp.status_code == 404


def test_path_traversal_rejected(client: TestClient, tmp_path: Path) -> None:
    resp = client.post("/api/knowledge/%2E%2E/lessons/p/approve")
    assert resp.status_code != 200
    assert not (tmp_path / "pending_lessons.json").exists()
    assert not (tmp_path / "lessons.json").exists()


def test_approve_missing_is_404(client: TestClient) -> None:
    _seed(client)
    resp = client.post("/api/knowledge/scn/lessons/nope/approve")
    assert resp.status_code == 404


def test_reject_missing_is_404(client: TestClient) -> None:
    _seed(client)
    resp = client.post("/api/knowledge/scn/lessons/nope/reject")
    assert resp.status_code == 404
