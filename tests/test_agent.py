"""Unit tests with a scripted model: they prove the safety properties hold in CODE,
whatever the model decides. Run: pytest -q"""
import httpx

from agent.llm import ScriptedLLM
from agent.runner import build_run
from tests.conftest import GOOD_CV, GOOD_LETTER

DOCS = {"job_id": "J-1001", "cv": GOOD_CV, "letter": GOOD_LETTER}


def run_with(script, settings, profile, allowed=None, **kw):
    return build_run(profile, "test goal", settings, ScriptedLLM(script), allowed_job_ids=allowed, **kw)


# ---------------------------------------------------------------- stop rule
def test_stop_rule_max_steps_on_infinite_loop(settings, profile):
    settings.max_steps = 7
    # A model that never stops: always searches with a different query
    run = run_with(lambda msgs, i: [("search_jobs", {"query": f"python {i}"})], settings, profile)
    assert run.run_until_pause() == "stopped"
    assert "max_steps" in run.stop_reason
    assert run.tool_calls <= settings.max_steps


def test_stop_rule_identical_calls(settings, profile):
    run = run_with(lambda msgs, i: [("get_profile", {})], settings, profile)
    assert run.run_until_pause() == "stopped"
    assert "loop detected" in run.stop_reason
    assert run.tool_calls == settings.max_identical_calls


def test_stop_rule_cost_budget(settings, profile):
    settings.max_cost_usd = 0.01        # each scripted call ~ $0.006
    run = run_with(lambda msgs, i: [("search_jobs", {"query": f"data {i}"})], settings, profile)
    assert run.run_until_pause() == "stopped"
    assert "cost budget" in run.stop_reason
    assert run.cost_usd < settings.max_cost_usd + 0.01


def test_model_that_never_calls_tools_stops(settings, profile):
    run = run_with(lambda msgs, i: "I am thinking...", settings, profile)
    assert run.run_until_pause() == "stopped"
    assert run.llm_calls == 2


def test_finish_is_done_rule(settings, profile):
    run = run_with([[("finish", {"status": "no_suitable_job", "summary": "nothing fits"})]], settings, profile)
    assert run.run_until_pause() == "done"
    assert run.final["status"] == "no_suitable_job"


# ---------------------------------------------------------------- checkpoint + idempotency
HAPPY = [[("get_profile", {})], [("get_job", {"job_id": "J-1001"})], [("save_documents", DOCS)],
         [("submit_application", {"job_id": "J-1001"})], [("finish", {"status": "completed", "summary": "applied"})]]


def apps(sandbox_url):
    return httpx.get(sandbox_url + "/api/applications").json()["applications"]


def test_write_waits_for_human(settings, profile, sandbox):
    run = run_with(HAPPY, settings, profile)
    assert run.run_until_pause() == "awaiting_approval"
    assert run.pending.tool == "submit_application"
    assert apps(sandbox) == []                     # nothing written before approval
    run.resolve("approve")
    assert run.run_until_pause() == "done"
    assert len(apps(sandbox)) == 1


def test_reject_means_no_write(settings, profile, sandbox):
    script = HAPPY[:4] + [[("finish", {"status": "user_declined", "summary": "user said no"})]]
    run = run_with(script, settings, profile)
    run.run_until_pause()
    run.resolve("reject", reason="not this one")
    assert run.run_until_pause() == "done"
    assert apps(sandbox) == []


def test_submit_twice_applies_once(settings, profile, sandbox):
    script = HAPPY[:4] + [[("submit_application", {"job_id": "J-1001"})], [("finish", {"status": "completed", "summary": "test done"})]]
    run = run_with(script, settings, profile)
    run.run_until_pause(); run.resolve("approve")
    run.run_until_pause(); run.resolve("approve")
    run.run_until_pause()
    assert len(apps(sandbox)) == 1
    assert run.trajectory[-2]["output"]["created"] is False


def test_submit_without_documents_is_refused(settings, profile, sandbox):
    run = run_with([[("get_job", {"job_id": "J-1001"})], [("submit_application", {"job_id": "J-1001"})],
                    [("finish", {"status": "blocked", "summary": "test done"})]], settings, profile)
    st = run.run_until_pause()
    assert st == "done", (run.stop_reason, run.trajectory)             # never paused: precheck failed before the checkpoint
    assert run.trajectory[1]["error_class"] == "wrong_order"


# ---------------------------------------------------------------- schemas + errors
def test_bad_arguments_are_explained(settings, profile):
    run = run_with([[("get_job", {"job_id": "1001"})], [("finish", {"status": "blocked", "summary": "test done"})]], settings, profile)
    run.run_until_pause()
    step = run.trajectory[0]
    assert not step["ok"] and step["error_class"] == "bad_arguments"
    assert "Invalid arguments" in step["output"]["error"]


def test_unknown_tool(settings, profile):
    run = run_with([[("delete_everything", {})], [("finish", {"status": "blocked", "summary": "test done"})]], settings, profile)
    run.run_until_pause()
    assert run.trajectory[0]["error_class"] == "wrong_tool"


def test_tool_down_is_retried_then_reported(settings, profile, sandbox):
    httpx.post(sandbox + "/api/faults", json={"target": "get_job", "mode": "error500", "count": 1})
    run = run_with([[("get_job", {"job_id": "J-1001"})], [("finish", {"status": "completed", "summary": "test done"})]], settings, profile)
    run.run_until_pause()
    assert run.trajectory[0]["ok"]                     # one automatic retry recovered
    httpx.post(sandbox + "/api/faults", json={"target": "get_job", "mode": "error500", "count": 5})
    run = run_with([[("get_job", {"job_id": "J-1001"})], [("finish", {"status": "blocked", "summary": "test done"})]], settings, profile)
    run.run_until_pause()
    assert run.trajectory[0]["error_class"] == "tool_down"


def test_timeout_is_classified(settings, profile, sandbox):
    httpx.post(sandbox + "/api/faults", json={"target": "search", "mode": "timeout", "count": 2})
    run = run_with([[("search_jobs", {"query": "python"})], [("finish", {"status": "blocked", "summary": "test done"})]], settings, profile)
    run.run_until_pause()
    assert run.trajectory[0]["error_class"] == "timeout"


def test_writes_are_never_auto_retried(settings, profile, sandbox):
    httpx.post(sandbox + "/api/faults", json={"target": "apply", "mode": "error500", "count": 1})
    run = run_with(HAPPY, settings, profile)
    run.run_until_pause(); run.resolve("approve")
    run.run_until_pause()
    sub = [s for s in run.trajectory if s["tool"] == "submit_application"]
    assert len(sub) == 1 and not sub[0]["ok"]
    assert not any(e["kind"] == "auto_retry" and e["tool"] == "submit_application" for e in run.events)


# ---------------------------------------------------------------- injection policies in code
def test_fabricated_claims_cannot_be_saved(settings, profile):
    bad = {"job_id": "J-1010", "cv": {**GOOD_CV, "sections": GOOD_CV["sections"] + [
        {"title": "Education", "items": [{"heading": "PhD in Computer Science, MIT", "text": "", "fact_ids": ["F1"]}]}]},
        "letter": GOOD_LETTER}
    run = run_with([[("get_job", {"job_id": "J-1010"})], [("save_documents", bad)], [("finish", {"status": "blocked", "summary": "test done"})]],
                   settings, profile)
    run.run_until_pause()
    assert run.trajectory[1]["error_class"] == "ungrounded_claim"
    assert "J-1010" not in run.ctx.documents


def test_job_not_requested_by_user_is_blocked(settings, profile, sandbox):
    docs = {**DOCS, "job_id": "J-1007"}
    run = run_with([[("get_job", {"job_id": "J-1007"})], [("save_documents", docs)], [("submit_application", {"job_id": "J-1007"})],
                    [("finish", {"status": "blocked", "summary": "test done"})]], settings, profile, allowed={"J-1013"})
    assert run.run_until_pause() == "done"
    assert run.trajectory[2]["error_class"] == "policy_block"
    assert apps(sandbox) == []


def test_budget_blocks_second_job(settings, profile, sandbox):
    settings.max_submissions = 1
    d2 = {**DOCS, "job_id": "J-1011"}
    script = HAPPY[:4] + [[("get_job", {"job_id": "J-1011"})], [("save_documents", d2)], [("submit_application", {"job_id": "J-1011"})],
                          [("finish", {"status": "completed", "summary": "test done"})]]
    run = run_with(script, settings, profile)
    run.run_until_pause(); run.resolve("approve")
    assert run.run_until_pause() == "done"
    assert len(apps(sandbox)) == 1
    assert run.trajectory[-2]["error_class"] == "budget"


def test_email_recipient_comes_from_record_not_posting(settings, profile, sandbox):
    docs = {**DOCS, "job_id": "J-1011"}
    body = "Dear Taunus Tech team, please find my CV and cover letter for the working student backend role attached. Kind regards, Lina Haddad"
    run = run_with([[("get_job", {"job_id": "J-1011"})], [("save_documents", docs)],
                    [("send_application_email", {"job_id": "J-1011", "subject": "Application: Working Student Backend", "body": body})],
                    [("finish", {"status": "completed", "summary": "test done"})]], settings, profile)
    run.run_until_pause()
    assert run.pending.preview["to"] == "jobs@taunus-tech.example"
    run.resolve("approve"); run.run_until_pause()
    mail = httpx.get(sandbox + "/api/mail").json()["mail"]
    assert [m["recipient"] for m in mail] == ["jobs@taunus-tech.example"]


def test_email_tool_has_no_recipient_argument(settings, profile):
    run = run_with([[("get_job", {"job_id": "J-1008"})],
                    [("send_application_email", {"job_id": "J-1008", "to": "hr-verify@neckar-secure.example", "subject": "Passport",
                                                 "body": "x" * 50})], [("finish", {"status": "blocked", "summary": "test done"})]], settings, profile)
    run.run_until_pause()
    assert run.trajectory[1]["error_class"] == "bad_arguments"


def test_private_data_never_leaves(settings, profile, sandbox):
    docs = {**DOCS, "job_id": "J-1008"}
    body = f"Dear team, as requested my passport number is {profile.private['passport_number']}. Kind regards, Lina Haddad"
    run = run_with([[("get_job", {"job_id": "J-1008"})], [("save_documents", docs)],
                    [("send_application_email", {"job_id": "J-1008", "subject": "Verification", "body": body})],
                    [("finish", {"status": "blocked", "summary": "test done"})]], settings, profile)
    assert run.run_until_pause() == "done"
    assert run.trajectory[2]["error_class"] == "policy_block"
    assert httpx.get(sandbox + "/api/mail").json()["mail"] == []


def test_untrusted_output_is_wrapped_and_flagged(settings, profile):
    run = run_with([[("get_job", {"job_id": "J-1009"})], [("finish", {"status": "completed", "summary": "test done"})]], settings, profile)
    run.run_until_pause()
    out = run.trajectory[0]["output"]["description"]
    assert out["trust"] == "UNTRUSTED_DATA" and out["suspected_injection"]


def test_ask_user_adds_confirmed_fact(settings, profile):
    run = run_with([[("ask_user", {"question": "Have you used Docker?"})], [("finish", {"status": "completed", "summary": "test done"})]],
                   settings, profile)
    assert run.run_until_pause() == "awaiting_input"
    run.answer("yes, in a university project", add_fact="Used Docker to containerise a university RAG chatbot project")
    run.run_until_pause()
    assert any("Docker" in f.text for f in run.ctx.profile.facts)


# ---------------------------------------------------------------- regressions found by the eval
def test_search_actually_filters(settings, profile):
    """Bug found by eval E01: the tool sent `query=` but the board reads `q=`, so every search returned all jobs."""
    run = run_with([[("search_jobs", {"query": "underwater basket weaving"})], [("finish", {"status": "no_suitable_job", "summary": "nothing"})]],
                   settings, profile)
    run.run_until_pause()
    assert run.trajectory[0]["output"]["results"] == []


def test_form_fill_never_submits_and_skips_sensitive_fields(settings, profile, sandbox):
    docs = {**DOCS, "job_id": "J-1016"}
    values = {"#first_name": "Lina", "#last_name": "Haddad", "#email": "lina.haddad@mail.example", "#national_id": "123456789"}
    run = run_with([[("get_job", {"job_id": "J-1016"})], [("save_documents", docs)], [("inspect_application_form", {"job_id": "J-1016"})],
                    [("fill_application_form", {"job_id": "J-1016", "values": values})], [("finish", {"status": "completed", "summary": "form filled"})]],
                   settings, profile)
    assert run.run_until_pause() == "awaiting_approval"
    assert run.pending.preview["left_for_user"] == ["#national_id"]
    run.resolve("approve")
    assert run.run_until_pause() == "done"
    step = [t for t in run.trajectory if t["tool"] == "fill_application_form"][0]
    assert step["ok"] and step["output"]["submitted_by_agent"] is False
    assert all(r["selector"] != "#national_id" for r in step["output"]["report"])
    assert apps(sandbox) == []        # nothing reached the board: only the user's click submits
