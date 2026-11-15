"""Model clients. AnthropicLLM talks to the Messages API with plain httpx;
ScriptedLLM replays fixed tool calls (used by unit tests and the harness self-check)."""
from __future__ import annotations

import json
import random
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
    model: str = ""                 # the model that answered (differs from OPERATOR_MODEL after a fallback)


class LLMError(RuntimeError):
    pass


# Busy / rate-limited / temporarily down: worth waiting and trying again (or trying a fallback model).
TRANSIENT_STATUS = (429, 500, 502, 503, 504, 529)


def _backoff(attempt: int, r: httpx.Response | None = None, cap: float = 20.0) -> float:
    """Seconds to wait before the next try: the server's Retry-After if it sent one, else exponential with jitter."""
    if r is not None:
        try:
            return min(float(r.headers.get("retry-after", "")), cap)
        except ValueError:
            pass
    return min(2 ** attempt, cap) * (0.75 + random.random() / 2)


def _error_text(r: httpx.Response) -> str:
    """The provider's own error message. Gemini wraps it in a list: [{"error": {...}}]."""
    try:
        data = r.json()
    except ValueError:
        return r.text[:300]
    if isinstance(data, list) and data:
        data = data[0]
    err = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(err, dict):
        msg = err.get("message") or json.dumps(err)
        status = err.get("status") or err.get("type") or ""
        return f"{msg} ({status})" if status else msg
    return str(err)[:300]


# Keywords Gemini's OpenAI-compatible endpoint is picky about. Dropping them changes nothing for safety:
# every tool input is still validated by its strict Pydantic schema before it runs.
_GEMINI_DROP = {"title", "default", "additionalProperties", "$schema"}


def _strip_schema(node):
    """Remove _GEMINI_DROP keywords from a JSON schema. Names inside "properties" are field names, never dropped."""
    if isinstance(node, list):
        return [_strip_schema(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "properties" and isinstance(v, dict):
            out[k] = {name: _strip_schema(sub) for name, sub in v.items()}
        elif k not in _GEMINI_DROP:
            out[k] = _strip_schema(v)
    return out


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
        last, tries = None, 5
        for attempt in range(tries):  # retry rate limits / overload with backoff
            r = self.client.post("/v1/messages", json=body)
            if r.status_code in TRANSIENT_STATUS:
                last = f"HTTP {r.status_code}: {_error_text(r)}"
                if attempt < tries - 1:
                    time.sleep(_backoff(attempt, r))
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
        raise LLMError(f"The model API is busy or rate-limiting ({tries} tries on {self.model}). {last or ''} "
                       "Wait a minute and start the run again.")


class OpenAICompatLLM:
    """Any OpenAI-compatible chat API (Groq, OpenRouter, local Ollama, ...).
    The loop speaks Anthropic's message format, so this class translates both ways:
    the rest of the agent does not know which provider is behind it."""

    def __init__(self, api_key: str, model: str, base_url: str, max_tokens: int = 4096, timeout: float = 180,
                 fallback_models: list[str] | tuple = (), tries_per_model: int = 4):
        self.model = model
        self.fallback_models = [m for m in fallback_models if m and m != model]
        self.tries_per_model = max(1, tries_per_model)
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
        base = str(self.client.base_url)
        body = {"messages": self._to_openai(system, messages)}
        # OpenAI's own API wants max_completion_tokens (newer models reject max_tokens); other servers use max_tokens.
        limit_key = "max_completion_tokens" if "api.openai.com" in base else "max_tokens"
        body[limit_key] = max_tokens or self.max_tokens
        if tools:
            gemini = "generativelanguage.googleapis.com" in base
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": _strip_schema(t["input_schema"]) if gemini else t["input_schema"]}} for t in tools]
        failures = []
        for model in [self.model, *self.fallback_models]:
            body["model"] = model
            last = None
            for attempt in range(self.tries_per_model):
                try:
                    r = self.client.post("/chat/completions", json=body)
                except httpx.TimeoutException as e:      # slow / overloaded server: try again
                    last = f"timed out ({type(e).__name__})"
                    if attempt < self.tries_per_model - 1:
                        time.sleep(_backoff(attempt))
                    continue
                except httpx.TransportError as e:        # wrong URL / server not running: retrying won't help
                    raise LLMError(f"Cannot reach the model server at {self.client.base_url}: {e}")
                if r.status_code in TRANSIENT_STATUS:
                    last = f"HTTP {r.status_code}: {_error_text(r)}"
                    if attempt < self.tries_per_model - 1:
                        time.sleep(_backoff(attempt, r))
                    continue
                if r.status_code == 404 and model != ([self.model, *self.fallback_models])[-1]:
                    last = f"HTTP 404 (model not found): {_error_text(r)[:200]}"
                    break               # this model does not exist (any more): try the next one
                if r.status_code != 200:
                    raise LLMError(f"API error {r.status_code} from {model}: {_error_text(r)[:500]}")
                return self._parse(r.json(), model)
            failures.append(f"{model}: {last}")
        hint = ("Free models are often overloaded: wait a minute and start the run again"
                + ("." if self.fallback_models else
                   ", or set OPERATOR_FALLBACK_MODELS in .env (e.g. a lighter model) so the agent switches automatically."))
        raise LLMError(f"The model provider is busy or rate-limiting. {' | '.join(failures)[:400]}. {hint}")

    @staticmethod
    def _parse(data: dict, model: str) -> LLMResponse:
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
                           stop_reason=(data.get("choices") or [{}])[0].get("finish_reason", ""), model=model)


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
        return OpenAICompatLLM(settings.openai_api_key, settings.model, settings.openai_base_url,
                               fallback_models=settings.fallback_models, tries_per_model=settings.llm_tries)
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
