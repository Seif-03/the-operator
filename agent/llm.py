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
    input_tokens: int = 0           # uncached input (full price)
    output_tokens: int = 0
    stop_reason: str = ""
    cache_write_tokens: int = 0     # input written to the prompt cache (~1.25x price)
    cache_read_tokens: int = 0      # input read from the prompt cache (~0.1x price)


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
        # Prompt caching: each loop step re-sends tools + system + the whole history. The automatic breakpoint
        # caches everything up to the last message, so the next step reads that prefix at ~10% of the price.
        body = {"model": self.model, "max_tokens": max_tokens or self.max_tokens, "system": system, "messages": messages,
                "cache_control": {"type": "ephemeral"}}
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
            usage = data.get("usage") or {}
            return LLMResponse(
                text="".join(b.get("text", "") for b in content if b.get("type") == "text"),
                tool_calls=[{"id": b["id"], "name": b["name"], "input": b.get("input", {})}
                            for b in content if b.get("type") == "tool_use"],
                content=content,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                stop_reason=data.get("stop_reason", ""),
                cache_write_tokens=usage.get("cache_creation_input_tokens") or 0,
                cache_read_tokens=usage.get("cache_read_input_tokens") or 0)
        raise LLMError(f"API kept failing: {last[:300] if last else ''}")


class OpenAICompatLLM:
    """Any OpenAI-compatible chat API (Groq, OpenRouter, local Ollama, ...).
    The loop speaks Anthropic's message format, so this class translates both ways:
    the rest of the agent does not know which provider is behind it."""

    def __init__(self, api_key: str, model: str, base_url: str, max_tokens: int = 4096, timeout: float = 180):
        self.model = model
        self.max_tokens = max_tokens
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers)

    @staticmethod
    def _to_openai(system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            if m["role"] == "assistant":
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}}
                         for b in content if b.get("type") == "tool_use"]
                msg = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
                continue
            # user turn: tool results become "tool" messages, any text stays a user message
            for b in content:
                if b.get("type") == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b.get("content", "")})
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b["text"]})
        return out

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                 max_tokens: int | None = None) -> LLMResponse:
        body = {"model": self.model, "messages": self._to_openai(system, messages)}
        # OpenAI's own API wants max_completion_tokens (newer models reject max_tokens); other servers use max_tokens.
        limit_key = "max_completion_tokens" if "api.openai.com" in str(self.client.base_url) else "max_tokens"
        body[limit_key] = max_tokens or self.max_tokens
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["input_schema"]}} for t in tools]
        last = None
        for attempt in range(4):
            try:
                r = self.client.post("/chat/completions", json=body)
            except httpx.TransportError as e:
                raise LLMError(f"Cannot reach the model server at {self.client.base_url}: {e}")
            if r.status_code in (429, 500, 502, 503, 529):
                last = r.text
                time.sleep(2 ** attempt)
                continue
            if r.status_code != 200:
                raise LLMError(f"API error {r.status_code}: {r.text[:500]}")
            data = r.json()
            msg = (data.get("choices") or [{}])[0].get("message", {})
            text = msg.get("content") or ""
            content = [{"type": "text", "text": text}] if text else []
            calls = []
            for c in msg.get("tool_calls") or []:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    # Passed on as-is: schema validation rejects it with a message the model can fix.
                    args = {"unparseable_arguments": c["function"].get("arguments", "")[:500]}
                call = {"id": c.get("id") or f"call_{len(calls)}", "name": c["function"]["name"], "input": args}
                calls.append(call)
                content.append({"type": "tool_use", **call})
            usage = data.get("usage") or {}
            # OpenAI caches long prompts automatically; prompt_tokens INCLUDES the cached part.
            cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
            return LLMResponse(text=text, tool_calls=calls, content=content,
                               input_tokens=usage.get("prompt_tokens", 0) - cached, cache_read_tokens=cached,
                               output_tokens=usage.get("completion_tokens", 0),
                               stop_reason=(data.get("choices") or [{}])[0].get("finish_reason", ""))
        raise LLMError(f"API kept failing: {last[:300] if last else ''}")


class UnavailableLLM:
    """Placeholder when no model is configured: the run can still be shown, but cannot continue."""

    def __init__(self, reason: str):
        self.reason = reason

    def complete(self, *a, **kw) -> LLMResponse:
        raise LLMError(self.reason)


def make_llm(settings):
    """The model client chosen in .env (OPERATOR_PROVIDER)."""
    problem = settings.model_problem()
    if problem:
        raise LLMError(problem)
    if settings.provider == "openai":
        return OpenAICompatLLM(settings.openai_api_key, settings.model, settings.openai_base_url)
    return AnthropicLLM(settings.anthropic_api_key, settings.model, settings.anthropic_base_url)


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
