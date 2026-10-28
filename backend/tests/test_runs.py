import pytest
from fastapi.testclient import TestClient

from backend import main as backend
from backend.main import app

client = TestClient(app)

TODOS = [
    {"task": "Work CLM-1001", "status": "done"},
    {"task": "Work CLM-1002", "status": "in_progress"},
    {"task": "Work CLM-1003", "status": "to_do"},
    {"task": "Work CLM-1004", "status": "for_handler"},
]


def start(claim_id, run_id):
    return client.post(f"/api/claims/{claim_id}/start", json={"run_id": run_id})


def release(claim_id, thread_id):
    return client.post(
        f"/api/claims/{claim_id}/release",
        json={"thread_id": thread_id, "problem": "The model timed out."},
    )


def decide(claim_id):
    client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": "decline",
            "payout": 0,
            "calculation": "No payout on a decline.",
            "reason": "The loss is excluded.",
            "policy_section": "9. General exclusions",
        },
    )


def finish(run_id, summary="Two claims decided."):
    return client.post(f"/api/runs/{run_id}/finish", json={"summary": summary})


def latest():
    return client.get("/api/runs/latest").json()


def test_no_run_yet():
    assert client.get("/api/runs/latest").json() is None


def test_one_run_at_a_time(new_run):
    run = new_run(2).json()
    assert run["status"] == "running"
    assert run["max_claims"] == 2
    assert run["todos"] == []
    assert new_run(5).status_code == 409
    assert latest()["run_id"] == run["run_id"]
    for claim_id in ["CLM-1001", "CLM-1002"]:
        start(claim_id, run["run_id"])
        decide(claim_id)
    assert finish(run["run_id"]).json() == {"status": "finished"}
    assert new_run(5).status_code == 200


def test_max_claims_must_be_positive(new_run):
    assert new_run(0).status_code == 422


def test_the_cap(new_run):
    run_id = new_run(2).json()["run_id"]
    first = start("CLM-1001", run_id).json()["thread_id"]
    start("CLM-1002", run_id)
    refused = start("CLM-1003", run_id)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "The run has already started its 2 claims"
    assert client.get("/api/claims/CLM-1003").json()["status"] == "waiting"
    release("CLM-1001", first)
    assert start("CLM-1001", run_id).status_code == 200


def test_missed_claims(new_run):
    run_id = new_run(2).json()["run_id"]
    assert finish(run_id).json()["detail"] == (
        "Claims still to work within the cap: CLM-1001, CLM-1002"
    )
    thread_id = start("CLM-1001", run_id).json()["thread_id"]
    release("CLM-1001", thread_id)
    start("CLM-1002", run_id)
    decide("CLM-1002")
    assert finish(run_id).json()["detail"] == (
        "Claims still to work within the cap: CLM-1001"
    )
    start("CLM-1001", run_id)
    decide("CLM-1001")
    assert finish(run_id, "CLM-1001 and CLM-1002 declined.").status_code == 200
    run = latest()
    assert run["status"] == "finished"
    assert run["summary"] == "CLM-1001 and CLM-1002 declined."
    assert run["finished_at"]
    assert finish(run_id).status_code == 409


def test_a_claim_left_for_a_handler_is_not_missed(new_run):
    run_id = new_run(1).json()["run_id"]
    for _ in range(2):
        thread_id = start("CLM-1001", run_id).json()["thread_id"]
        release("CLM-1001", thread_id)
    assert finish(run_id).status_code == 200


def test_a_cap_above_the_queue(new_run):
    run_id = new_run(30).json()["run_id"]
    claims = [c["claim_id"] for c in client.get("/api/claims").json()]
    for claim_id in claims:
        start(claim_id, run_id)
        decide(claim_id)
    assert finish(run_id).status_code == 200


def test_write_todos(new_run):
    run_id = new_run().json()["run_id"]
    response = client.put(f"/api/runs/{run_id}/todos", json={"todos": TODOS})
    assert response.json() == {"status": "saved"}
    assert latest()["todos"] == TODOS
    bad = [{"task": "Work CLM-1001", "status": "maybe"}]
    assert (
        client.put(f"/api/runs/{run_id}/todos", json={"todos": bad}).status_code == 422
    )
    assert client.put("/api/runs/nope/todos", json={"todos": TODOS}).status_code == 404


def test_todos_refused_on_a_finished_run(new_run):
    run_id = new_run(25).json()["run_id"]
    for claim in client.get("/api/claims").json():
        start(claim["claim_id"], run_id)
        decide(claim["claim_id"])
    finish(run_id)
    assert client.put(f"/api/runs/{run_id}/todos", json={"todos": TODOS}).json() == {
        "detail": f"Run {run_id} is finished"
    }


def test_claims_refused_on_a_stopped_run(new_run):
    run_id = new_run().json()["run_id"]
    with TestClient(app):
        pass
    assert latest()["status"] == "stopped"
    assert latest()["problem"] == "The backend restarted during the run."
    assert start("CLM-1001", run_id).status_code == 409


@pytest.mark.parametrize(
    ("queue", "problem"),
    [
        (lambda run_id: "", "The agent ended the run without finishing it."),
        (
            lambda run_id: 1 / 0,
            "The run stopped with an error: division by zero",
        ),
    ],
)
def test_a_run_that_ends_badly_is_stopped(monkeypatch, queue, problem):
    monkeypatch.setattr(backend.claim_agent, "run_queue", queue)
    client.post("/api/runs", json={"max_claims": 5})
    run = latest()
    assert run["status"] == "stopped"
    assert run["problem"] == problem
    assert run["finished_at"]
