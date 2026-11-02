import pytest
import json
import os
import sqlite3
import tempfile
import app as flask_app


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_aether.sqlite3"
    flask_app.DB = str(db_path)
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as client:
        yield client


def test_health_endpoint(client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"status": "ok"}


def test_health_exposes_only_valid_deployed_revision(client, monkeypatch):
    expected = "aB" * 20
    monkeypatch.setenv("RENDER_GIT_COMMIT", expected)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "revision": expected.lower()}


@pytest.mark.parametrize("invalid", [
    "", "not-a-git-sha", "a" * 39, "a" * 41,
    "z" * 40, "a" * 39 + "\\n", "SECRET=value",
])
def test_health_never_reflects_unvalidated_revision(client, monkeypatch, invalid):
    monkeypatch.setenv("RENDER_GIT_COMMIT", invalid)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert invalid.encode() not in response.data if invalid else True


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"AETHER" in response.data


def test_api_results_empty_and_run(client):
    response = client.get("/api/results")
    assert response.status_code == 200
    assert response.get_json() == []

    post_resp = client.post("/api/run")
    assert post_resp.status_code == 200
    res_data = post_resp.get_json()
    assert "estimate" in res_data
    assert "expected" in res_data
    assert "deviation" in res_data
    assert res_data["trials"] == 20000

    results_resp = client.get("/api/results")
    assert results_resp.status_code == 200
    results_list = results_resp.get_json()
    assert len(results_list) == 1
    assert results_list[0]["status"] == "completed"


def test_api_research_endpoint(client, tmp_path):
    res_file = tmp_path / "research.json"
    res_file.write_text(json.dumps([{"time": "2026-01-01T00:00:00Z", "experiments": []}]))
    flask_app.RESEARCH_JSON_PATH = res_file

    response = client.get("/api/research")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1


def test_research_archive_does_not_leak_json_parse_details(client, tmp_path, monkeypatch):
    archive = tmp_path / "private_archive.json"
    archive.write_text("{invalid archive")
    monkeypatch.setattr(flask_app, "RESEARCH_JSON_PATH", archive)

    response = client.get("/api/research")

    assert response.status_code == 500
    assert response.get_json() == {"error": "Research archive temporarily unavailable."}
    assert b"Expecting property name" not in response.data
    assert b"private_archive" not in response.data


def test_research_archive_does_not_leak_filesystem_details(client, monkeypatch):
    class UnreadableArchive:
        def exists(self):
            return True

        def read_text(self, encoding):
            raise OSError("sensitive-internal-directory/secret-archive")

    monkeypatch.setattr(flask_app, "RESEARCH_JSON_PATH", UnreadableArchive())

    response = client.get("/api/research")

    assert response.status_code == 500
    assert response.get_json() == {"error": "Research archive temporarily unavailable."}
    assert b"sensitive-internal-directory" not in response.data
