import pytest
from fastapi.testclient import TestClient
from langchain.agents.middleware import ModelRetryMiddleware

from agent import main
from backend.main import app


class Backend(TestClient):
    """A test client that leaves out the backend's startup, which a `with` runs."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture(autouse=True)
def backend_client(monkeypatch):
    """Send the agent's API calls to the backend in this process."""
    monkeypatch.setattr(main, "backend", lambda: Backend(app))


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """Retry a failing stub model without waiting between tries."""
    monkeypatch.setattr(
        main,
        "retry",
        lambda: ModelRetryMiddleware(
            max_retries=3, on_failure="error", initial_delay=0, jitter=False
        ),
    )
