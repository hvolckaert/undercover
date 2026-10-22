import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import main
from backend import main as backend
from backend.main import app

client = TestClient(app)


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


def tool_call(name, args, id_):
    return {"name": name, "args": args, "id": id_}


def script(claim_id, payout, final):
    reads = [
        tool_call("get_claim", {"claim_id": claim_id}, "1"),
        tool_call("get_policy", {"policy_id": "POL-2001"}, "2"),
        tool_call("get_customer", {"customer_id": "CUS-3001"}, "3"),
        tool_call("get_policy_wording", {}, "4"),
    ]
    decision = {
        "decision": "approve",
        "payout": payout,
        "calculation": f"${payout:.2f} within the maximum",
        "reason": "The flight was canceled for a crew problem.",
        "policy_section": "3. Trip Delay",
    }
    replies = [
        AIMessage(content="", tool_calls=reads),
        AIMessage(
            content="",
            tool_calls=[
                tool_call(
                    "record_decision",
                    {"claim_id": claim_id, "decision": decision},
                    "5",
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                tool_call("pay_claim", {"claim_id": claim_id, "amount": payout}, "6")
            ],
        ),
        AIMessage(content=final),
    ]
    return StubModel(messages=iter(replies))


@pytest.fixture(autouse=True)
def backend_client(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: TestClient(app))


def test_run_decides_and_pays():
    reply = main.run("CLM-1001", "thread-1", script("CLM-1001", 420.0, "Approved."))
    assert reply == "Approved."
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["decision"]["payout"] == 420.0
    assert claim["payment"]["amount"] == 420.0
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["kind"] for s in steps] == [
        *["tool_call"] * 4,
        *["tool_result"] * 4,
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "reply",
    ]
    assert steps[0]["content"] == 'get_claim {"claim_id": "CLM-1001"}'
    assert {s["content"].split(":")[0] for s in steps[4:8]} == {
        "get_claim",
        "get_policy",
        "get_customer",
        "get_policy_wording",
    }
    assert {s["thread_id"] for s in steps} == {"thread-1"}


def test_payment_over_the_limit_is_blocked():
    main.run("CLM-1001", "thread-2", script("CLM-1001", 1250.0, "Awaiting sign-off."))
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "waiting_for_signoff"
    assert claim["payment"] is None
    results = [
        s["content"]
        for s in client.get("/api/claims/CLM-1001/steps").json()
        if s["kind"] == "tool_result"
    ]
    assert results[-1] == (
        "pay_claim: Refused (409): This payout needs a handler's sign-off"
    )


def test_run_agent_starts_the_agent(monkeypatch):
    runs = []
    monkeypatch.setattr(
        main,
        "run",
        lambda claim_id, thread_id: (
            runs.append(claim_id)
            or client.post(
                f"/api/claims/{claim_id}/decision",
                json={
                    "decision": "refer",
                    "payout": 0,
                    "calculation": "No payout on a referral.",
                    "reason": "A document is missing.",
                    "policy_section": "11. How to claim",
                },
            )
        ),
    )
    started = client.post("/api/claims/CLM-1002/run").json()
    assert started["status"] == "in_progress"
    assert runs == ["CLM-1002"]
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "decided"
    assert client.post("/api/claims/CLM-1002/run").status_code == 409


def test_a_failed_run_goes_back_to_the_queue(monkeypatch):
    def fail(claim_id, thread_id):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(main, "run", fail)
    client.post("/api/claims/CLM-1003/run")
    assert client.get("/api/claims/CLM-1003").json()["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1003/steps").json()
    assert steps[-1]["kind"] == "error"
    assert "model unavailable" in steps[-1]["content"]


def test_a_run_without_a_decision_goes_back_to_the_queue(monkeypatch):
    monkeypatch.setattr(main, "run", lambda claim_id, thread_id: "")
    client.post("/api/claims/CLM-1004/run")
    assert client.get("/api/claims/CLM-1004").json()["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1004/steps").json()
    assert steps[-1]["content"] == "The agent finished without recording a decision."


def test_the_agent_never_sees_the_evals():
    instructions = client.get("/api/instructions").json()["instructions"]
    assert "evals" not in instructions
    for agent_tool in main.TOOLS:
        assert "evals" not in str(agent_tool.args)
        assert "evals" not in agent_tool.description
    assert backend.claim_agent is main


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert main.model().model_name == "openai/gpt-6-luna"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"
