# Postmortem

What went wrong while building The Operator, and what we learned. Problems found so far during the build are below. Add the ones from the real-model eval and the demo.

## 1. Every search returned every job (found by the eval)

**What happened.** The `search_jobs` tool sent its arguments with `params=a.model_dump()`, so the HTTP query string said `query=...`. The board reads `q=...`. The board ignored the unknown parameter and returned all jobs, so no search was ever filtered.
**Why we didn't notice.** Unit tests checked that search *returned* results, not that they matched. Happy-path search scenarios (H07) still passed: the agent picked a good job from the full list.
**How it was found.** E01 ("underwater basket weaving") expected `no_suitable_job` and got an application instead.
**Fix.** Map arguments explicitly. Added `test_search_actually_filters`.
**Lesson.** Interfaces between our own components need contract tests too. A negative scenario (expect *nothing*) caught what positive ones could not.

## 2. Schema strictness blocked the agent's own `finish`

**What happened.** `finish.summary` has `min_length=5`. The scripted tests used `"x"`, so `finish` failed validation, the model "never finished", and the run was stopped by the no-tool-call rule. The test failure message pointed at the wrong cause (stop rule) at first.
**Lesson.** Strict schemas are right, but a failure in the *done* tool is costly. Its error must be very clear, and the stop reason must show the last error. We now log `error_class` on every failed call.

## 3. The grounding check punished honesty

**What happened.** The first version flagged any sentence naming a skill missing from the profile, including "I have not yet used Airflow, but I am eager to learn it." That pushes the model to *hide* gaps, the opposite of what we want.
**Fix.** Sentences with learning/negation cues are exempt from skill checks (`LEARNING_CUES`).
**Trade-off.** An attacker could phrase a claim as learning ("eager to learn Kubernetes, which I used for 5 years"). The years-of-experience pattern is still checked in such sentences, and the human sees the letter. Listed as residual risk 2 in the threat model.

## 4. Short skill names matched normal words

**What happened.** "React", "Spring", "Express", "Agile" and "ARM" are also English words ("I react quickly"). Case-insensitive matching produced false errors.
**Fix.** These are matched case-sensitively in their proper spelling. **Still imperfect:** a sentence starting with "React" is ambiguous.

## 5. Tool schemas with `$ref`

**What happened.** Pydantic emits nested models as `$defs` + `$ref`. We inline them before sending tool schemas to the API, so nothing depends on how the API resolves references.
**Lesson.** Look at the exact schema the model receives, not the Python class.

## 6. Design decision we reversed: auto-retrying writes

Our first plan retried all tool failures automatically. For writes, the human approved **one** action, so silently re-sending is wrong even when idempotency makes it harmless. Now only reads auto-retry. A write retry is a new model decision, visible in the trajectory.

## 7. Time spent waiting for the human counted toward the time budget

If the user went for coffee at the checkpoint, the run hit `max_wall_seconds` and stopped. The pause time is now excluded (`AgentRun.elapsed`).

## 8. The app crashed on Windows on the first page load

**What happened.** On a teammate's Windows machine, `python run.py` started, but opening the page crashed with `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d`. On Windows, Python reads files as cp1252 unless told otherwise. `index.html` contains UTF-8 characters (arrows, quotes), and we only ever tested on Linux, where UTF-8 is the default.
**Fix.** Every file read/write now passes `encoding="utf-8"`. The browser worker's stdout pipe is forced to UTF-8. `.env` is read as `utf-8-sig`, so a BOM added by Notepad doesn't break the key name.
**Lesson.** "Runs from a clean clone" means on every team member's OS. Test on Windows before the demo.

## To fill in after the real-model eval and the demo

- Which scenarios failed and why (wrong path? fabricated claim blocked? didn't adapt after rejection?)
- Did any injection succeed against the model alone (blocked only by code)?
- Real cost and latency vs. the estimates
- What broke in the live demo
