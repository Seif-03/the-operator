import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.config import get_settings  # noqa: E402
from agent.profile import load_profile  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="session")
def sandbox_url():
    port = _free_port()
    db = Path(tempfile.mkdtemp()) / "test.db"
    env = {**os.environ, "SANDBOX_DB": str(db), "SANDBOX_TIMEOUT_SLEEP": "2.5"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "sandbox.jobboard:app", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(url + "/api/jobs", timeout=0.5)
            break
        except Exception:
            time.sleep(0.2)
    yield url
    proc.terminate()


@pytest.fixture
def sandbox(sandbox_url):
    httpx.post(sandbox_url + "/api/reset")
    return sandbox_url


@pytest.fixture
def settings(sandbox, tmp_path):
    return get_settings(sandbox_url=sandbox, output_dir=tmp_path / "out", log_dir=tmp_path / "logs", mode="sandbox",
                        tool_timeout_s=1.0)


@pytest.fixture
def profile():
    return load_profile(ROOT / "sandbox/profiles/lina.json")


GOOD_CV = {
    "headline": "Computer Science student focused on data and Python",
    "summary": {"text": "B.Sc. Computer Science student with hands-on Python and SQL work in university projects.", "fact_ids": ["F1", "F3"]},
    "sections": [
        {"title": "Education", "items": [{"heading": "B.Sc. Computer Science, TU Darmstadt (2023 - present)", "text": "", "fact_ids": ["F1"]}]},
        {"title": "Projects", "items": [{"heading": "RAG chatbot over legal documents", "text": "Built the FastAPI backend of a RAG chatbot with a React frontend.", "fact_ids": ["F3"]}]},
    ],
    "skills": ["Python", "SQL", "PostgreSQL", "FastAPI"],
    "languages": ["English (fluent, C1)", "German (B2)"],
}
GOOD_LETTER = {"text": "Dear Rhein Mobility team,\n\nI am a computer science student in Darmstadt and I would like to join you as a working student. "
                       "In a university project I built the FastAPI backend of a RAG chatbot, and I work with Python and SQL.\n\n"
                       "I have not yet used Airflow, but I am eager to learn it.\n\nKind regards,\nLina Haddad",
               "fact_ids": ["F1", "F3"]}
