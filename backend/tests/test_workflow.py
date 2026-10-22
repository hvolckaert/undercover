import json

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.main import app

client = TestClient(app)


def decide(claim_id, decision="approve", payout=420.0):
    return client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "calculation": "Hotel $245.00 + meals $95.00 + taxis $80.00 = $420.00",
            "reason": "The flight was canceled for a crew problem.",
            "policy_section": "3. Trip Delay",
        },
    )


def pay(claim_id, amount):
    return client.post(f"/api/claims/{claim_id}/payment", json={"amount": amount})


def sign_off(claim_id, handler_id="HND-01"):
    return client.post(
        f"/api/claims/{claim_id}/sign-off", json={"handler_id": handler_id}
    )


def test_steps():
    for kind, content in [("tool_call", "get_claim"), ("reply", "Approved")]:
        response = client.post(
            "/api/claims/CLM-1001/steps",
            json={"thread_id": "t1", "kind": kind, "content": content},
        )
        assert response.status_code == 200
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [(s["kind"], s["content"]) for s in steps] == [
        ("tool_call", "get_claim"),
        ("reply", "Approved"),
    ]
    assert steps[0]["thread_id"] == "t1"
    assert client.get("/api/claims/CLM-1002/steps").json() == []
    assert client.get("/api/claims/CLM-9999/steps").status_code == 404


def test_approve_within_limit():
    assert decide("CLM-1001").json() == {"status": "decided"}
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["decision"]["policy_section"] == "3. Trip Delay"
    assert pay("CLM-1001", 420.0).json() == {"status": "paid"}
    assert client.get("/api/claims/CLM-1001").json()["payment"]["amount"] == 420.0
    assert pay("CLM-1001", 420.0).status_code == 409


def test_approve_over_limit_waits_for_sign_off():
    assert decide("CLM-1002", payout=1250.0).json() == {"status": "waiting_for_signoff"}
    refused = pay("CLM-1002", 1250.0)
    assert refused.status_code == 409
    assert "sign-off" in refused.json()["detail"]
    assert client.get("/api/claims/CLM-1002").json()["payment"] is None

    assert sign_off("CLM-1002").json() == {"status": "decided"}
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "decided"
    assert claim["sign_off"]["name"] == "Dana Whitfield"
    assert claim["payment"]["amount"] == 1250.0
    assert pay("CLM-1002", 1250.0).status_code == 409
    assert sign_off("CLM-1002").status_code == 409


def test_exactly_the_limit_needs_no_sign_off():
    assert decide("CLM-1003", payout=1000.0).json() == {"status": "decided"}
    assert pay("CLM-1003", 1000.0).json() == {"status": "paid"}


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_decline_and_refer(decision):
    assert decide("CLM-1004", decision, 0).json() == {"status": "decided"}
    assert pay("CLM-1004", 100.0).status_code == 409
    assert sign_off("CLM-1004").status_code == 409


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_no_payout_unless_approved(decision):
    assert decide("CLM-1004", decision, 50.0).status_code == 422


def test_pay_refusals():
    assert pay("CLM-1005", 420.0).status_code == 409
    decide("CLM-1005")
    assert pay("CLM-1005", 999.0).status_code == 409
    assert pay("CLM-1005", -5).status_code == 422
    assert pay("CLM-9999", 420.0).status_code == 404


def test_one_decision_per_claim():
    decide("CLM-1006")
    assert decide("CLM-1006", "decline", 0).status_code == 409


def test_sign_off_refusals():
    decide("CLM-1007", payout=1500.0)
    assert sign_off("CLM-1007", "HND-99").status_code == 404
    conn = db.connect()
    handler = db.record(conn, "handler", "HND-03")
    handler["can_approve_over_limit"] = False
    conn.execute(
        "UPDATE records SET body = ? WHERE kind = 'handler' AND id = 'HND-03'",
        (json.dumps(handler),),
    )
    conn.commit()
    conn.close()
    assert sign_off("CLM-1007", "HND-03").status_code == 403
    assert client.get("/api/claims/CLM-1007").json()["payment"] is None


def test_queue_shows_decisions():
    decide("CLM-1001")
    first = client.get("/api/claims").json()[0]
    assert first["status"] == "decided"
    assert first["decision"] == "approve"
    assert first["payout"] == 420.0
