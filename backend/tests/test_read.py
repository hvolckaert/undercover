from fastapi.testclient import TestClient

from backend import db
from backend.main import app

client = TestClient(app)


def test_seeds_the_queue():
    claims = client.get("/api/claims").json()
    assert len(claims) == 25
    assert {c["status"] for c in claims} == {"waiting"}
    first = claims[0]
    assert first["claim_id"] == "CLM-1001"
    assert first["customer_name"] == "Maya Patel"
    assert first["amount_claimed"] == 420.0
    assert first["decision"] is None


def test_seeds_once():
    db.connect().close()
    assert len(client.get("/api/claims").json()) == 25


def test_leaves_out_evals_and_security():
    conn = db.connect()
    ids = {row["claim_id"] for row in conn.execute("SELECT claim_id FROM claims")}
    for name in ["evals/held_out_claims.json", "security/claims.json"]:
        held_back = {c["claim_id"] for c in db.load(name)}
        assert ids.isdisjoint(held_back)
    assert "CLM-1901" not in "\n".join(conn.iterdump())
    assert client.get("/api/claims/CLM-1901").status_code == 404


def test_get_claim():
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "waiting"
    assert len(claim["items"]) == 3
    assert sum(item["amount"] for item in claim["items"]) == 420.0
    assert claim["documents"]
    assert claim["decision"] is None
    assert claim["payment"] is None


def test_missing_records():
    assert client.get("/api/claims/CLM-9999").status_code == 404
    assert client.get("/api/policies/POL-9999").status_code == 404
    assert client.get("/api/customers/CUS-9999").status_code == 404


def test_get_policy():
    policy = client.get("/api/policies/POL-2001").json()
    assert policy["plan_details"]["name"] == "UnderCover Premium"
    assert policy["plan_details"]["deductible"] == 50.0
    assert policy["plan_details"]["deductible_applies_to"] == [
        "baggage",
        "emergency_medical",
    ]
    assert policy["add_on_details"] == []


def test_get_policy_with_add_ons():
    policy_id = next(p["policy_id"] for p in db.load("policies.json") if p["add_ons"])
    policy = client.get(f"/api/policies/{policy_id}").json()
    assert [a["add_on"] for a in policy["add_on_details"]] == policy["add_ons"]


def test_get_customer():
    customer = client.get("/api/customers/CUS-3001").json()
    assert customer["name"] == "Maya Patel"
    assert customer["previous_claims"][0]["claim_id"] == "CLM-0412"


def test_policy_wording_and_instructions():
    wording = client.get("/api/policy-wording").json()["wording"]
    assert "## 10. How we work out your payment" in wording
    instructions = client.get("/api/instructions").json()["instructions"]
    assert "UnderCover Agent" in instructions


def test_list_handlers():
    handlers = client.get("/api/handlers").json()
    assert [h["handler_id"] for h in handlers] == ["HND-01", "HND-02", "HND-03"]


def test_every_operation_is_documented():
    for path in app.openapi()["paths"].values():
        for operation in path.values():
            assert operation["operationId"]
            assert operation["summary"] or operation["description"]
            for parameter in operation.get("parameters", []):
                assert parameter["required"]
