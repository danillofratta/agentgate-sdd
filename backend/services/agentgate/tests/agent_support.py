"""Deterministic provider shared by offline and opt-in local integration verification."""

import json


def tool_call(name, arguments):
    return {
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def proposal(amount=100):
    return {
        "tool_name": "simulate_transfer",
        "arguments": {
            "source_account_id": "acct-alice",
            "destination_account_id": "acct-bob",
            "amount_cents": amount,
            "currency": "USD",
        },
    }


class ScriptedLlm:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []
        self.verified = 0

    async def verify_tools(self):
        self.verified += 1

    async def complete(self, messages, tools, required=None):
        self.seen.append((list(messages), tools, required))
        response = (
            self.responses.pop(0)
            if self.responses
            else {"content": "Inspect the authoritative card.", "tool_calls": []}
        )
        if isinstance(response, Exception):
            raise response
        return response(messages) if callable(response) else response
