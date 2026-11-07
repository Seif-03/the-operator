# The Operator — a job-application agent

CS496 AI Engineering · Project 3 · MedTech, Fall 2026

Give it your CV, LinkedIn export, website or old cover letters. It builds a reviewed profile of **true facts**, tailors a CV and cover letter to a job posting, and applies in one of three ways, always after you approve:

| Channel | What the write does | Who presses the final button |
|---|---|---|
| **Job board** (`submit_application`) | submits to the sandbox board API | you approve, agent submits |
| **Email** (`send_application_email`) | sends CV + letter PDFs to the job's address on record | you approve, agent sends |
| **Form fill** (`fill_application_form`) | opens the application page in a browser and fills it | **you click Submit** — the agent cannot |

Everything runs against a **resettable sandbox** (fake job board, application forms, mailbox) by default. `APPLY_MODE=real` switches email to SMTP and form-fill to real pages.

## Setup (one command, Windows / macOS / Linux)

```bash
python install.py
```
It installs the packages and the browser for form-fill mode, and creates `.env`. Then choose the model in `.env`:

- **Claude (default, used for the eval):** set `ANTHROPIC_API_KEY`.
- **Free:** set `OPERATOR_PROVIDER=openai` and an OpenAI-compatible server (Groq, OpenRouter, or a local Ollama); examples are in `.env.example`. Free models are weaker at multi-step tool use.

## Run (one command)

```bash
python run.py
```
Open http://127.0.0.1:8000. The sandbox job board is at http://127.0.0.1:8100.
Runs are saved in `data/runs/`, so a run waiting for your approval survives a restart.
Flow: **Profile** (import + review facts) → **Apply** (job ids / link / pasted posting / search + channel) → **Run** (live trajectory, approval card) → **Sandbox** (see what was written, reset).

CLI alternative: `python -m agent.runner --profile sandbox/profiles/lina.json --job J-1001 --channel api`

## Tests and eval

```bash
pytest -q                              # 39 tests: stop rule, checkpoint, idempotency, policies, form never submits, saved runs
python -m eval.run_eval                # 40 trajectory scenarios with the real model -> eval/results/<model>/
python -m eval.run_eval --only I01,I03 # a subset
python -m eval.run_eval --policy selftest   # harness check without an API key (not a result)
```

## Results

> Fill in after `python -m eval.run_eval` (copy from `eval/results/<model>/results.md`).

| Metric | Value |
|---|---|
| Task success (40 scenarios) | _tbd_ |
| Step accuracy / tool-call precision | _tbd_ |
| Recovery after failure | _tbd_ |
| Injection cases defended | _tbd_ / 10 |
| Stop-rule violations | _tbd_ (limit: 20 tool calls) |
| Cost per task · p50 / p95 time | _tbd_ |
| Cost at 100× | _tbd_ |

## Layout

```
agent/        tools.py (schemas, writes, policies) · loop.py (loop, stop rule, checkpoint)
              grounding.py (no-fabrication check) · guards.py (injection defenses)
              profile.py (import) · render.py (PDFs) · formfill.py (browser, never submits) · llm.py · runner.py
sandbox/      jobboard.py (fake board + forms + mailbox + fault injection) · seed_jobs.json · profiles/
app/          server.py + static/index.html (web UI)
eval/         scenarios.json (40) · run_eval.py · results/
tests/        unit tests with a scripted model
errors.md  threat_model.md  postmortem.md  docs/report.md
```

## Safety in one paragraph

Writes never run when the model calls them: the loop pauses and shows the exact action, and only the approved arguments run. The **stop rule** (20 tool calls, $0.50, 250k tokens, 10 min, 3 identical calls) is checked before every model and tool call. **Grounding**: CV items must cite profile fact ids, and a deterministic checker blocks skills, degrees, institutions, years of experience and languages the profile does not support. **Injection**: postings, pages and old letters come back wrapped as `UNTRUSTED_DATA` with flags. Write tools take no free-form recipient or job list, so the email address comes from the board's record, only jobs the user named can receive a write, private fields never reach the model and are blocked in outgoing text, and form fill has no code path that clicks. Details: `threat_model.md`.

## Contributions

| Member | Contribution |
|---|---|
| _name_ | _e.g. agent loop, stop rule, tests_ |
| _name_ | _e.g. sandbox, eval harness_ |
| _name_ | _e.g. web UI, form-fill mode_ |
| _name_ | _e.g. threat model, injection cases, report_ |

No real credentials are in this repo. `.env` is git-ignored.
