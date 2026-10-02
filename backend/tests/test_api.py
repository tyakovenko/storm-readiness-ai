"""Tests for FastAPI backend server endpoints."""

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    os.environ["LLM_MODEL"] = "mock"
    from backend.app import app
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["model"] == "mock"
    assert data["mock"] is True


def test_storm_endpoint(client):
    r = client.get("/api/storm")
    assert r.status_code == 200
    data = r.json()
    assert "advisory" in data
    assert "scenarios" in data
    assert "enso" in data
    assert data["advisory"]["storm_name"] is not None


def test_impact_endpoint(client):
    r = client.get("/api/impact?fips=12075")
    assert r.status_code == 200
    data = r.json()
    assert "counties" in data
    assert len(data["counties"]) == 1
    assert data["counties"][0]["fips"] == "12075"


def test_staging_endpoint(client):
    r = client.get("/api/staging?max_trucks=6")
    assert r.status_code == 200
    data = r.json()
    assert data["trucks_available"] == 6
    assert "allocations" in data
    assert "shelter_beds_available" in data


def test_chat_endpoint(client):
    r = client.post("/api/chat", json={"message": "Which counties are most at risk?"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "passed"
    assert "answer" in data
    assert len(data["sources"]) > 0
