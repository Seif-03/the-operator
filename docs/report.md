# The Operator — Project 3 Report (draft)

CS496 AI Engineering · Team: _names_ · max 4 pages. Numbers marked _tbd_ come from `eval/results/<model>/`.

## 1. Task, tools, and what the write changes

The Operator applies to jobs for a user. It reads a reviewed profile of true facts, reads a posting, writes a tailored CV and cover letter, and applies through one of three channels. Twelve tools: 7 reads (`get_profile`, `search_jobs`, `get_job`, `read_job_url`, `check_documents`, `inspect_application_form`, `ask_user`), 4 writes (`save_documents`, `submit_application`, `send_application_email`, `fill_application_form`), and `finish`.

Writes change: local PDFs (`save_documents`, idempotent overwrite), an application record on the board (`submit_application`, unique on user+job), an email in the outbox (`send_application_email`, idempotency key = hash(user, job)), and the field values of an application form in a browser (`fill_application_form`, never submits). All tools have strict Pydantic schemas (`extra="forbid"`, id patterns, length limits). Errors return as text with a hint. Every call is logged with input, output and time (`logs/<run>.jsonl`).

## 2. Loop, stop rule, and proof it stops

ReAct-style single agent (`agent/loop.py`): model → tool calls → results → model, until `finish`. No multi-agent design: one loop is enough to plan a 5–7 step task.

**Stop rule**, checked before every model call and every tool call: ≤20 tool calls, ≤$0.50, ≤250k tokens, ≤10 min agent time, ≤3 identical calls, and stop after 2 turns without a tool call. **Done rule:** `finish`.
**Proof:** (a) unit tests with adversarial scripted models: an infinite searcher stops at exactly `max_steps`, a repeater stops at 3 identical calls, a big spender stops at the cost cap, a model that only talks stops after 2 turns; (b) eval check `stop_rule_held` on all 40 scenarios: _tbd_ violations, maximum tool calls seen _tbd_ / 20. Each iteration increases the step, token or no-tool counter, and every counter has a cap, so the loop terminates.

## 3. Sandbox and human checkpoint

Sandbox: FastAPI + SQLite job board with 16 postings (7 contain attacks), HTML application forms, a mock mailbox, and fault injection (500, 503, timeout, empty) per endpoint. Reset is one call (`POST /api/reset`). The eval starts a fresh sandbox per run and resets it per scenario. Real mode swaps only the email transport (SMTP) and the form target (real pages).

Checkpoint: gated tools are never executed on the model's call. The loop validates the arguments, runs the prechecks, builds a preview (job, recipient, CV with fact citations, letter, grounding result, injection warnings), and pauses. The user can approve, edit then approve (edits re-render the PDFs), or reject with a reason that goes back to the model. Only the shown arguments run.

## 4. Trajectory eval

40 scenarios (`eval/scenarios.json`): 10 happy path across 3 channels, 3 poor fit, 2 missing info, 1 empty result, 8 tool failure/bad input, 4 user changes mind, 2 budget/idempotency, 10 injection. Each has an expected tool path and outcome checks on the sandbox state (applications, mail recipients, form fields), on the text that left the system (no fabricated claims, no private data, language), and on the trajectory (checkpoint before every write, stop rule). The simulated human **approves everything** unless the scenario says otherwise, so safety cannot depend on a careful human.

Metrics: step accuracy = LCS(actual, expected)/|actual|; path recall = LCS/|expected|; wasted steps = |actual| − LCS; tool-call precision = 1 − (model-caused failed calls / all calls).

| Metric | Value |
|---|---|
| Task success | _tbd_ /40 |
| Step accuracy · path recall | _tbd_ · _tbd_ |
| Tool-call precision | _tbd_ |
| Wasted steps per task | _tbd_ |

## 5. Error taxonomy and recovery

15 classes (see `errors.md`), each with a handling rule and a test. Reads auto-retry once; writes never auto-retry. Recovery-after-failure (recoverable fault scenarios that still completed): _tbd_.

## 6. Threat model, injection results, cost model

Untrusted entry points: postings, web pages, form pages, the user's own imported documents. Three layers: data framing + detector, **code-level policies** (no recipient argument, job allowlist, application budget, private-data block, grounding, no submit path), and the human. Injection results: _tbd_ /10 defended; see the table in `eval/results/<model>/results.md` for which attacks the model attempted and code blocked.

**Cost model.** cost/task = tokens_in × p_in + tokens_out × p_out. Measured: _tbd_ tokens and $_tbd_ per task, p50/p95 _tbd_ s. At 100× (100 users × 5 applications/week ≈ 2,000 tasks/month): $_tbd_/month. Main driver: input tokens grow with each step because the full history is re-sent. The next saving would be prompt caching of the system prompt and tool schemas.
