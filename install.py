"""One setup command, same on Windows, macOS and Linux:

    python install.py

Installs the Python packages, the Chromium browser used by form-fill mode,
and creates .env from .env.example if it does not exist yet.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def step(title: str, cmd: list[str]) -> None:
    print(f"\n== {title}")
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        sys.exit(f"\nFailed: {' '.join(cmd)}")


def main() -> None:
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is needed.")
    step("Installing Python packages", [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    step("Installing the browser for form-fill mode", [sys.executable, "-m", "playwright", "install", "chromium"])
    env = ROOT / ".env"
    if env.exists():
        print("\n== .env already exists, left unchanged")
    else:
        shutil.copy(ROOT / ".env.example", env)
        print("\n== Created .env from .env.example")
    print("\nDone. Next: open .env and set your model (ANTHROPIC_API_KEY, or a free provider), then run:  python run.py")


if __name__ == "__main__":
    main()
