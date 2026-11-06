"""Token-based estimates, following the course CostAccumulator pattern."""
from dataclasses import dataclass

# USD / million tokens; standard input price, without cache or batch discounts.
# https://developers.openai.com/api/docs/models/gpt-4o-mini (checked 2026-11-04)
MODEL_PRICES = {"gpt-4o-mini": {"input": 0.15, "output": 0.60}}


def cost_usd(model, input_tokens, output_tokens):
    prices = MODEL_PRICES.get(model.removeprefix("openai:").lower())
    if prices is None:
        return None  # An unpriced model must not look free.
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


@dataclass
class CostAccumulator:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    missing_usage: int = 0

    def add(self, usage):
        self.requests += 1
        if usage is None:
            self.missing_usage += 1
            return
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0

    @property
    def total_cost(self):
        if self.missing_usage:
            return None
        return cost_usd(self.model, self.input_tokens, self.output_tokens)

    def as_dict(self):
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "requests": self.requests, "missing_usage": self.missing_usage,
                "estimated_cost_usd": self.total_cost}
