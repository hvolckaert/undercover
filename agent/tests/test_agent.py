from fastapi.testclient import TestClient

from agent import main
from agent.tests.stubs import StubModel, claim_script
from backend import main as backend
from backend.main import app

client = TestClient(app)


def use_claim_model(monkeypatch, *replies, failures=0):
    model = StubModel(messages=iter(replies), failures=failures)
    monkeypatch.setattr(main, "claim_model", lambda: model)


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
    instructions = client.get("/api/instructions").json()["claim"]
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
