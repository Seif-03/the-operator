"""LangSmith tracing (optional).

Turn it on in .env:
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=lsv2_...
    LANGSMITH_PROJECT=the-operator            (optional, default "the-operator")

What is traced (one LangSmith *thread* per agent run, keyed by the run id):
    operator.run_until_pause   chain   one stretch of the loop, until it finishes or pauses for the human
      llm.complete             llm     every model call, with token usage (LangSmith computes the cost)
      tool:<name>              tool    every tool call, with its arguments and result
        browser_use.<op>       chain   browser-use runs inside the browser tools, with their token usage
    operator.resolve           chain   the human's decision at a checkpoint and the write it runs
The eval can also log each scenario as an experiment run with its scores as feedback (eval/run_eval.py --langsmith).

Without the variables, or without the langsmith package, every function here is a no-op:
the agent never depends on LangSmith being reachable.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, Callable

os.environ.setdefault("LANGSMITH_PROJECT", "the-operator")

try:  # optional dependency
    import langsmith as _ls
    from langsmith import traceable as _traceable
    from langsmith.run_helpers import get_current_run_tree as _current
except Exception:  # pragma: no cover - only when the package is missing
    _ls = None
    _traceable = None
    _current = None


def enabled() -> bool:
    flag = (os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2") or "").strip().lower()
    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    return _ls is not None and flag in ("1", "true", "yes") and bool(key)


def traceable(*dargs, **dkwargs) -> Callable:
    """langsmith.traceable when installed, else a decorator that does nothing.
    (langsmith's own decorator already skips sending when tracing is off.)"""
    if _traceable is not None:
        return _traceable(*dargs, **dkwargs)

    def deco(fn):
        return fn
    if dargs and callable(dargs[0]) and not dkwargs:
        return dargs[0]
    return deco


def set_usage(input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0, model: str = "",
              provider: str = "") -> None:
    """Attach token usage to the current LangSmith run (shown as tokens and cost in the UI)."""
    if not enabled() or _current is None:
        return
    with contextlib.suppress(Exception):
        rt = _current()
        if rt is None:
            return
        details = {}
        if cache_read:
            details["cache_read"] = cache_read
        if cache_write:
            details["cache_creation"] = cache_write
        usage = {"input_tokens": input_tokens + cache_read + cache_write, "output_tokens": output_tokens,
                 "total_tokens": input_tokens + cache_read + cache_write + output_tokens}
        if details:
            usage["input_token_details"] = details
        rt.set(usage_metadata=usage)
        if model:
            rt.metadata.update({"ls_model_name": model, "ls_provider": provider or "unknown"})


def add_metadata(**meta: Any) -> None:
    if not enabled() or _current is None:
        return
    with contextlib.suppress(Exception):
        rt = _current()
        if rt is not None:
            rt.metadata.update(meta)


def current_run_id() -> str | None:
    if not enabled() or _current is None:
        return None
    with contextlib.suppress(Exception):
        rt = _current()
        return str(rt.id) if rt is not None else None
    return None


def run_metadata(run_id: str, **extra: Any) -> dict:
    """Metadata that groups every trace of one agent run into one LangSmith thread."""
    return {"thread_id": run_id, "session_id": run_id, "operator_run_id": run_id, **extra}


@contextlib.contextmanager
def trace(name: str, run_type: str = "chain", inputs: dict | None = None, **kw):
    """langsmith.trace when tracing is on; otherwise yields None."""
    if not enabled():
        yield None
        return
    try:
        cm = _ls.trace(name, run_type=run_type, inputs=inputs or {}, **kw)
        rt = cm.__enter__()
    except Exception:
        yield None
        return
    exc = (None, None, None)
    try:
        yield rt
    except BaseException as e:
        exc = (type(e), e, e.__traceback__)
        raise
    finally:
        with contextlib.suppress(Exception):
            cm.__exit__(*exc)


def client():
    return _ls.Client() if enabled() else None


def flush() -> None:
    """Send pending traces now (the CLI and the eval exit right after a run)."""
    if not enabled():
        return
    with contextlib.suppress(Exception):
        from langsmith.run_trees import get_cached_client
        get_cached_client().flush()
