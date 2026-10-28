import pytest
from fastapi.testclient import TestClient

from backend import main as backend
from backend.main import app


@pytest.fixture
def new_run(monkeypatch):
    """Start runs whose queue agent does nothing, so tests drive them by hand."""
    monkeypatch.setattr(backend, "work_queue", lambda run_id: None)

    def start(max_claims=25):
        return TestClient(app).post("/api/runs", json={"max_claims": max_claims})

    return start
