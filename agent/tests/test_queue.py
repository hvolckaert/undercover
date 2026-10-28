from itertools import count

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent import main
from agent.tests.stubs import StubModel, claim_script, tool_call
from backend import main as backend
from backend.main import app

client = TestClient(app)
ids = count()
LIST = ("list_waiting_claims", {})


def turn(*calls):
    """One reply from the queue agent, calling some tools."""
    return AIMessage(
        content="",
        tool_calls=[tool_call(name, args, f"q{next(ids)}") for name, args in calls],
    )


def todos(states, check="to_do"):
    items = [{"task": f"Work {c}", "status": s} for c, s in states.items()]
    items.append({"task": "Check for missed claims", "status": check})
    return ("write_todos", {"todos": items})


def work(claim_id):
    return ("work_claim", {"claim_id": claim_id})


def finish(summary="All done."):
    return ("finish_run", {"summary": summary})


def deciding(claim_id, payout=420.0):
    return StubModel(messages=iter(claim_script(claim_id, payout)))


def failing():
    return StubModel(messages=iter([]), failures=99)


def use_models(monkeypatch, queue_replies, claim_models):
    queue = StubModel(messages=iter([*queue_replies, AIMessage(content="Done.")]))
    monkeypatch.setattr(main, "queue_model", lambda: queue)
    claims = iter(claim_models)
    monkeypatch.setattr(main, "claim_model", lambda: next(claims))


@pytest.fixture
def calls(monkeypatch):
    """Record every call the agent makes to the backend, with the reply."""
    made = []
    real = main.call

    def spy(method, path, body=None):
        reply = real(method, path, body)
        made.append((method, path, body, reply))
        return reply

    monkeypatch.setattr(main, "call", spy)
    return made


def start_run(max_claims):
    return client.post("/api/runs", json={"max_claims": max_claims}).json()


def claim(claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def steps(claim_id):
    return client.get(f"/api/claims/{claim_id}/steps").json()


def latest():
    return client.get("/api/runs/latest").json()


def test_a_capped_run_works_its_claims_and_keeps_its_todos(monkeypatch, calls):
    chosen = ["CLM-1001", "CLM-1002", "CLM-1003"]
    states = dict.fromkeys(chosen, "to_do")
    replies = [turn(LIST), turn(todos(states))]
    for claim_id in chosen:
        states[claim_id] = "in_progress"
        replies.append(turn(todos(states)))
        replies.append(turn(work(claim_id)))
        states[claim_id] = "done"
        replies.append(turn(todos(states)))
    replies += [turn(LIST), turn(todos(states, "done")), turn(finish("3 approved."))]
    use_models(monkeypatch, replies, [deciding(c) for c in chosen])

    start_run(3)

    run = latest()
    assert run["status"] == "finished"
    assert run["summary"] == "3 approved."
    assert {t["status"] for t in run["todos"]} == {"done"}
    for claim_id in chosen:
        assert claim(claim_id)["status"] == "decided"
    waiting = [c for c in client.get("/api/claims").json() if c["status"] == "waiting"]
    assert len(waiting) == 22
    threads = [{s["thread_id"] for s in steps(c)} for c in chosen]
    assert all(len(t) == 1 for t in threads)
    assert len(set.union(*threads)) == 3
    lists = [
        [t["status"] for t in body["todos"][:3]]
        for method, _, body, _ in calls
        if method == "PUT"
    ]
    assert lists[0] == ["to_do", "to_do", "to_do"]
    assert ["in_progress", "to_do", "to_do"] in lists
    assert ["done", "in_progress", "to_do"] in lists
    assert lists[-1] == ["done", "done", "done"]
    results = [reply for _, path, _, reply in calls if path.endswith("/finish")]
    assert results == ['{"status":"finished"}']


def test_a_failed_claim_does_not_stop_the_run_and_is_tried_again(monkeypatch):
    replies = [
        turn(LIST),
        turn(work("CLM-1001")),
        turn(work("CLM-1002")),
        turn(work("CLM-1001")),
        turn(finish()),
    ]
    use_models(
        monkeypatch,
        replies,
        [failing(), deciding("CLM-1002"), deciding("CLM-1001")],
    )

    start_run(2)

    assert latest()["status"] == "finished"
    assert claim("CLM-1002")["status"] == "decided"
    assert claim("CLM-1001")["status"] == "decided"
    errors = [s for s in steps("CLM-1001") if s["kind"] == "error"]
    assert [e["content"] for e in errors] == [
        "The agent stopped with an error: The model timed out."
    ]
    attempts = {c["claim_id"]: c["attempts"] for c in client.get("/api/claims").json()}
    assert attempts["CLM-1001"] == 2
    assert len({s["thread_id"] for s in steps("CLM-1001")}) == 2


def test_a_claim_that_fails_twice_is_left_for_a_handler(monkeypatch):
    replies = [
        turn(LIST),
        turn(todos({"CLM-1001": "in_progress"})),
        turn(work("CLM-1001")),
        turn(work("CLM-1001")),
        turn(todos({"CLM-1001": "for_handler"}, "done")),
        turn(finish("CLM-1001 is left for a handler.")),
    ]
    use_models(monkeypatch, replies, [failing(), failing()])

    start_run(1)

    assert claim("CLM-1001")["status"] == "needs_handler"
    run = latest()
    assert run["status"] == "finished"
    assert run["todos"][0] == {"task": "Work CLM-1001", "status": "for_handler"}


def test_the_check_for_missed_claims(monkeypatch, calls):
    replies = [
        turn(LIST),
        turn(work("CLM-1001")),
        turn(finish("Too early.")),
        turn(work("CLM-1002")),
        turn(finish("Two claims approved.")),
    ]
    use_models(monkeypatch, replies, [deciding("CLM-1001"), deciding("CLM-1002")])

    start_run(2)

    finishes = [reply for _, path, _, reply in calls if path.endswith("/finish")]
    assert finishes == [
        "Refused (409): Claims still to work within the cap: CLM-1002",
        '{"status":"finished"}',
    ]
    assert latest()["summary"] == "Two claims approved."
    assert claim("CLM-1002")["status"] == "decided"


def test_work_claim_reports_in_one_line(monkeypatch):
    monkeypatch.setattr(backend, "work_queue", lambda run_id, max_claims: None)
    run_id = start_run(3)["run_id"]
    tools = {t.name: t for t in main.queue_tools(run_id)}
    models = iter([deciding("CLM-1001"), deciding("CLM-1002", 1250.0), failing()])
    monkeypatch.setattr(main, "claim_model", lambda: next(models))

    def work_on(claim_id):
        return tools["work_claim"].invoke({"claim_id": claim_id})

    assert work_on("CLM-1001") == "CLM-1001: approve, $420.00 paid."
    assert work_on("CLM-1002") == ("CLM-1002: approve, $1,250.00 waiting for signoff.")
    assert work_on("CLM-1003") == (
        "CLM-1003: failed, back in the queue for one more try."
        " The agent stopped with an error: The model timed out."
    )
    assert work_on("CLM-1004") == (
        "CLM-1004: Refused (409): The run has already started its 3 claims"
    )
    assert (
        work_on("CLM-1001") == "CLM-1001: Refused (409): Claim CLM-1001 is not waiting"
    )
    waiting = tools["list_waiting_claims"].invoke({})
    assert "CLM-1001" not in waiting
    assert "CLM-1003:" in waiting
    assert "1 earlier attempts" in waiting


def test_report():
    claim_record = {
        "claim_id": "CLM-1005",
        "status": "decided",
        "decision": {"decision": "decline", "payout": 0},
        "payment": None,
    }
    assert main.report(claim_record) == "CLM-1005: decline."
    claim_record.update(decision=None, status="needs_handler")
    assert main.report(claim_record) == "CLM-1005: needs handler."


def test_a_claim_agent_that_loops_is_stopped_and_released(monkeypatch):
    loop = [
        AIMessage(
            content="",
            tool_calls=[tool_call("get_claim", {"claim_id": "CLM-1006"}, f"l{n}")],
        )
        for n in range(main.MODEL_CALLS_PER_CLAIM + 5)
    ]
    monkeypatch.setattr(main, "claim_model", lambda: StubModel(messages=iter(loop)))

    client.post("/api/claims/CLM-1006/run")

    assert claim("CLM-1006")["status"] == "waiting"
    recorded = steps("CLM-1006")
    calls_made = [s for s in recorded if s["kind"] == "tool_call"]
    assert len(calls_made) == main.MODEL_CALLS_PER_CLAIM
    assert recorded[-1]["content"] == (
        "The agent finished without recording a decision."
    )


def test_the_queue_agent_never_sees_the_evals():
    assert "evals" not in client.get("/api/instructions").json()["queue"]
    for agent_tool in main.queue_tools("run"):
        assert "evals" not in str(agent_tool.args)
        assert "evals" not in agent_tool.description
