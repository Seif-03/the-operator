"""Build runs, log every event to logs/<run_id>.jsonl, and a small CLI.

CLI: python -m agent.runner --profile sandbox/profiles/lina.json --job J-1001 --channel api
Approvals are asked in the terminal.
"""
from __future__ import annotations

import argparse
import re
import json
from pathlib import Path

from .config import Settings, get_settings
from .llm import LLMError, UnavailableLLM, make_llm
from .loop import AgentRun, new_run_id
from .profile import Profile, load_profile
from . import tracing
from .tools import RunContext, url_job_id

CHANNEL_TEXT = {
    "api": "Submit through the job board (submit_application).",
    "email": "Apply by email (send_application_email).",
    "form": "Fill the job's online application form (inspect_application_form, then fill_application_form). The user clicks Submit.",
    "browser": "Apply on the job's website with the browser (browser_fill_application, then browser_submit_application, "
               "which the user approves).",
}


def make_logger(settings: Settings):
    def log(run_id: str, ev: dict):
        with (settings.log_dir / f"{run_id}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    return log


def build_goal(job_ids: list[str], job_url: str | None, search: str | None, channel: str, extra: str = "", k: int = 1,
               pasted_job_id: str | None = None, web_search: bool = False, location: str = "", sites: list[str] | None = None) -> str:
    parts = []
    if pasted_job_id:
        parts.append(f"Apply for the job posting I pasted. Read it with get_job (job id {pasted_job_id}).")
    if job_ids:
        parts.append(f"Apply for job(s): {', '.join(job_ids)}.")
    if job_url:
        parts.append(f"Apply for the job at this link: {job_url}")
    if search and web_search:
        where = f" in {location}" if location else ""
        parts.append(f"Find suitable jobs for me on real job sites ({', '.join(sites or ['linkedin', 'indeed'])}) with "
                     f"web_search_jobs, matching: '{search}'{where}. Read the promising ones with read_job_url and apply to "
                     f"at most {k} that genuinely fit my profile.")
    elif search:
        parts.append(f"Find suitable jobs for me matching: '{search}'. Apply to at most {k} that genuinely fit my profile.")
    parts.append("Channel: " + CHANNEL_TEXT.get(channel, channel))
    if extra:
        parts.append("My notes: " + extra)
    return "\n".join(parts)


def build_run(profile: Profile, goal: str, settings: Settings | None = None, llm=None,
              allowed_job_ids: set[str] | None = None, contacts: dict[str, str] | None = None,
              run_id: str | None = None, form_headed: bool = False, user_jobs: dict[str, dict] | None = None) -> AgentRun:
    s = settings or get_settings()
    llm = llm or make_llm(s)
    ctx = RunContext(settings=s, profile=profile.model_copy(deep=True), run_id=run_id or new_run_id(),
                     allowed_job_ids=allowed_job_ids, user_contact_emails=contacts or {}, form_headed=form_headed,
                     user_jobs=user_jobs or {})
    return AgentRun(ctx, llm, goal, s, logger=make_logger(s))


# ------------------------------------------------------------ runs saved to disk (data/runs/<run_id>.json)
def save_run(run: AgentRun, runs_dir: Path) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    tmp = runs_dir / f"{run.id}.json.tmp"
    tmp.write_text(json.dumps(run.to_state(), ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(runs_dir / f"{run.id}.json")     # write-then-rename: never leaves a half-written file


def load_runs(runs_dir: Path) -> dict[str, AgentRun]:
    """Reload every saved run. Runs waiting for approval can be approved after a restart."""
    try:
        llm = make_llm(get_settings())
    except LLMError as e:
        llm = UnavailableLLM(str(e))
    runs = {}
    for f in sorted(runs_dir.glob("*.json")):
        try:
            state = json.loads(f.read_text(encoding="utf-8"))
            s = get_settings(max_submissions=state.get("max_submissions", 1))
            runs[state["run_id"]] = AgentRun.from_state(state, s, llm, logger=make_logger(s))
        except Exception as e:  # one damaged file must not stop the app
            print(f"Skipping saved run {f.name}: {e}")
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--job", action="append", default=[])
    ap.add_argument("--url")
    ap.add_argument("--search")
    ap.add_argument("--channel", choices=["api", "email", "form", "browser"], default="api")
    ap.add_argument("--web", action="store_true", help="with --search: search real job sites with browser-use")
    ap.add_argument("--location", default="")
    ap.add_argument("--notes", default="")
    a = ap.parse_args()
    s = get_settings()
    if a.channel == "browser" or a.web:
        s.browser_use = True
    if s.model_problem():
        raise SystemExit(s.model_problem())
    prof = load_profile(a.profile)
    allowed = set(a.job) if a.job else None
    if a.url and not a.search:
        m = re.search(r"/(?:jobs|apply)/(J-\d{4})", a.url)
        allowed = (allowed or set()) | {m.group(1) if (m and a.url.startswith(s.sandbox_url)) else url_job_id(a.url)}
    run = build_run(prof, build_goal(a.job, a.url, a.search, a.channel, a.notes, web_search=a.web, location=a.location),
                    s, allowed_job_ids=allowed)
    while True:
        st = run.run_until_pause()
        if st == "awaiting_approval":
            print(json.dumps(run.pending.preview, indent=2, ensure_ascii=False, default=str)[:6000])
            d = input("Approve this action? [y/N/reason to reject]: ").strip()
            run.resolve("approve") if d.lower() in ("y", "yes") else run.resolve("reject", reason=d)
        elif st == "awaiting_input":
            ans = input(f"Agent asks: {run.pending.preview['question']}\n> ")
            add = input("Add this as a confirmed fact to your profile? Type the fact or leave empty: ").strip()
            run.answer(ans, add or None)
        else:
            break
    print(json.dumps(run.summary(), indent=2, default=str))
    tracing.flush()


if __name__ == "__main__":
    main()