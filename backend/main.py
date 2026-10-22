"""The UnderCover backend."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

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


class Decision(BaseModel):
    """The agent's decision on a claim."""

    decision: Literal["approve", "decline", "refer"]
    payout: float = Field(ge=0)
    calculation: str
    reason: str
    policy_section: str

    @model_validator(mode="after")
    def no_payout_unless_approved(self) -> Self:
        if self.decision != "approve" and self.payout != 0:
            raise ValueError("Only an approved claim has a payout")
        return self


class Step(BaseModel):
    """One step the agent took on a claim."""

    thread_id: str
    kind: Literal["tool_call", "tool_result", "reply", "error"]
    content: str


class Payment(BaseModel):
    """A payment on an approved claim."""

    amount: float = Field(gt=0)


class SignOff(BaseModel):
    """A handler's sign-off on a payout over the limit."""

    handler_id: str


def now() -> str:
    """Return the time now in UTC, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def approval_limit(conn: sqlite3.Connection) -> float:
    """Return the payout above which a handler must sign off."""
    return db.record(conn, "company", "company")["payout_approval_limit"]


def pay(conn: sqlite3.Connection, claim_id: str, amount: float) -> None:
    """Record a payment on a claim."""
    conn.execute(
        "INSERT INTO payments (claim_id, amount, paid_at) VALUES (?, ?, ?)",
        (claim_id, amount, now()),
    )


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


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: Db) -> list[dict[str, Any]]:
    """List the steps the agent has taken on a claim, oldest first."""
    claim_row(conn, claim_id)
    rows = conn.execute(
        "SELECT * FROM steps WHERE claim_id = ? ORDER BY step_id", (claim_id,)
    ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/claims/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, step: Step, conn: Db) -> dict[str, str]:
    """Record one step the agent took on a claim."""
    claim_row(conn, claim_id)
    conn.execute(
        "INSERT INTO steps (claim_id, thread_id, kind, content, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (claim_id, step.thread_id, step.kind, step.content, now()),
    )
    return {"status": "recorded"}


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, decision: Decision, conn: Db) -> dict[str, str]:
    """Record the decision on a claim; a payout over the limit waits for sign-off."""
    if claim_row(conn, claim_id)["decision"]:
        raise HTTPException(409, f"Claim {claim_id} already has a decision")
    over_limit = decision.payout > approval_limit(conn)
    status = "waiting_for_signoff" if over_limit else "decided"
    conn.execute(
        "UPDATE claims SET decision = ?, status = ? WHERE claim_id = ?",
        (decision.model_dump_json(), status, claim_id),
    )
    return {"status": status}


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, payment: Payment, conn: Db) -> dict[str, str]:
    """Pay the approved payout on a claim; over the limit it needs a sign-off."""
    row = claim_row(conn, claim_id)
    decision = json.loads(row["decision"]) if row["decision"] else None
    if decision is None or decision["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} is not approved")
    if payment.amount != decision["payout"]:
        raise HTTPException(409, f"The approved payout is {decision['payout']:.2f}")
    if row["status"] == "waiting_for_signoff":
        raise HTTPException(409, "This payout needs a handler's sign-off")
    if get_claim(claim_id, conn)["payment"]:
        raise HTTPException(409, f"Claim {claim_id} is already paid")
    pay(conn, claim_id, payment.amount)
    return {"status": "paid"}


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off")
def sign_off(claim_id: str, request: SignOff, conn: Db) -> dict[str, str]:
    """Sign off a payout over the limit, which releases the payment."""
    row = claim_row(conn, claim_id)
    if row["status"] != "waiting_for_signoff":
        raise HTTPException(409, f"Claim {claim_id} is not waiting for sign-off")
    handler = found(
        db.record(conn, "handler", request.handler_id), f"handler {request.handler_id}"
    )
    if not handler["can_approve_over_limit"]:
        raise HTTPException(403, f"{handler['name']} cannot sign off this payout")
    signed = {"handler_id": handler["handler_id"], "name": handler["name"], "at": now()}
    conn.execute(
        "UPDATE claims SET sign_off = ?, status = 'decided' WHERE claim_id = ?",
        (json.dumps(signed), claim_id),
    )
    pay(conn, claim_id, json.loads(row["decision"])["payout"])
    return {"status": "decided"}
