"""Model clients. AnthropicLLM talks to the Messages API with plain httpx;
ScriptedLLM replays fixed tool calls (used by unit tests and the harness self-check)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict]          # [{"id", "name", "input"}]
    content: list[dict]             # raw assistant content blocks (Anthropic format)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""


class LLMError(RuntimeError):
    pass


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.anthropic.com",
                 max_tokens: int = 4096, timeout: float = 120):
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set. Put it in .env (see .env.example).")
        self.model = model
        self.max_tokens = max_tokens
        self.client = httpx.Client(base_url=base_url, timeout=timeout, headers={
            "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                 max_tokens: int | None = None) -> LLMResponse:
        body = {"model": self.model, "max_tokens": max_tokens or self.max_tokens, "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
        last = None
        for attempt in range(4):  # retry rate limits / overload with backoff
            r = self.client.post("/v1/messages", json=body)
            if r.status_code in (429, 500, 502, 503, 529):
                last = r.text
                time.sleep(2 ** attempt)
                continue
            if r.status_code != 200:
                raise LLMError(f"API error {r.status_code}: {r.text[:500]}")
            data = r.json()
            content = data.get("content", [])
            return LLMResponse(
                text="".join(b.get("text", "") for b in content if b.get("type") == "text"),
                tool_calls=[{"id": b["id"], "name": b["name"], "input": b.get("input", {})}
                            for b in content if b.get("type") == "tool_use"],
                content=content,
                input_tokens=data.get("usage", {}).get("input_tokens", 0),
                output_tokens=data.get("usage", {}).get("output_tokens", 0),
                stop_reason=data.get("stop_reason", ""))
        raise LLMError(f"API kept failing: {last[:300] if last else ''}")


@dataclass
class ScriptedLLM:
    """Deterministic fake model. `script` is a list of steps; each step is a list of
    (tool_name, input) tuples or a final text string. A callable can also decide."""
    script: list | Callable = field(default_factory=list)
    i: int = 0
    tokens_per_call: tuple[int, int] = (1000, 200)

    def complete(self, system, messages, tools=None, max_tokens=None) -> LLMResponse:
        if callable(self.script):
            step = self.script(messages, self.i)
        else:
            step = self.script[self.i] if self.i < len(self.script) else "done"
        self.i += 1
        if isinstance(step, str):
            content = [{"type": "text", "text": step}]
            calls = []
        else:
            calls, content = [], []
            for n, (name, inp) in enumerate(step):
                cid = f"toolu_{self.i}_{n}"
                calls.append({"id": cid, "name": name, "input": inp})
                content.append({"type": "tool_use", "id": cid, "name": name, "input": inp})
        return LLMResponse(text=step if isinstance(step, str) else "", tool_calls=calls, content=content,
                           input_tokens=self.tokens_per_call[0], output_tokens=self.tokens_per_call[1],
                           stop_reason="tool_use" if calls else "end_turn")


def parse_json_block(text: str) -> dict:
    """Pull the first JSON object out of a model answer."""
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("no JSON object in model output")
    return json.loads(text[s:e + 1])
