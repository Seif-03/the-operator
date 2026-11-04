# Error taxonomy

Every failed tool call is classified (`error_class` in the trajectory log) by `agent/loop.py::_classify`.
Errors return to the model as `{"error": ..., "hint": ...}`, readable text with a next step, never a stack trace.

| # | Class | What goes wrong | What the agent / code does | Test (unit) | Eval scenario |
|---|---|---|---|---|---|
| 1 | `tool_down` | Board / mail server returns 5xx or is unreachable | Reads: one automatic retry in code. Writes: **never** auto-retried (the human approved one attempt); the model may call again, and idempotency makes that safe. After 2 failures: finish `blocked` | `test_tool_down_is_retried_then_reported`, `test_writes_are_never_auto_retried` | F01, F02, F03, F05, F06 |
| 2 | `timeout` | Tool takes longer than `TOOL_TIMEOUT_S` (2 s) | Same as tool_down (marked retryable) | `test_timeout_is_classified` | F04 |
| 3 | `bad_arguments` | Model passes args that break the strict schema (wrong id format, extra field like `to`) | Pydantic rejects before anything runs; message lists each bad field | `test_bad_arguments_are_explained`, `test_email_tool_has_no_recipient_argument` | all (precision metric) |
| 4 | `wrong_tool` | Model calls a tool that does not exist | Error lists available tools | `test_unknown_tool` | all (precision metric) |
| 5 | `empty_result` | Search finds nothing | Not an error: result says "try one broader query or finish `no_suitable_job`" | `test_search_actually_filters` | E01, F08 |
| 6 | `not_found` | Job id does not exist | Error + hint to use `search_jobs` | — | F07 |
| 7 | `wrong_order` | Write before its prerequisites (submit before `save_documents`, act on a job not read) | Precheck refuses **before** the checkpoint, so the human is never asked to approve something that would fail | `test_submit_without_documents_is_refused` | all (precision metric) |
| 8 | `ungrounded_claim` | Draft CV/letter/email/form answer claims a skill, degree, institution, year count or language not in the profile | `save_documents` refuses, listing each claim. The model must remove it or `ask_user` | `test_fabricated_claims_cannot_be_saved` | P01–P03, M01, I03, I07 |
| 9 | `policy_block` | Write targets a job the user did not ask for, a non-record recipient, or contains private data | Refused in code, whatever the model "believes" | `test_job_not_requested_by_user_is_blocked`, `test_private_data_never_leaves` | I01, I06, I09, I10 |
| 10 | `budget` | More applications than the run allows | Refused; hint says finish | `test_budget_blocks_second_job` | B01, I02, I10 |
| 11 | loop | Model repeats the same call or never finishes | Stop rule: identical call > 3×, 20 tool calls, $0.50, 250k tokens, 10 min, or 2 turns without a tool call → run `stopped` with a reason | `test_stop_rule_*`, `test_model_that_never_calls_tools_stops` | all (`stop_rule_held` check) |
| 12 | `user_rejected` | Human says no at the checkpoint, maybe with a new instruction | Tool result carries the reason; model must adjust or finish `user_declined`, not repeat unchanged | `test_reject_means_no_write` | U01, U02, U04 |
| 13 | user changes mind | Human edits the letter/email before approving | Edited text replaces the draft; PDFs re-rendered; grounding re-run as a warning (user's own words) | — | U03 |
| 14 | missing info | Job needs something the profile does not show | Model calls `ask_user`; a "yes" can add a `user_confirmed` fact that can then be cited | `test_ask_user_adds_confirmed_fact` | M01, M02 |
| 15 | model API failure | Anthropic API errors / rate limits | 4 attempts with backoff in `llm.py`, then the run ends with status `error` and the reason | — | — |

## Recovery-after-failure

Defined as: among scenarios with an injected environment fault that **can** be recovered from (F01, F03, F04, F05, F08), the share that still finished the task correctly. F02, F06 and F07 are unrecoverable by design; success there means finishing `blocked` cleanly with no write. Results: `eval/results/<model>/summary.json → recovery_after_failure`.
