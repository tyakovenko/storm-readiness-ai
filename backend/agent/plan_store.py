"""Persistent SQLite-backed Human-in-the-Loop plan approval store.

Enforces valid status transitions:
  draft -> modified -> approved -> deployed
  (or draft/modified -> rejected)
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "plans.db"

VALID_STATUSES = {"draft", "modified", "approved", "deployed", "rejected"}
TRANSITIONS = {
    "draft": {"modified", "approved", "rejected"},
    "modified": {"modified", "approved", "rejected"},
    "approved": {"deployed", "modified", "rejected"},
    "deployed": set(),
    "rejected": {"draft", "modified"},
}


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                plan_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                county TEXT NOT NULL,
                status TEXT NOT NULL,
                author TEXT,
                approver TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approved_at TEXT,
                notes TEXT,
                inputs_json TEXT NOT NULL,
                allocations_json TEXT NOT NULL,
                audit_trail_json TEXT NOT NULL
            )
        """)
        conn.commit()


def create_plan(agent_id: str,
                county: str,
                inputs: dict,
                allocations: dict,
                author: str = "Emergency Manager",
                notes: str = "") -> dict:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    plan_id = f"plan_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    status = "draft"
    audit = [{
        "status": status,
        "timestamp": now,
        "by": author,
        "comment": "Plan created in draft state"
    }]

    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO plans (
                plan_id, agent_id, county, status, author, approver,
                created_at, updated_at, approved_at, notes,
                inputs_json, allocations_json, audit_trail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                plan_id, agent_id, county, status, author, None,
                now, now, None, notes,
                json.dumps(inputs), json.dumps(allocations), json.dumps(audit)
            ),
        )
        conn.commit()

    return get_plan(plan_id)


def get_plan(plan_id: str) -> dict | None:
    init_db()
    with _get_connection() as conn:
        cur = conn.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["inputs"] = json.loads(d.pop("inputs_json"))
        d["allocations"] = json.loads(d.pop("allocations_json"))
        d["audit_trail"] = json.loads(d.pop("audit_trail_json"))
        return d


def list_plans(agent_id: str | None = None, status: str | None = None) -> list[dict]:
    init_db()
    with _get_connection() as conn:
        query = "SELECT * FROM plans WHERE 1=1"
        params = []
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC"
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["inputs"] = json.loads(d.pop("inputs_json"))
            d["allocations"] = json.loads(d.pop("allocations_json"))
            d["audit_trail"] = json.loads(d.pop("audit_trail_json"))
            out.append(d)
        return out


def update_plan(plan_id: str,
                status: str | None = None,
                approver: str | None = None,
                notes: str | None = None,
                new_inputs: dict | None = None,
                new_allocations: dict | None = None,
                user: str = "Operator") -> dict:
    plan = get_plan(plan_id)
    if not plan:
        raise KeyError(f"Plan not found: {plan_id}")

    current_status = plan["status"]
    target_status = status or current_status
    if target_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {target_status}. Must be one of {VALID_STATUSES}")

    if target_status != current_status and target_status not in TRANSITIONS.get(current_status, set()):
        raise ValueError(f"Illegal transition: {current_status} -> {target_status}")

    now = datetime.now(timezone.utc).isoformat()
    audit = plan["audit_trail"]
    approved_at = plan.get("approved_at")
    final_approver = plan.get("approver")

    if target_status != current_status:
        comment = f"Status changed from {current_status} to {target_status}"
        if notes:
            comment += f": {notes}"
        audit.append({
            "status": target_status,
            "timestamp": now,
            "by": approver or user,
            "comment": comment
        })
        if target_status == "approved":
            approved_at = now
            final_approver = approver or user

    final_inputs = new_inputs if new_inputs is not None else plan["inputs"]
    final_allocations = new_allocations if new_allocations is not None else plan["allocations"]
    final_notes = notes if notes is not None else plan.get("notes", "")

    with _get_connection() as conn:
        conn.execute(
            """
            UPDATE plans SET
                status = ?,
                approver = ?,
                approved_at = ?,
                updated_at = ?,
                notes = ?,
                inputs_json = ?,
                allocations_json = ?,
                audit_trail_json = ?
            WHERE plan_id = ?
        """,
            (
                target_status,
                final_approver,
                approved_at,
                now,
                final_notes,
                json.dumps(final_inputs),
                json.dumps(final_allocations),
                json.dumps(audit),
                plan_id
            ),
        )
        conn.commit()

    return get_plan(plan_id)
