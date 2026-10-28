import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import main
from backend import main as backend
from backend.main import app

client = TestClient(app)


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies, after timing out `failures` times."""

    failures: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.failures:
            self.failures -= 1
            raise TimeoutError("The model timed out.")
        return super()._generate(messages, stop, run_manager, **kwargs)


def tool_call(name, args, id_):
    return {"name": name, "args": args, "id": id_}


def decision(payout):
    return {
        "decision": "approve",
        "payout": payout,
        "calculation": f"${payout:.2f} within the maximum",
        "reason": "The flight was canceled for a crew problem.",
        "policy_section": "3. Trip Delay",
    }


def claim_script(claim_id, payout=420.0, final="Approved."):
    reads = [
        tool_call("get_claim", {"claim_id": claim_id}, "1"),
        tool_call("get_policy", {"policy_id": "POL-2001"}, "2"),
        tool_call("get_customer", {"customer_id": "CUS-3001"}, "3"),
        tool_call("list_sections", {}, "4"),
    ]
    lookups = [
        tool_call("read_section", {"document": "policy_wording", "section": "3"}, "5"),
        tool_call("read_section", {"document": "claims_manual", "section": "10"}, "6"),
        tool_call("search_documents", {"words": "meals receipts"}, "7"),
    ]
    return [
        AIMessage(content="", tool_calls=reads),
        AIMessage(content="", tool_calls=lookups),
        AIMessage(
            content="",
            tool_calls=[
                tool_call(
                    "record_decision",
                    {"claim_id": claim_id, "decision": decision(payout)},
                    "8",
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                tool_call("pay_claim", {"claim_id": claim_id, "amount": payout}, "9")
            ],
        ),
        AIMessage(content=final),
    ]


def use_claim_model(monkeypatch, *replies, failures=0):
    model = StubModel(messages=iter(replies), failures=failures)
    monkeypatch.setattr(main, "claim_model", lambda: model)


@pytest.fixture(autouse=True)
def backend_client(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: TestClient(app))


def steps(claim_id):
    return client.get(f"/api/claims/{claim_id}/steps").json()


def test_run_claim_looks_up_decides_and_pays(monkeypatch):
    use_claim_model(monkeypatch, *claim_script("CLM-1001"))
    assert main.run_claim("CLM-1001", "thread-1") == "Approved."
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["decision"]["payout"] == 420.0
    assert claim["payment"]["amount"] == 420.0
    recorded = steps("CLM-1001")
    assert [s["kind"] for s in recorded] == [
        *["tool_call"] * 4,
        *["tool_result"] * 4,
        *["tool_call"] * 3,
        *["tool_result"] * 3,
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "reply",
    ]
    assert recorded[0]["content"] == 'get_claim {"claim_id": "CLM-1001"}'
    calls = [s["content"] for s in recorded if s["kind"] == "tool_call"]
    assert 'read_section {"document": "claims_manual", "section": "10"}' in calls
    results = [s["content"] for s in recorded if s["kind"] == "tool_result"]
    assert any(r.startswith("read_section:") and "Meals without" in r for r in results)
    assert any(r.startswith("search_documents:") and "$35" in r for r in results)
    assert {s["thread_id"] for s in recorded} == {"thread-1"}


def test_payment_over_the_limit_is_blocked(monkeypatch):
    use_claim_model(monkeypatch, *claim_script("CLM-1001", 1250.0, "Held."))
    main.run_claim("CLM-1001", "thread-2")
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "waiting_for_signoff"
    assert claim["payment"] is None
    results = [s["content"] for s in steps("CLM-1001") if s["kind"] == "tool_result"]
    assert results[-1] == (
        "pay_claim: Refused (409): This payout needs a handler's sign-off"
    )


def test_a_provider_error_is_retried(monkeypatch):
    use_claim_model(monkeypatch, *claim_script("CLM-1002"), failures=1)
    assert main.run_claim("CLM-1002", "thread-3") == "Approved."
    assert client.get("/api/claims/CLM-1002").json()["status"] == "decided"
    assert "error" not in {s["kind"] for s in steps("CLM-1002")}


def test_run_agent_starts_the_agent(monkeypatch):
    use_claim_model(monkeypatch, *claim_script("CLM-1002"))
    started = client.post("/api/claims/CLM-1002/run").json()
    assert started["status"] == "in_progress"
    assert client.get("/api/claims/CLM-1002").json()["status"] == "decided"
    assert client.post("/api/claims/CLM-1002/run").status_code == 409


def test_a_failed_run_goes_back_to_the_queue(monkeypatch):
    def fail(claim_id, thread_id):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(main, "run_claim", fail)
    client.post("/api/claims/CLM-1003/run")
    assert client.get("/api/claims/CLM-1003").json()["status"] == "waiting"
    assert steps("CLM-1003")[-1]["kind"] == "error"
    assert "model unavailable" in steps("CLM-1003")[-1]["content"]


def test_a_run_without_a_decision_goes_back_to_the_queue(monkeypatch):
    monkeypatch.setattr(main, "run_claim", lambda claim_id, thread_id: "")
    client.post("/api/claims/CLM-1004/run")
    assert client.get("/api/claims/CLM-1004").json()["status"] == "waiting"
    assert steps("CLM-1004")[-1]["content"] == (
        "The agent finished without recording a decision."
    )


def test_the_agent_never_sees_the_evals():
    instructions = client.get("/api/instructions").json()["instructions"]
    assert "evals" not in instructions
    for agent_tool in main.CLAIM_TOOLS:
        assert "evals" not in str(agent_tool.args)
        assert "evals" not in agent_tool.description
    assert backend.claim_agent is main


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    default = main.model()
    assert default.model_name == "deepseek/deepseek-v4.1-flash"
    assert default.reasoning_effort == "low"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"
