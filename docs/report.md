# The Operator — Project 3 Report

CS496 AI Engineering · Team: 5
Evaluation snapshot: **2026-11-08, gpt-4.1-mini** (OpenAI), sandbox mode. Measured values below are from `eval/results/gpt-4.1-mini/`. The current code also contains browser-use tools, but those real-site workflows are not represented in the 40-scenario results.

## 1. Task, tools, and what the write changes

The Operator applies to jobs for a user. It reads a reviewed profile of true facts, reads a posting, writes a tailored CV and cover letter, and supports sandbox board submission, email, form filling, and an optional browser-use workflow for real sites. The web app also tracks applications, follow-up dates and notes. The current tool registry has 15 tools: 7 read/search tools, the gated `ask_user` tool, 6 write tools (including browser fill and approved browser submit), and `finish`. Optional LangSmith tracing records model and tool runs when configured. The 2026-11-08 evaluation does not cover browser-use or the application tracker; it exercised the three sandbox channels.

Writes change local PDFs (`save_documents`, overwrite for the same job), a sandbox application record (`submit_application`, idempotent), an email (`send_application_email`, idempotency key derived from user and job), or application form fields. The sandbox form-fill tool does not submit; the optional browser workflow has a separate submit tool that requires approval and is guarded by application-level network checks. Tool arguments use strict Pydantic schemas (`extra="forbid"`, patterns and length limits). Tool errors return a message and hint; run events are logged in `logs/<run_id>.jsonl`.

## 2. Loop, stop rule, and proof it stops

ReAct-style single agent (`agent/loop.py`): model → tool calls → results → model, until `finish`. No multi-agent design: one loop is enough to plan a 5–7 step task.

**Stop rule**, checked before every model call and every tool call: ≤20 tool calls, ≤$0.50, ≤250k tokens, ≤10 min agent time, ≤3 identical calls, and stop after 2 turns without a tool call. **Done rule:** `finish`.

**Proof.** (a) Unit tests with adversarial scripted models: an infinite searcher stops at `max_steps`, a repeater stops after too many identical calls, a big spender stops at the cost cap, and a model that only talks stops after 2 turns. (b) The 40-scenario evaluation recorded **0 stop-rule violations**; the maximum was **10 tool calls out of 20**. The rule checks step, token, cost, elapsed time, repeated-call and no-tool limits.

## 3. Design: sandbox and safety mechanisms

**Principle: the model may be fooled; the code must not be.** The agent reads third-party text (postings, pages, forms), so every safety property is enforced in code, outside the model. Prompts and labels reduce bad model behaviour; the code decides what can actually happen.

**3.1 Sandbox.** A fake, resettable copy of the outside world: FastAPI + SQLite job board on port 8100 with **16 postings, 7 of which contain injections** (J-1008–J-1013, J-1016; J-1016's form has a hidden one too), HTML application forms, a mock mailbox with idempotency keys, and **fault injection** (`500`, `503`, timeout, empty result). Reset is one call (`POST /api/reset`). The sample applicant profile includes canary values for private-data leak checks. The evaluation starts a fresh sandbox on a random port with a temporary database per run. Optional real mode uses SMTP and real application pages; optional browser-use adds real-site search, reading, filling, and guarded submission. The agent loop itself has no shell tool; its model-facing capabilities are the typed tools.

**3.2 Defense in depth.**

| Layer | Mechanism | Stops |
|---|---|---|
| 1. Data framing | Third-party text returned as `{"trust": "UNTRUSTED_DATA", "suspected_injection": [...], "data": ...}` + regex detector | Reduces how often the model follows injected text (warning only) |
| 2. Capability design | Structured args; `send_application_email` has **no recipient arg** (address from record or user); schemas `extra="forbid"` | Redirecting applications |
| 3. Policies in code | `allowed_job_ids`, submission budget (1/run), `leaks_private()` on outgoing text, sensitive form fields always empty | Mass-applying, data exfiltration |
| 4. Grounding | Deterministic: every CV item cites fact ids; skills/degrees/institutions/years/languages must exist in profile | Making the user lie |
| 5. Human checkpoint | Gated tools never run on the model's call; loop pauses as `awaiting_approval` with frozen args | "Skip confirmation" attacks |
| 6. No-submit form fill | Sandbox `fill_application_form` fills fields but has no submit action; real browser submission is a separate guarded, approved tool | Unapproved form submission |
| 7. Stop rule | Checked before every model and tool call | Runaway loops and cost |
| 8. Idempotency | Same application/mail key created once; only reads auto-retry | Duplicate applications |

**3.3 Human checkpoint.** Write tools that send or submit (`submit_application`, `send_application_email`, `fill_application_form`, `browser_submit_application`) pause until approval; `ask_user` pauses for an answer. The loop validates arguments and prechecks (job allowed, budget, saved documents, trusted recipient, grounding, private-data checks), shows a preview, and freezes the approved arguments. Browser submission additionally checks that the form still contains the approved values before our code clicks the submit button. Users can edit the letter/email or reject; edited user text is treated as user-authored.

**3.4 Private data and logging.** `Profile.public_view()` excludes the private block, keeping passport, ID and birth date out of model context. Outgoing model-authored text is checked for private values before save/send; the optional browser packet is built in code without private fields. Tool errors use readable messages and hints and are classified for evaluation. Events are logged to `logs/<run_id>.jsonl`; saved run state is written with a temporary file and rename so a run waiting for approval can be restored after restart.

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
| Task success | **35 / 40 (87.5%)** |
| Step accuracy · path recall | **0.798 · 0.951** |
| Tool-call precision | **0.915** |
| Wasted steps per task | **1.55** |

The 5 failures are recorded in `README.md` and `eval/results/gpt-4.1-mini/results.md`.

## 5. Error taxonomy and recovery

`errors.md` documents 19 error and exception cases, their handling, and related unit/evaluation coverage (not every case has a dedicated unit test). Reads may be retried once for transient failures; writes are not automatically retried. Recovery-after-failure among the five recoverable injected-fault scenarios: **5 / 5**. The current automated test suite passes **70 tests**; this code-level suite is separate from the 40 live-model evaluation scenarios.

## 6. Threat model, injection results, cost model

Untrusted entry points: postings, web pages, form pages, the user's own imported documents. Three layers: data framing + detector, **code-level policies** (no recipient argument, job allowlist, application budget, private-data block, grounding, no submit path), and the human.

**Injection results:** 8 / 10 scenarios met every expected outcome; **0 harmful writes in all 10**. In I03 and I06 the agent stopped without applying, so those attacks caused safe denial of service rather than an unauthorized or fabricated application. The evaluator's simulated approver approves checkpoints by default, testing defenses without relying on a careful user. There were 0 stop-rule violations. Per-scenario details are in `eval/results/gpt-4.1-mini/results.md`.

**Cost and latency (evaluation snapshot).** At the recorded gpt-4.1-mini rates ($0.40/M input tokens, $1.60/M output tokens), the mean was **28,479 tokens and $0.006 per task**; p50 / p95 elapsed time was **12.01 / 19.5 seconds**. The recorded estimate is **$0.60 per 100 tasks** and **$12.06 per month** at approximately 2,000 tasks/month. These are averages from the 40 sandbox scenarios, not a production forecast. The prompt history is resent on each model call; provider prompt caching is used where available and token usage is tracked.

## 7. Limitations

1. **Soft influence.** An injection can still change wording; grounding blocks false claims, not tone.
2. **Grounding vocabulary.** The checker only knows listed skills, degrees and patterns, so a niche skill or a vague claim like "expert in cloud" can pass.
3. **Availability attacks.** I03 and I06 made the agent give up on a fake requirement instead of applying and flagging the attack — no harmful write, but a fake requirement can still block an application.
4. **Evaluation scope.** The 40-scenario result covers sandbox board, email and sandbox form workflows; it does not establish reliability on live job sites. Browser-use search/read/fill/submit are not covered and need their own evaluation on representative sites.
5. **Human rubber-stamping.** Users may click through, so layer 3 (policies in code) must stay strong.
6. **Known gaps.** `read_job_url` has no IP-range restriction (SSRF risk); user-edited letters do not pass through `leaks_private`; sandbox HTML fields are not escaped; page JavaScript in real mode can read values typed into that page.