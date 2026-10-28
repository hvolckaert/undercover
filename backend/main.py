"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from agent import main as claim_agent
from backend import db

INSTRUCTIONS = Path(__file__).resolve().parent / "instructions"
DOCUMENTS = {"policy_wording": "policy_wording.md", "claims_manual": "claims_manual.md"}
MAX_ATTEMPTS = 2


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    recover()
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)

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


class Start(BaseModel):
    """The run starting work on a claim."""

    run_id: str


class Release(BaseModel):
    """Why a claim agent stopped before it decided a claim."""

    thread_id: str
    problem: str


class NewRun(BaseModel):
    """A run of the agent over the queue, capped at a number of claims."""

    max_claims: int = Field(ge=1)


class Todo(BaseModel):
    """One item on the agent's to-do list for a run."""

    task: str
    status: Literal["to_do", "in_progress", "done", "for_handler"]


class Todos(BaseModel):
    """The agent's whole to-do list for a run."""

    todos: list[Todo]


class Finish(BaseModel):
    """The agent's summary of a run, for the handlers."""

    summary: str


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
                "attempts": row["attempts"],
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


def sections(document: str) -> dict[str, dict[str, str]]:
    """Split a document on its numbered headings, keyed by the section number."""
    name = found(DOCUMENTS.get(document), f"document {document}")
    text = (db.DATA / name).read_text(encoding="utf-8")
    split = {}
    for part in text.split("\n## ")[1:]:
        number, _, title = part.partition("\n")[0].partition(". ")
        split[number] = {
            "document": document,
            "section": number,
            "title": title,
            "text": f"## {part.strip()}",
        }
    return split


@app.get("/api/documents", operation_id="list_sections")
def list_sections() -> dict[str, list[str]]:
    """List the sections of the policy wording and the claims manual."""
    return {
        document: [f"{s['section']}. {s['title']}" for s in sections(document).values()]
        for document in DOCUMENTS
    }


@app.get("/api/documents/search", operation_id="search_documents")
def search_documents(words: str) -> list[dict[str, str]]:
    """Find the paragraphs of the wording and the manual that hold all the words."""
    wanted = words.lower().split()
    return [
        {
            "document": section["document"],
            "section": section["section"],
            "title": section["title"],
            "paragraph": paragraph,
        }
        for document in DOCUMENTS
        for section in sections(document).values()
        for paragraph in section["text"].split("\n\n")
        if all(word in paragraph.lower() for word in wanted)
    ]


@app.get("/api/documents/{document}/sections/{section}", operation_id="read_section")
def read_section(document: str, section: str) -> dict[str, str]:
    """Read one section of the policy wording or the claims manual."""
    return found(sections(document).get(section), f"section {section} in {document}")


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions() -> dict[str, str]:
    """Get the agent's instructions for running the queue and for working a claim."""
    return {
        agent: (INSTRUCTIONS / f"{agent}.md").read_text(encoding="utf-8")
        for agent in ("queue", "claim")
    }


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
    add_step(conn, claim_id, step)
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


def add_step(conn: sqlite3.Connection, claim_id: str, step: Step) -> None:
    """Store one step the agent took on a claim."""
    conn.execute(
        "INSERT INTO steps (claim_id, thread_id, kind, content, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (claim_id, step.thread_id, step.kind, step.content, now()),
    )


def start(conn: sqlite3.Connection, claim_id: str, run_id: str | None) -> str:
    """Move a waiting claim to in progress and return its new thread id."""
    claim_row(conn, claim_id)
    thread_id = uuid4().hex
    started = conn.execute(
        "UPDATE claims SET status = 'in_progress', attempts = attempts + 1,"
        " run_id = ?, thread_id = ? WHERE claim_id = ? AND status = 'waiting'",
        (run_id, thread_id, claim_id),
    ).rowcount
    if not started:
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    return thread_id


def release(
    conn: sqlite3.Connection, claim_id: str, thread_id: str, problem: str
) -> str:
    """Put a claim back in the queue, or leave it for a handler on its last try."""
    row = claim_row(conn, claim_id)
    if row["status"] != "in_progress" or row["thread_id"] != thread_id:
        raise HTTPException(409, f"Claim {claim_id} is not in progress on this thread")
    status = "needs_handler" if row["attempts"] >= MAX_ATTEMPTS else "waiting"
    if status == "needs_handler":
        problem += f" Left for a handler after {row['attempts']} attempts."
    add_step(conn, claim_id, Step(thread_id=thread_id, kind="error", content=problem))
    conn.execute("UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id))
    return status


def recover() -> None:
    """Release the claims left in progress when the backend last stopped."""
    conn = db.connect()
    with conn:
        rows = conn.execute(
            "SELECT claim_id, thread_id FROM claims WHERE status = 'in_progress'"
        ).fetchall()
        for row in rows:
            release(
                conn,
                row["claim_id"],
                row["thread_id"],
                "The backend restarted while the agent was working on this claim.",
            )
        conn.execute(
            "UPDATE runs SET status = 'stopped', problem = ?, finished_at = ?"
            " WHERE status = 'running'",
            ("The backend restarted during the run.", now()),
        )
    conn.close()


def run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    """Return a run's row, or raise 404."""
    return found(
        conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone(),
        f"run {run_id}",
    )


def running(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    """Return a run's row, or raise 409 if it is not running."""
    run = run_row(conn, run_id)
    if run["status"] != "running":
        raise HTTPException(409, f"Run {run_id} is {run['status']}")
    return run


def started_by(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    """Return the claims a run has started, whatever they became."""
    return conn.execute(
        "SELECT claim_id, status FROM claims WHERE run_id = ? ORDER BY claim_id",
        (run_id,),
    ).fetchall()


def missed_claims(conn: sqlite3.Connection, run: sqlite3.Row) -> list[str]:
    """Return the waiting claims a run still has to work within its cap."""
    started = started_by(conn, run["run_id"])
    retries = [c["claim_id"] for c in started if c["status"] == "waiting"]
    room = run["max_claims"] - len(started)
    others = conn.execute(
        "SELECT claim_id FROM claims WHERE status = 'waiting'"
        " AND run_id IS NOT ? ORDER BY claim_id LIMIT ?",
        (run["run_id"], max(room, 0)),
    ).fetchall()
    return retries + [c["claim_id"] for c in others]


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, request: Start, conn: Db) -> dict[str, str]:
    """Start work on a waiting claim for a run and return the thread id."""
    run = running(conn, request.run_id)
    started = started_by(conn, request.run_id)
    retry = claim_id in [c["claim_id"] for c in started]
    if not retry and len(started) >= run["max_claims"]:
        raise HTTPException(
            409, f"The run has already started its {run['max_claims']} claims"
        )
    return {"thread_id": start(conn, claim_id, request.run_id)}


@app.post("/api/claims/{claim_id}/release", operation_id="release_claim")
def release_claim(claim_id: str, request: Release, conn: Db) -> dict[str, str]:
    """Release a claim the agent could not decide, with the problem."""
    return {"status": release(conn, claim_id, request.thread_id, request.problem)}


@app.post("/api/claims/{claim_id}/run", operation_id="run_agent")
def run_agent(claim_id: str, tasks: BackgroundTasks, conn: Db) -> dict[str, str]:
    """Start the UnderCover Agent on a waiting claim."""
    thread_id = start(conn, claim_id, None)
    conn.commit()
    tasks.add_task(claim_agent.work, claim_id, thread_id)
    return {"status": "in_progress", "thread_id": thread_id}


def run_json(run: sqlite3.Row) -> dict[str, Any]:
    """Return a run as the API shows it."""
    return {**dict(run), "todos": json.loads(run["todos"])}


def work_queue(run_id: str, max_claims: int) -> None:
    """Run the agent on the queue; stop the run if it ends without finishing."""
    try:
        claim_agent.run_queue(run_id, max_claims)
        problem = "The agent ended the run without finishing it."
    except Exception as error:
        problem = f"The run stopped with an error: {error}"
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE runs SET status = 'stopped', problem = ?, finished_at = ?"
            " WHERE run_id = ? AND status = 'running'",
            (problem, now(), run_id),
        )
    conn.close()


@app.post("/api/runs", operation_id="start_run")
def start_run(request: NewRun, tasks: BackgroundTasks, conn: Db) -> dict[str, Any]:
    """Start the UnderCover Agent on the queue, working at most max_claims claims."""
    if conn.execute("SELECT 1 FROM runs WHERE status = 'running'").fetchone():
        raise HTTPException(409, "A run is already running")
    run_id = uuid4().hex
    conn.execute(
        "INSERT INTO runs (run_id, max_claims, status, todos, started_at)"
        " VALUES (?, ?, 'running', '[]', ?)",
        (run_id, request.max_claims, now()),
    )
    conn.commit()
    tasks.add_task(work_queue, run_id, request.max_claims)
    return run_json(run_row(conn, run_id))


@app.get("/api/runs/latest", operation_id="get_latest_run")
def get_latest_run(conn: Db) -> dict[str, Any] | None:
    """Get the latest run with its to-do list and summary, or null if none."""
    run = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return run_json(run) if run else None


@app.put("/api/runs/{run_id}/todos", operation_id="write_todos")
def write_todos(run_id: str, request: Todos, conn: Db) -> dict[str, str]:
    """Replace the agent's to-do list for a running run."""
    running(conn, run_id)
    todos = json.dumps([todo.model_dump() for todo in request.todos])
    conn.execute("UPDATE runs SET todos = ? WHERE run_id = ?", (todos, run_id))
    return {"status": "saved"}


@app.post("/api/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: str, request: Finish, conn: Db) -> dict[str, str]:
    """Finish a run with a summary; refused while claims within its cap are missed."""
    missed = missed_claims(conn, running(conn, run_id))
    if missed:
        raise HTTPException(
            409, f"Claims still to work within the cap: {', '.join(missed)}"
        )
    conn.execute(
        "UPDATE runs SET status = 'finished', summary = ?, finished_at = ?"
        " WHERE run_id = ?",
        (request.summary, now(), run_id),
    )
    return {"status": "finished"}
