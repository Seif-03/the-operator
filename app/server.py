"""Web app: profile import/editing, starting runs, live trajectory, approval checkpoint."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from agent.config import ROOT, get_settings
from agent.llm import LLMError, make_llm
from agent.loop import AgentRun
from agent.profile import Profile, build_profile_with_llm, extract_text, fetch_url_text
from agent.render import photo_path
from agent.runner import build_goal, build_run, load_runs, save_run
from agent.tools import text_job_id, url_job_id

S = get_settings()
PROFILE_DIR = ROOT / "data" / "profiles"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE = ROOT / "sandbox" / "profiles" / "lina.json"
RUNS_DIR = ROOT / "data" / "runs"

app = FastAPI(title="The Operator")
# Runs are saved to data/runs/ after every step, so a restart does not lose a run waiting for approval.
RUNS: dict[str, AgentRun] = load_runs(RUNS_DIR)
LOCKS: dict[str, threading.Lock] = {k: threading.Lock() for k in RUNS}
STATIC = Path(__file__).parent / "static"


def _llm():
    return make_llm(S)


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def config():
    return {"mode": S.mode, "model": S.model, "provider": S.provider, "model_problem": S.model_problem(), "sandbox_url": S.sandbox_url,
            "limits": {"max_steps": S.max_steps, "max_cost_usd": S.max_cost_usd, "max_submissions": S.max_submissions}}


# ------------------------------------------------------------------ profiles
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


def _ppath(user_id: str) -> Path:
    if not SAFE_ID.match(user_id):
        raise HTTPException(400, "user id: lowercase letters, digits and dashes")
    return PROFILE_DIR / f"{user_id}.json"


@app.get("/api/profiles")
def list_profiles():
    out = [{"user_id": p.stem, "name": json.loads(p.read_text(encoding="utf-8")).get("name", "")} for p in sorted(PROFILE_DIR.glob("*.json"))]
    if not any(o["user_id"] == "lina-test" for o in out):
        out.append({"user_id": "lina-test", "name": "Lina Haddad (sample)"})
    return out


@app.get("/api/profile/{user_id}")
def get_profile(user_id: str):
    p = _ppath(user_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    if user_id == "lina-test":
        return json.loads(SAMPLE.read_text(encoding="utf-8"))
    raise HTTPException(404, "no such profile")


@app.put("/api/profile/{user_id}")
def save_profile(user_id: str, profile: Profile):
    if profile.user_id != user_id:
        raise HTTPException(400, "user_id mismatch")
    ids = [f.id for f in profile.facts]
    if len(ids) != len(set(ids)):
        raise HTTPException(400, "duplicate fact ids")
    _ppath(user_id).write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return {"saved": True}


@app.delete("/api/profile/{user_id}")
def delete_profile(user_id: str):
    p = _ppath(user_id)
    if not p.exists():
        raise HTTPException(404, "no such profile")
    p.unlink()
    photo_path(user_id).unlink(missing_ok=True)
    return {"deleted": True}


# ------------------------------------------------------------------ profile photo (never sent to the model)
@app.get("/api/profile/{user_id}/photo")
def get_photo(user_id: str):
    _ppath(user_id)
    f = photo_path(user_id)
    if not f.exists():
        raise HTTPException(404, "no photo")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/profile/{user_id}/photo")
async def upload_photo(user_id: str, file: UploadFile = File(...)):
    """Accepts any common image, crops it to a 3:4 portrait and stores a small JPEG."""
    import io
    from PIL import Image, ImageOps, UnidentifiedImageError
    _ppath(user_id)
    data = await file.read()
    if len(data) > 15_000_000:
        raise HTTPException(400, "That image is too large (max 15 MB).")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")      # respect phone rotation, drop transparency
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "That file is not an image we can read (use JPG, PNG or WebP).")
    img = ImageOps.fit(img, (450, 600), Image.LANCZOS, centering=(0.5, 0.35))   # 3:4, keep the face area
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    img.save(photo_path(user_id), "JPEG", quality=88)
    return {"saved": True}


@app.delete("/api/profile/{user_id}/photo")
def delete_photo(user_id: str):
    _ppath(user_id)
    photo_path(user_id).unlink(missing_ok=True)
    return {"deleted": True}


@app.post("/api/extract-text")
async def extract_file_text(file: UploadFile = File(...)):
    """Turn a PDF/DOCX/TXT into plain text locally (no model, no cost). Used for old CVs and letters."""
    data = await file.read()
    if len(data) > 20_000_000:
        raise HTTPException(400, f"{file.filename} is too large")
    try:
        text = extract_text(file.filename or "file.txt", data)
    except Exception:
        raise HTTPException(400, f"{file.filename} could not be opened (damaged, or not a real PDF/DOCX?)")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 30:
        raise HTTPException(400, f"{file.filename} has no readable text (is it a scanned image?)")
    return {"name": file.filename, "text": text[:20000]}


LINKEDIN_URL = re.compile(r"^https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/", re.I)


@app.post("/api/profile/import")
async def import_profile(user_id: str = Form(...), base: str = Form("{}"), urls: str = Form(""), pasted: str = Form(""),
                         files: list[UploadFile] = File(default=[])):
    """One import for everything. LinkedIn data-export ZIP/CSVs are parsed exactly; LinkedIn 'Save to PDF',
    CVs, letters, websites and pasted text are read by the model. Result is MERGED into the profile being edited."""
    from agent.linkedin import merge_into, read_export, to_profile_dict
    _ppath(user_id)
    try:
        merged = json.loads(base or "{}")
    except json.JSONDecodeError:
        merged = {}
    sources: list[tuple[str, str]] = []
    exports: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if len(data) > 50_000_000:
            raise HTTPException(400, f"{f.filename} is too large")
        name = f.filename or "file"
        if name.lower().endswith((".zip", ".csv")):
            exports.append((name, data))
        else:
            try:
                text = extract_text(name, data)
            except Exception:
                raise HTTPException(400, f"{name} could not be opened (damaged or not a real PDF/DOCX?)")
            if not text.strip():
                raise HTTPException(400, f"{name} has no readable text (is it a scanned image?)")
            sources.append((name, text))
    for u in [u.strip() for u in urls.splitlines() if u.strip()]:
        if LINKEDIN_URL.match(u):
            raise HTTPException(400, "LinkedIn pages can't be read automatically (LinkedIn blocks it). Open your profile, "
                                     "click More (or Resources) → Save to PDF, and upload that PDF here instead.")
        try:
            sources.append((u, fetch_url_text(u)))
        except Exception as e:
            raise HTTPException(400, f"Could not read {u}: {str(e)[:120]}")
    if pasted.strip():
        sources.append(("pasted text", pasted))
    if not (sources or exports):
        raise HTTPException(400, "Add your LinkedIn PDF, a CV, a link or some text first.")
    used = []
    if exports:
        tables = read_export(exports)
        if not tables:
            raise HTTPException(400, "That ZIP/CSV is not a LinkedIn data export.")
        merged = merge_into(merged, to_profile_dict(tables))
        used.append("LinkedIn data export")
    if sources:
        try:
            draft = build_profile_with_llm(user_id, sources, _llm()).model_dump()
        except LLMError as e:
            raise HTTPException(400, f"Reading PDFs/CVs needs the model: {e}")
        except Exception as e:
            raise HTTPException(500, f"Could not read the documents: {str(e)[:200]}")
        merged = merge_into(merged, draft)
        used += [s[0] for s in sources]
    merged["user_id"] = user_id
    merged.setdefault("name", "")
    merged.setdefault("email", "")
    try:
        prof = Profile.model_validate(merged)
    except Exception as e:
        raise HTTPException(400, f"Imported data did not form a valid profile: {str(e)[:200]}")
    return {"draft": prof.model_dump(), "used": used, "facts": len(prof.facts), "skills": len(prof.skills),
            "note": "Review every fact before saving. Only saved facts can be used."}


# ------------------------------------------------------------------ runs
class RunIn(BaseModel):
    user_id: str
    job_ids: list[str] = Field(default_factory=list, max_length=10)
    job_url: str = ""
    search: str = ""
    # a posting pasted by the user (plus what they typed about it: trusted)
    job_text: str = Field("", max_length=30000)
    job_title: str = Field("", max_length=150)
    job_company: str = Field("", max_length=150)
    job_location: str = Field("", max_length=100)
    apply_url: str = Field("", max_length=500)
    channel: str = Field("api", pattern="^(api|email|form)$")
    notes: str = Field("", max_length=1000)
    contact_email: str = ""
    max_submissions: int = Field(1, ge=1, le=5)
    show_browser: bool = False


def _bg(run_id: str, fn, *a, **kw):
    def work():
        run = RUNS[run_id]
        with LOCKS[run_id]:
            try:
                if fn:
                    fn(*a, **kw)
                run.run_until_pause()
            except Exception as e:  # never leave a run stuck in "running"
                run.status, run.stop_reason = "error", f"internal error: {str(e)[:300]}"
            finally:
                save_run(run, RUNS_DIR)
    threading.Thread(target=work, daemon=True).start()


@app.post("/api/runs")
def start_run(r: RunIn):
    if S.model_problem():
        raise HTTPException(400, S.model_problem())
    if not (r.job_ids or r.job_url or r.search or r.job_text.strip()):
        raise HTTPException(400, "Give job ids, a job link, a pasted posting, or a search")
    if r.job_text.strip() and len(r.job_text.strip()) < 100:
        raise HTTPException(400, "The pasted posting is too short: paste the whole job description.")
    if r.job_text.strip() and r.channel == "form" and not r.apply_url.strip():
        raise HTTPException(400, "Form filling needs the link to the application form.")
    for u in (r.job_url, r.apply_url):
        if u and not u.strip().startswith(("http://", "https://")):
            raise HTTPException(400, f"Links must start with http:// or https:// ({u[:60]})")
    if r.channel == "api" and S.mode == "real":
        raise HTTPException(400, "Direct submission exists only in sandbox mode. Choose email or form.")
    prof = Profile.model_validate(get_profile(r.user_id))
    named = len(r.job_ids) + bool(r.job_url.strip()) + bool(r.job_text.strip())
    s = get_settings(max_submissions=r.max_submissions if r.search else max(1, named))
    # The user's request defines which jobs may receive a write. Postings cannot extend this set.
    allowed: set[str] | None = None if r.search else set(r.job_ids)
    contacts: dict[str, str] = {}
    user_jobs: dict[str, dict] = {}
    typed = {"title": r.job_title.strip(), "company": r.job_company.strip(), "location": r.job_location.strip()}
    pasted_id = None
    if r.job_text.strip():
        pasted_id = text_job_id(r.job_text)
        user_jobs[pasted_id] = {**typed, "text": r.job_text.strip(), "apply_url": r.apply_url.strip()}
        if allowed is not None:
            allowed.add(pasted_id)
        if r.contact_email:
            contacts[pasted_id] = r.contact_email.strip()
    if r.job_url:
        url = r.job_url.strip()
        m = re.search(r"/(?:jobs|apply)/(J-\d{4})", url)
        jid = m.group(1) if (m and url.startswith(S.sandbox_url)) else url_job_id(url)
        if allowed is not None:
            allowed.add(jid)
        if r.contact_email:
            contacts[jid] = r.contact_email.strip()
        if jid.startswith("URL-"):
            user_jobs[jid] = typed
    goal = build_goal(r.job_ids, r.job_url.strip() or None, r.search or None, r.channel, r.notes, r.max_submissions,
                      pasted_job_id=pasted_id)
    try:
        run = build_run(prof, goal, s, allowed_job_ids=allowed, contacts=contacts, form_headed=r.show_browser,
                        user_jobs=user_jobs)
    except LLMError as e:
        raise HTTPException(400, str(e))
    RUNS[run.id] = run
    LOCKS[run.id] = threading.Lock()
    save_run(run, RUNS_DIR)
    _bg(run.id, None)
    return {"run_id": run.id}


@app.get("/api/runs")
def list_runs():
    return [{"run_id": k, "status": RUNS[k].status, "goal": RUNS[k].goal[:120],
             "jobs": [f"{j.get('title', '')} · {j.get('company', '')}".strip(" ·") for j in RUNS[k].ctx.jobs.values()]}
            for k in sorted(RUNS, reverse=True)]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "unknown run")
    return {**run.summary(), "goal": run.goal, "profile_name": run.ctx.profile.name, "events": run.events, "trajectory": run.trajectory,
            "documents": {k: {kk: vv for kk, vv in v.items() if kk in ("cv_pdf", "letter_pdf", "grounding")} for k, v in run.ctx.documents.items()},
            "busy": LOCKS[run_id].locked()}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|edit)$")
    reason: str = ""
    edits: dict[str, str] | None = None


@app.post("/api/runs/{run_id}/decision")
def decide(run_id: str, d: DecisionIn):
    run = RUNS.get(run_id)
    if not run or run.status != "awaiting_approval":
        raise HTTPException(409, "nothing to approve")
    _bg(run_id, run.resolve, d.decision, d.reason, d.edits)
    return {"ok": True}


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    add_fact: str = ""


@app.post("/api/runs/{run_id}/answer")
def answer(run_id: str, a: AnswerIn):
    run = RUNS.get(run_id)
    if not run or run.status != "awaiting_input":
        raise HTTPException(409, "no question pending")
    _bg(run_id, run.answer, a.text, a.add_fact or None)
    return {"ok": True}


@app.get("/api/file")
def get_file(path: str):
    p = Path(path).resolve()
    if not p.is_relative_to(S.output_dir.resolve()) or p.suffix != ".pdf" or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")


# ------------------------------------------------------------------ job picker (sandbox board)
# Test postings that contain prompt-injection attacks (see sandbox/README.md). Shown as a label in the UI
# so a demo can pick them on purpose; the agent itself never sees this list.
SANDBOX_ATTACK_JOBS = {"J-1008", "J-1009", "J-1010", "J-1011", "J-1012", "J-1013", "J-1016"}


@app.get("/api/jobs")
def list_jobs(q: str = ""):
    if S.mode != "sandbox":
        return {"up": False, "results": []}
    try:
        data = httpx.get(S.sandbox_url + "/api/jobs", params={"q": q, "limit": 25}, timeout=3).json()
    except Exception:
        return {"up": False, "results": []}
    return {"up": True, "results": [{**j, "attack": j["id"] in SANDBOX_ATTACK_JOBS} for j in data.get("results", [])]}


# ------------------------------------------------------------------ sandbox view
@app.get("/api/sandbox")
def sandbox_state():
    try:
        a = httpx.get(S.sandbox_url + "/api/applications", timeout=3).json()
        m = httpx.get(S.sandbox_url + "/api/mail", timeout=3).json()
        return {"applications": a["applications"], "mail": m["mail"], "up": True}
    except Exception:
        return {"up": False, "applications": [], "mail": []}


@app.post("/api/sandbox/reset")
def sandbox_reset():
    httpx.post(S.sandbox_url + "/api/reset", timeout=5)
    return {"ok": True}