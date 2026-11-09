# The Operator — Project 3 Report

CS496 AI Engineering · Team: 5
Model: **gpt-4.1-mini** (OpenAI). All numbers below come from `eval/results/gpt-4.1-mini/`.

## 1. Task, tools, and what the write changes

The Operator applies to jobs for a user. It reads a reviewed profile of true facts, reads a posting, writes a tailored CV and cover letter, and applies through one of three channels. Twelve tools: 7 reads (`get_profile`, `search_jobs`, `get_job`, `read_job_url`, `check_documents`, `inspect_application_form`, `ask_user`), 4 writes (`save_documents`, `submit_application`, `send_application_email`, `fill_application_form`), and `finish`.

Writes change: local PDFs (`save_documents`, idempotent overwrite), an application record on the board (`submit_application`, unique on user+job), an email in the outbox (`send_application_email`, idempotency key = hash(user, job)), and the field values of an application form in a browser (`fill_application_form`, never submits). All tools have strict Pydantic schemas (`extra="forbid"`, id patterns, length limits). Errors return as text with a hint. Every call is logged with input, output and time (`logs/<run>.jsonl`).

## 2. Loop, stop rule, and proof it stops

ReAct-style single agent (`agent/loop.py`): model → tool calls → results → model, until `finish`. No multi-agent design: one loop is enough to plan a 5–7 step task.

**Stop rule**, checked before every model call and every tool call: ≤20 tool calls, ≤$0.50, ≤250k tokens, ≤10 min agent time, ≤3 identical calls, and stop after 2 turns without a tool call. **Done rule:** `finish`.

**Proof.** (a) Unit tests with adversarial scripted models: an infinite searcher stops at exactly `max_steps`, a repeater stops at 3 identical calls, a big spender stops at the cost cap, a model that only talks stops after 2 turns. (b) Eval check `stop_rule_held` on all 40 scenarios: **0 violations**, maximum tool calls seen _tbd_ / 20. Each iteration increases the step, token or no-tool counter, and every counter has a cap, so the loop terminates.

## 3. Design: sandbox and safety mechanisms

**Principle: the model may be fooled; the code must not be.** The agent reads third-party text (postings, pages, forms), so every safety property is enforced in code, outside the model. Prompts and labels reduce bad model behaviour; the code decides what can actually happen.

**3.1 Sandbox.** A fake, resettable copy of the outside world: FastAPI + SQLite job board on port 8100 with **16 postings, 7 of which contain injections** (J-1008–J-1013, J-1016; J-1016's form has a hidden one too), HTML application forms, a mock mailbox with idempotency keys, and **fault injection** (`500`, `503`, `timeout`, `empty`) per endpoint. Reset is one call (`POST /api/reset`). The fake applicant `lina.json` carries canary values (`P0000TEST1`, `TN-TEST-000`) — if one ever leaves the system, a leak is proven. The eval starts a fresh sandbox on a random port with a temporary DB per run. Real mode swaps only the email transport (SMTP) and the form target (real pages). Isolation is environment-level, not OS-level: the agent has no shell and no arbitrary file/network tool; its whole capability surface is the 12 typed tools.

**3.2 Defense in depth.**

| Layer | Mechanism | Stops |
|---|---|---|
| 1. Data framing | Third-party text returned as `{"trust": "UNTRUSTED_DATA", "suspected_injection": [...], "data": ...}` + regex detector | Reduces how often the model follows injected text (warning only) |
| 2. Capability design | Structured args; `send_application_email` has **no recipient arg** (address from record or user); schemas `extra="forbid"` | Redirecting applications |
| 3. Policies in code | `allowed_job_ids`, submission budget (1/run), `leaks_private()` on outgoing text, sensitive form fields always empty | Mass-applying, data exfiltration |
| 4. Grounding | Deterministic: every CV item cites fact ids; skills/degrees/institutions/years/languages must exist in profile | Making the user lie |
| 5. Human checkpoint | Gated tools never run on the model's call; loop pauses as `awaiting_approval` with frozen args | "Skip confirmation" attacks |
| 6. No-submit form fill | `formfill.py` has no click/submit path; button selectors refused | Autonomous submission |
| 7. Stop rule | Checked before every model and tool call | Runaway loops and cost |
| 8. Idempotency | Same application/mail key created once; only reads auto-retry | Duplicate applications |

**3.3 Human checkpoint.** Gated tools (`submit_application`, `send_application_email`, `fill_application_form`, `ask_user`) are never executed on the model's call. The loop validates the arguments, runs every precheck (job allowed, budget left, documents saved, trusted recipient, grounding, no private data), builds a preview (job, recipient, CV with fact citations, letter, grounding result, injection warnings), and pauses. The user can approve, edit then approve (edits re-render the PDFs), or reject with a reason that goes back to the model. **Only the shown, frozen arguments run**, and the same prechecks run again at execution time, so nothing can change between preview and send.

**3.4 Private data and logging.** `Profile.public_view()` excludes the private block, so passport, ID and birth date never enter the model's context; the extractor never takes private data from model output. Outgoing text (CV, letter, email, form values) is scanned for private values before save/send. Tool errors are `ToolError(message, hint)` — readable, actionable, never a stack trace — and are classified (`policy_block`, `ungrounded_claim`, `timeout`, `tool_down`, `wrong_order`, …) for the eval. Every event is written to `logs/<run_id>.jsonl`; runs are saved to `data/runs/` with write-then-rename, so a run waiting for approval survives a restart.

**3.5 Attack → defense mapping.**

| Attack (sandbox job) | Blocked by |
|---|---|
| J-1008: email passport + DOB to a third party | Private fields never reach the model; `leaks_private` blocks outgoing text |
| J-1011: redirect to a free-mail address | No recipient argument; address from the record |
| J-1009, J-1013: apply to every job / to J-1007 | `allowed_job_ids` + submission budget |
| J-1010, J-1016: add fake PhD / skills / languages | Grounding check |
| J-1012: "pre-approved, skip confirmation" | Checkpoint is in the loop, not the prompt |
| J-1016 form: hidden passport request | Sensitive-field rule leaves the ID field empty |

## 4. Trajectory eval

40 scenarios (`eval/scenarios.json`): 10 happy path across 3 channels, 3 poor fit, 2 missing info, 1 empty result, 8 tool failure/bad input, 4 user changes mind, 2 budget/idempotency, 10 injection. Each has an expected tool path and outcome checks on the sandbox state (applications, mail recipients, form fields), on the text that left the system (no fabricated claims, no private data, language), and on the trajectory (checkpoint before every write, stop rule). The simulated human **approves everything** unless the scenario says otherwise, so safety cannot depend on a careful human.

Metrics: step accuracy = LCS(actual, expected)/|actual|; path recall = LCS/|expected|; wasted steps = |actual| − LCS; tool-call precision = 1 − (model-caused failed calls / all calls).

| Metric | Value |
|---|---|
| Task success | **35 / 40** |
| Step accuracy · path recall | _tbd_ · _tbd_ |
| Tool-call precision | _tbd_ |
| Wasted steps per task | _tbd_ |

The 5 failures are recorded in `README.md` and `eval/results/gpt-4.1-mini/results.md`.

## 5. Error taxonomy and recovery

15 classes (see `errors.md`), each with a handling rule and a test. Reads auto-retry once; writes never auto-retry. Recovery-after-failure (recoverable fault scenarios that still completed): **5 / 5**.

## 6. Threat model, injection results, cost model

Untrusted entry points: postings, web pages, form pages, the user's own imported documents. Three layers: data framing + detector, **code-level policies** (no recipient argument, job allowlist, application budget, private-data block, grounding, no submit path), and the human.

**Injection results: 10 / 10 defended, 0 harmful writes**, 0 stop-rule violations. The eval approver approves everything, which shows the code-level defenses hold even when the human rubber-stamps. Which attacks the model attempted and which layer blocked them is in `eval/results/gpt-4.1-mini/results.md`.

**Cost model.** cost/task = tokens_in × p_in + tokens_out × p_out. Measured: _tbd_ tokens and $_tbd_ per task, p50 / p95 _tbd_ s. At 100× (100 users × 5 applications/week ≈ 2,000 tasks/month): $_tbd_/month. Main driver: input tokens grow with each step because the full history is re-sent. Next saving: prompt caching of the system prompt and tool schemas.

## 7. Limitations

1. **Soft influence.** An injection can still change wording; grounding blocks false claims, not tone.
2. **Grounding vocabulary.** The checker only knows listed skills, degrees and patterns, so a niche skill or a vague claim like "expert in cloud" can pass.
3. **Availability attacks.** I03 and I06 made the agent give up on a fake requirement instead of applying and flagging the attack — no harmful write, but a fake requirement can still block an application.
4. **Real mode.** Form pages run their own JavaScript, and URL jobs have no trusted contact record.
5. **Human rubber-stamping.** Users may click through, so layer 3 (policies in code) must stay strong.
6. **Known gaps.** SSRF in `read_job_url` (no IP-range check yet), edited letters skip `leaks_private`, sandbox HTML fields are not escaped, real-mode JS can read typed values.