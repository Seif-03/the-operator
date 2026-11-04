# Sandbox

A fake, resettable stand-in for job portals and email. All sandbox-mode writes land in `sandbox/data/sandbox.db` (SQLite).

| | |
|---|---|
| Start | `python run.py` (starts it on port 8100), or `uvicorn sandbox.jobboard:app --port 8100` |
| Reset | `curl -X POST localhost:8100/api/reset`, or the **Reset sandbox** button in the UI. Wipes applications and mail, reseeds jobs |
| Inspect | `GET /api/applications`, `GET /api/mail`, or the UI's Sandbox tab |
| Inject faults | `POST /api/faults {"target": "search\|get_job\|apply\|mail\|form", "mode": "error500\|timeout\|unavailable\|empty", "count": N}` |
| Pages | `/` job list, `/jobs/{id}` posting, `/apply/{id}` application form (for form-fill mode) |

Data: `seed_jobs.json` holds 16 postings. J-1008 to J-1013 and J-1016 contain prompt-injection attacks; the J-1016 form has a hidden one too.
`profiles/lina.json` is a fictional test applicant with fake private fields, used to detect leaks.

The eval and the tests start their own sandbox on a random port with a temporary database, so they never touch this one.
