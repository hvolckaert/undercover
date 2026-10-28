from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


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
