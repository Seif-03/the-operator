from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_tracker_crud(tmp_path, monkeypatch):
    import app.server as srv

    monkeypatch.setattr(srv, "TRACKER_FILE", tmp_path / "applications.json")
    client = TestClient(srv.app)

    created = client.post("/api/tracker", json={
        "user_id": "tracker-test",
        "title": "Working Student, Data",
        "company": "Example GmbH",
        "applied_at": "2026-11-20",
        "url": "https://jobs.example/123",
    })
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["status"] == "applied"

    listed = client.get("/api/tracker", params={"user_id": "tracker-test"})
    assert [item["id"] for item in listed.json()] == [entry["id"]]

    updated = client.patch(f"/api/tracker/{entry['id']}", json={
        "status": "interview",
        "follow_up_date": "2026-11-27",
        "notes": "Technical interview",
    })
    assert updated.status_code == 200
    assert updated.json()["status"] == "interview"
    assert updated.json()["follow_up_date"] == "2026-11-27"
    assert updated.json()["notes"] == "Technical interview"

    assert client.delete(f"/api/tracker/{entry['id']}").json() == {"deleted": True}
    assert client.delete(f"/api/tracker/{entry['id']}").status_code == 404


def test_tracker_imports_successful_run_steps_once_and_keeps_user_status(tmp_path, monkeypatch):
    import app.server as srv

    monkeypatch.setattr(srv, "TRACKER_FILE", tmp_path / "applications.json")
    fill_step = {"tool": "fill_application_form", "input": {"job_id": "J-1001"}, "ok": True, "output": {}}
    run = SimpleNamespace(
        id="20261120-120000-test01",
        started=datetime(2026, 11, 20).timestamp(),
        trajectory=[fill_step],
        ctx=SimpleNamespace(
            profile=SimpleNamespace(user_id="tracker-test", name="Test User"),
            jobs={"J-1001": {"title": "Data Intern", "company": "Example GmbH", "location": "Berlin"}},
        ),
    )
    monkeypatch.setattr(srv, "RUNS", {run.id: run})
    client = TestClient(srv.app)

    first = client.get("/api/tracker", params={"user_id": "tracker-test"}).json()
    assert len(first) == 1
    assert first[0]["status"] == "ready_to_submit"
    assert first[0]["title"] == "Data Intern"

    run.trajectory.append({"tool": "browser_submit_application", "input": {"job_id": "J-1001"}, "ok": True, "output": {}})
    second = client.get("/api/tracker", params={"user_id": "tracker-test"}).json()
    assert len(second) == 1
    assert second[0]["status"] == "applied"

    client.patch(f"/api/tracker/{second[0]['id']}", json={
        "status": "interview", "follow_up_date": None, "notes": "Invite received",
    })
    refreshed = client.get("/api/tracker", params={"user_id": "tracker-test"}).json()
    assert len(refreshed) == 1
    assert refreshed[0]["status"] == "interview"
    assert refreshed[0]["notes"] == "Invite received"

    assert client.delete(f"/api/tracker/{refreshed[0]['id']}").status_code == 200
    assert client.get("/api/tracker", params={"user_id": "tracker-test"}).json() == []
