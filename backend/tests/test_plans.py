"""Tests for Human-in-the-Loop plan approval workflow and critical facilities (Gaps 2 & 3)."""

import pytest
from fastapi.testclient import TestClient

from agent import plan_store
from agent.hurricane_tools import HurricaneToolset
from app import app


def test_plan_lifecycle_and_transitions():
    # 1. Create a draft plan
    plan = plan_store.create_plan(
        agent_id="lee-hurricane",
        county="Lee County",
        inputs={"exclude_surge": True, "unavailable_shelters": ["Test Shelter"]},
        allocations={"water_gallons": 196162, "generators_kw": 6538, "beds": 34070},
        author="Ops Chief",
        notes="Draft review",
    )
    plan_id = plan["plan_id"]
    assert plan["status"] == "draft"
    assert len(plan["audit_trail"]) == 1

    # 2. Modify the plan
    mod = plan_store.update_plan(
        plan_id=plan_id,
        status="modified",
        notes="Adjusted shelter closures",
        new_inputs={"exclude_surge": True, "unavailable_shelters": ["Test Shelter", "Site B"]},
    )
    assert mod["status"] == "modified"
    assert len(mod["audit_trail"]) == 2

    # 3. Approve the plan
    appr = plan_store.update_plan(
        plan_id=plan_id,
        status="approved",
        approver="Director Johnson",
        notes="Signed off by Incident Commander",
    )
    assert appr["status"] == "approved"
    assert appr["approver"] == "Director Johnson"
    assert appr["approved_at"] is not None
    assert len(appr["audit_trail"]) == 3

    # 4. Deploy the plan
    dep = plan_store.update_plan(
        plan_id=plan_id,
        status="deployed",
        notes="Staging orders dispatched to depots",
    )
    assert dep["status"] == "deployed"

    # 5. Verify illegal transition from deployed -> draft raises ValueError
    with pytest.raises(ValueError, match="Illegal transition"):
        plan_store.update_plan(plan_id=plan_id, status="draft")


def test_plan_api_endpoints():
    client = TestClient(app)

    # List plans
    r = client.get("/api/plans")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # Create plan via API
    r_create = client.post("/api/plans", json={
        "agent_id": "harris-hurricane",
        "county": "Harris County",
        "inputs": {"max_trucks": 50},
        "allocations": {"beds": 12000, "water_gallons": 100000},
        "author": "Emergency Planner",
        "notes": "Initial storm draft"
    })
    assert r_create.status_code == 200
    data = r_create.json()
    pid = data["plan_id"]
    assert data["status"] == "draft"

    # Get single plan
    r_get = client.get(f"/api/plans/{pid}")
    assert r_get.status_code == 200
    assert r_get.json()["plan_id"] == pid

    # Approve plan via API
    r_appr = client.post(f"/api/plans/{pid}/approve", json={
        "approver": "County Judge Lina Hidalgo",
        "notes": "Approved for emergency mobilization"
    })
    assert r_appr.status_code == 200
    assert r_appr.json()["status"] == "approved"
    assert r_appr.json()["approver"] == "County Judge Lina Hidalgo"


def test_critical_facilities_and_tracts_in_assets():
    ts = HurricaneToolset("12071")
    assets = ts.query_assets()

    # Check critical facilities
    assert assets["critical_facilities_total"] >= 5
    assert assets["hospitals_total"] >= 3
    assert "critical_facilities" in assets
    assert any(f["type"] == "hospital" for f in assets["critical_facilities"])
    assert any(f["type"] == "fire_station" for f in assets["critical_facilities"])
    assert any(f["type"] == "eoc" for f in assets["critical_facilities"])

    # Check Census tracts
    assert "census_tracts" in assets
    assert assets["census_tracts"]["total_tracts"] == 128
    assert assets["census_tracts"]["high_svi_tracts"] == 32
    assert assets["census_tracts"]["surge_exposed_tracts"] == 46

    # Test filtering by facility_type="hospital"
    hosp_only = ts.query_assets(facility_type="hospital")
    assert all(f["type"] == "hospital" for f in hosp_only["critical_facilities"])
    assert len(hosp_only["critical_facilities"]) == assets["hospitals_total"]


def test_plan_tools_in_toolset():
    ts = HurricaneToolset("12071")
    save_res = ts.save_plan(notes="Test auto-save from tool", author="Agent System")
    assert save_res["status"] == "draft"
    pid = save_res["plan_id"]

    appr_res = ts.approve_plan(plan_id=pid, approver="EOC Manager", notes="Approved via tool")
    assert appr_res["status"] == "approved"
    assert appr_res["approver"] == "EOC Manager"
