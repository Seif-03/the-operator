"""Settings, read from environment / .env (never commit real keys)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


@dataclass
class Settings:
    # "sandbox" = all writes go to the fake job board + mock mailbox (default, used for evals/demo)
    # "real"    = email goes out over SMTP, form fill opens real pages (user still clicks Submit)
    mode: str = os.environ.get("APPLY_MODE", "sandbox")
    sandbox_url: str = os.environ.get("SANDBOX_URL", "http://127.0.0.1:8100")

    # "anthropic" = Claude via the Anthropic API (default)
    # "openai"    = any OpenAI-compatible server: Groq, OpenRouter, a local Ollama, ...
    provider: str = os.environ.get("OPERATOR_PROVIDER", "anthropic").strip().lower()
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    anthropic_base_url: str = os.environ.get("OPERATOR_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base_url: str = os.environ.get("OPENAI_BASE_URL") or "http://localhost:11434/v1"   # empty in .env -> Ollama
    model: str = os.environ.get("OPERATOR_MODEL") or "claude-haiku-5-5"
    # USD per million tokens (Haiku 5.5 list price). Set these in .env when you change the model.
    price_in_per_mtok: float = _f("PRICE_IN_PER_MTOK", 0.10)
    price_out_per_mtok: float = _f("PRICE_OUT_PER_MTOK", 0.50)
    # Prompt-cache prices relative to the input price. Anthropic: write 1.25x, read 0.1x.
    # OpenAI caches automatically: no write premium, reads 0.25x on gpt-4.1 models (check your model's price page).
    cache_write_factor: float = _f("CACHE_WRITE_FACTOR", 1.0 if provider == "openai" else 1.25)
    cache_read_factor: float = _f("CACHE_READ_FACTOR", 0.25 if provider == "openai" else 0.10)

    # ---- stop rule (hard limits enforced in code) ----
    max_steps: int = int(os.environ.get("MAX_STEPS", 20))
    max_cost_usd: float = _f("MAX_COST_USD", 0.50)
    max_tokens_total: int = int(os.environ.get("MAX_TOKENS_TOTAL", 250_000))
    max_wall_seconds: float = _f("MAX_WALL_SECONDS", 600)
    max_submissions: int = int(os.environ.get("MAX_SUBMISSIONS", 1))
    max_identical_calls: int = int(os.environ.get("MAX_IDENTICAL_CALLS", 3))
    tool_timeout_s: float = _f("TOOL_TIMEOUT_S", 2.0)
    tool_retries: int = int(os.environ.get("TOOL_RETRIES", 1))

    # ---- real-mode email (SMTP) ----
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SMTP_PORT", 587))
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")

    output_dir: Path = field(default_factory=lambda: ROOT / "outputs")
    log_dir: Path = field(default_factory=lambda: ROOT / "logs")

    def model_problem(self) -> str:
        """Empty string if a model is configured, otherwise what the user must fix."""
        if self.provider == "anthropic":
            return "" if self.anthropic_api_key else "Set ANTHROPIC_API_KEY in .env (or choose a free provider, see .env.example) and restart."
        if self.provider == "openai":
            local = "localhost" in self.openai_base_url or "127.0.0.1" in self.openai_base_url
            return "" if (self.openai_api_key or local) else "Set OPENAI_API_KEY in .env for your provider and restart."
        return f"Unknown OPERATOR_PROVIDER '{self.provider}': use 'anthropic' or 'openai'."


def get_settings(**overrides) -> Settings:
    s = Settings()
    for k, v in overrides.items():
        setattr(s, k, v)
    s.output_dir.mkdir(parents=True, exist_ok=True)
    s.log_dir.mkdir(parents=True, exist_ok=True)
    return s