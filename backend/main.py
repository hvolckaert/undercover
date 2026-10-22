"""The UnderCover backend."""

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException

from backend import db

INSTRUCTIONS = Path(__file__).resolve().parent / "instructions.md"

app = FastAPI(title="UnderCover")

Db = Annotated[sqlite3.Connection, Depends(db.get_db)]


def claim_row(conn: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    """Return a claim's row, or raise 404."""
    row = conn.execute(
        "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No claim {claim_id}")
    return row


def found(item: Any, what: str) -> Any:
    """Return a record, or raise 404 if it is missing."""
    if item is None:
        raise HTTPException(404, f"No {what}")
    return item


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(conn: Db) -> list[dict[str, Any]]:
    """List the claims queue with where each claim stands."""
    rows = conn.execute("SELECT * FROM claims ORDER BY claim_id").fetchall()
    claims = []
    for row in rows:
        body = json.loads(row["body"])
        customer = db.record(conn, "customer", body["customer_id"])
        decision = json.loads(row["decision"]) if row["decision"] else None
        claims.append(
            {
                "claim_id": row["claim_id"],
                "customer_name": customer["name"],
                "claim_type": body["claim_type"],
                "summary": body["summary"],
                "submitted_on": body["submitted_on"],
                "amount_claimed": body["amount_claimed"],
                "status": row["status"],
                "decision": decision["decision"] if decision else None,
                "payout": decision["payout"] if decision else None,
            }
        )
    return claims


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, conn: Db) -> dict[str, Any]:
    """Get one claim in full, with its decision, sign-off and payment."""
    row = claim_row(conn, claim_id)
    payment = conn.execute(
        "SELECT amount, paid_at FROM payments WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    return {
        **json.loads(row["body"]),
        "status": row["status"],
        "decision": json.loads(row["decision"]) if row["decision"] else None,
        "sign_off": json.loads(row["sign_off"]) if row["sign_off"] else None,
        "payment": dict(payment) if payment else None,
    }


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, conn: Db) -> dict[str, Any]:
    """Get a policy with its plan's limits and its add-ons."""
    policy = found(db.record(conn, "policy", policy_id), f"policy {policy_id}")
    plan = db.record(conn, "plan", policy["plan"])
    plan["deductible_applies_to"] = db.record(conn, "deductible", "applies_to")
    add_ons = [db.record(conn, "add_on", a) for a in policy["add_ons"]]
    return {**policy, "plan_details": plan, "add_on_details": add_ons}


@app.get("/api/customers/{customer_id}", operation_id="get_customer")
def get_customer(customer_id: str, conn: Db) -> dict[str, Any]:
    """Get a customer with their earlier claims."""
    return found(db.record(conn, "customer", customer_id), f"customer {customer_id}")


@app.get("/api/policy-wording", operation_id="get_policy_wording")
def get_policy_wording() -> dict[str, str]:
    """Get the policy wording, the contract with the customer."""
    return {"wording": (db.DATA / "policy_wording.md").read_text(encoding="utf-8")}


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions() -> dict[str, str]:
    """Get the UnderCover Agent's instructions."""
    return {"instructions": INSTRUCTIONS.read_text(encoding="utf-8")}


@app.get("/api/handlers", operation_id="list_handlers")
def list_handlers(conn: Db) -> list[dict[str, Any]]:
    """List the claims handlers."""
    return db.records(conn, "handler")
