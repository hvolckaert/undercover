"""The UnderCover Agent."""

import json
import os
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr

load_dotenv(override=True)

BACKEND_URL = "http://localhost:8000"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-luna"


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


def call(method: str, path: str, body: dict[str, Any] | None = None) -> str:
    """Call the backend and return its reply, or why it refused."""
    with backend() as client:
        response = client.request(method, path, json=body)
    if response.is_error:
        return f"Refused ({response.status_code}): {response.json()['detail']}"
    return response.text


@tool
def get_claim(claim_id: str) -> str:
    """Get a claim: the story, the items claimed and the documents."""
    return call("GET", f"/api/claims/{claim_id}")


@tool
def get_policy(policy_id: str) -> str:
    """Get a policy with its plan's limits, its add-ons and the covered trip."""
    return call("GET", f"/api/policies/{policy_id}")


@tool
def get_customer(customer_id: str) -> str:
    """Get a customer with their earlier claims."""
    return call("GET", f"/api/customers/{customer_id}")


@tool
def get_policy_wording() -> str:
    """Get the policy wording, the contract the decision must follow."""
    return call("GET", "/api/policy-wording")


class Decision(BaseModel):
    """A decision on a claim."""

    decision: Literal["approve", "decline", "refer"]
    payout: float = Field(description="US dollars; 0 unless approved")
    calculation: str = Field(description="How the payout was worked out")
    reason: str = Field(description="Two or three plain sentences")
    policy_section: str = Field(description="Such as '3. Trip Delay'")


@tool
def record_decision(claim_id: str, decision: Decision) -> str:
    """Record the decision on a claim."""
    return call("POST", f"/api/claims/{claim_id}/decision", decision.model_dump())


@tool
def pay_claim(claim_id: str, amount: float) -> str:
    """Pay the approved payout on a claim."""
    return call("POST", f"/api/claims/{claim_id}/payment", {"amount": amount})


TOOLS = [
    get_claim,
    get_policy,
    get_customer,
    get_policy_wording,
    record_decision,
    pay_claim,
]


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or GPT-6 Luna by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
    )


def steps(message: BaseMessage) -> list[tuple[str, str]]:
    """Turn one message from the agent into the steps the dashboard shows."""
    if isinstance(message, ToolMessage):
        return [("tool_result", f"{message.name}: {message.text}")]
    if isinstance(message, AIMessage) and message.tool_calls:
        return [
            ("tool_call", f"{call['name']} {json.dumps(call['args'])}")
            for call in message.tool_calls
        ]
    return [("reply", message.text)] if message.text else []


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the agent on one claim, record each step and return its final reply."""
    instructions = json.loads(call("GET", "/api/instructions"))["instructions"]
    agent = create_agent(llm or model(), tools=TOOLS, system_prompt=instructions)
    reply = ""
    for update in agent.stream(
        {"messages": [{"role": "user", "content": f"Decide claim {claim_id}."}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    ):
        for state in update.values():
            for message in (state or {}).get("messages", []):
                for kind, content in steps(message):
                    call(
                        "POST",
                        f"/api/claims/{claim_id}/steps",
                        {"thread_id": thread_id, "kind": kind, "content": content},
                    )
                    reply = content if kind == "reply" else reply
    return reply
