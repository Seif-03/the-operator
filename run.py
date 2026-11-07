"""One run command: starts the sandbox job board (port 8100) and the web app (port 8000).

    python run.py            -> open http://127.0.0.1:8000
"""
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    if not (ROOT / ".env").exists():
        print("No .env file yet: run  python install.py  first (or copy .env.example to .env).")
    env = {**os.environ}
    procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "sandbox.jobboard:app", "--port", "8100", "--log-level", "warning"], cwd=ROOT, env=env),
             subprocess.Popen([sys.executable, "-m", "uvicorn", "app.server:app", "--port", "8000", "--log-level", "warning"], cwd=ROOT, env=env)]
    time.sleep(3)
    if any(p.poll() is not None for p in procs):
        for p in procs:
            p.terminate()
        sys.exit("\nCould not start. Is port 8000 or 8100 already in use (another copy of The Operator still running)? "
                 "See the error above.")
    print("\n  The Operator  ->  http://127.0.0.1:8000\n  Sandbox board ->  http://127.0.0.1:8100\n  Ctrl+C to stop\n")
    if "--no-browser" not in sys.argv:
        try:
            webbrowser.open("http://127.0.0.1:8000")
        except Exception:
            pass
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
