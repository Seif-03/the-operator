"""Form-fill mode: open an application page in a real browser, read the form, fill it.

Hard rule enforced HERE, not in the prompt: this module has no code path that clicks,
presses Enter in, or submits a form. It only sets field values and attaches the CV file.
The user reviews the filled page and clicks Submit themselves.

Runs Playwright in a child process (python -m agent.formfill <json>) so a headed browser
can stay open for the user after the agent's tool call returns.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INSPECT_JS = r"""
() => {
  const out = [];
  const els = document.querySelectorAll('input, textarea, select');
  for (const el of els) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden','submit','button','reset','image'].includes(type)) continue;
    let label = '';
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) label = l.innerText; }
    if (!label && el.closest('label')) label = el.closest('label').innerText;
    if (!label) label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '';
    const sel = el.id ? `#${CSS.escape(el.id)}` : (el.name ? `[name="${el.name}"]` : null);
    if (!sel) continue;
    const opts = el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.text).slice(0, 30) : undefined;
    out.push({selector: sel, label: label.trim().slice(0, 120), type, required: el.required, options: opts});
  }
  return out;
}
"""


def _launch(p, headless: bool):
    try:
        return p.chromium.launch(headless=headless, channel="chrome")
    except Exception:
        return p.chromium.launch(headless=headless)


def _worker(args: dict) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = _launch(p, headless=args.get("headless", True))
        page = browser.new_page()
        page.goto(args["url"], timeout=20000)
        page.wait_for_load_state("domcontentloaded")
        if args["op"] == "inspect":
            fields = page.evaluate(INSPECT_JS)
            text = page.inner_text("body")[:8000]
            print(json.dumps({"ok": True, "fields": fields, "page_text": text}), flush=True)
            browser.close()
            return
        report = []
        for sel, val in args.get("values", {}).items():
            try:
                el = page.locator(sel).first
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                typ = (el.get_attribute("type") or "").lower()
                if typ in ("submit", "button", "image", "reset"):
                    report.append({"selector": sel, "status": "refused_button"})
                    continue
                if typ == "file":
                    if args.get("cv_path"):
                        el.set_input_files(args["cv_path"])
                        report.append({"selector": sel, "status": "attached_cv"})
                    continue
                if tag == "select":
                    el.select_option(label=str(val))
                elif typ in ("checkbox", "radio"):
                    el.set_checked(bool(val))
                else:
                    el.fill(str(val))       # fill() never submits
                report.append({"selector": sel, "status": "filled"})
            except Exception as e:  # keep going, report the field
                report.append({"selector": sel, "status": f"error: {str(e)[:120]}"})
        values_now = page.evaluate("() => Object.fromEntries(Array.from(document.querySelectorAll('input,textarea,select'))"
                                   ".filter(e => e.type !== 'file' && (e.id || e.name)).map(e => [e.id ? '#' + e.id : e.name, e.value]))")
        print(json.dumps({"ok": True, "report": report, "values_now": values_now, "url": page.url}), flush=True)
        if args.get("keep_open"):
            # Leave the window for the user: they check it and click Submit themselves.
            try:
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
        browser.close()


def _run(args: dict, timeout: float = 60) -> dict:
    cmd = [sys.executable, "-m", "agent.formfill", json.dumps(args)]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if args.get("keep_open"):
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", env=env)
        line = proc.stdout.readline()          # first line = result; process keeps the window open
        if not line:
            return {"ok": False, "error": (proc.stderr.read() or "browser failed")[-400:]}
        return json.loads(line)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0 or not r.stdout.strip():
        return {"ok": False, "error": (r.stderr or "browser failed")[-400:]}
    return json.loads(r.stdout.strip().splitlines()[-1])


def inspect_form(url: str) -> dict:
    return _run({"op": "inspect", "url": url, "headless": True})


def fill_form(url: str, values: dict[str, str], cv_path: str | None, headless: bool, keep_open: bool) -> dict:
    return _run({"op": "fill", "url": url, "values": values, "cv_path": cv_path, "headless": headless, "keep_open": keep_open})


if __name__ == "__main__":
    _worker(json.loads(sys.argv[1]))