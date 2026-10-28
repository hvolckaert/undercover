from fastapi.testclient import TestClient

from backend import db
from backend import main as backend
from backend.main import app

client = TestClient(app)


def start(claim_id, run_id="run-1"):
    return client.post(f"/api/claims/{claim_id}/start", json={"run_id": run_id})


def release(claim_id, thread_id, problem="The model timed out."):
    return client.post(
        f"/api/claims/{claim_id}/release",
        json={"thread_id": thread_id, "problem": problem},
    )


def claim(claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def row(claim_id):
    conn = db.connect()
    found = dict(
        conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
    )
    conn.close()
    return found


def test_start_a_waiting_claim():
    thread_id = start("CLM-1001").json()["thread_id"]
    assert claim("CLM-1001")["status"] == "in_progress"
    started = row("CLM-1001")
    assert started["attempts"] == 1
    assert started["run_id"] == "run-1"
    assert started["thread_id"] == thread_id
    assert start("CLM-1001").status_code == 409
    assert start("CLM-9999").status_code == 404


def test_first_failure_goes_back_to_the_queue_and_second_to_a_handler():
    first = start("CLM-1002").json()["thread_id"]
    assert release("CLM-1002", first).json() == {"status": "waiting"}
    steps = client.get("/api/claims/CLM-1002/steps").json()
    assert [(s["kind"], s["content"]) for s in steps] == [
        ("error", "The model timed out.")
    ]

    second = start("CLM-1002").json()["thread_id"]
    assert second != first
    assert release("CLM-1002", second).json() == {"status": "needs_handler"}
    assert claim("CLM-1002")["status"] == "needs_handler"
    last = client.get("/api/claims/CLM-1002/steps").json()[-1]
    assert last["content"] == (
        "The model timed out. Left for a handler after 2 attempts."
    )
    assert start("CLM-1002").status_code == 409


def test_release_refusals():
    thread_id = start("CLM-1003").json()["thread_id"]
    assert release("CLM-1003", "another-thread").status_code == 409
    client.post(
        "/api/claims/CLM-1003/decision",
        json={
            "decision": "decline",
            "payout": 0,
            "calculation": "No payout on a decline.",
            "reason": "The loss is excluded.",
            "policy_section": "9. General exclusions",
        },
    )
    assert release("CLM-1003", thread_id).status_code == 409
    assert claim("CLM-1003")["status"] == "decided"
    assert client.get("/api/claims/CLM-1003/steps").json() == []


def test_a_decided_claim_is_never_started_again():
    start("CLM-1004")
    client.post(
        "/api/claims/CLM-1004/decision",
        json={
            "decision": "approve",
            "payout": 100.0,
            "calculation": "$100.00",
            "reason": "Covered.",
            "policy_section": "3. Trip Delay",
        },
    )
    assert start("CLM-1004").status_code == 409
    assert client.post("/api/claims/CLM-1004/run").status_code == 409


def test_startup_releases_claims_left_in_progress():
    start("CLM-1005")
    with TestClient(app):
        pass
    assert claim("CLM-1005")["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1005/steps").json()
    assert steps[-1]["content"] == (
        "The backend restarted while the agent was working on this claim."
    )
    assert backend.MAX_ATTEMPTS == 2


def test_reseed():
    start("CLM-1006")
    db.reseed()
    assert row("CLM-1006")["attempts"] == 0
    statuses = {c["status"] for c in client.get("/api/claims").json()}
    assert statuses == {"waiting"}
