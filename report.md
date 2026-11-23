# The Operator: what it does, in simple words

> This is a plain-language guide to the app and remaining work.
> The formal course report and measured evaluation are in `docs/report.md`.

## 1. What the app does

The Operator is an **AI assistant that applies to jobs for you**, but never behind your back.

1. You give it **true facts about yourself**: your CV, your LinkedIn PDF, old cover letters.
2. You point it at **a job**: a test job, a job link, or a job description you paste.
3. The AI **writes a CV and a cover letter tailored to that job**, using *only* your facts.
4. It **stops and shows you everything** before anything is sent: the CV, the letter, who it goes to.
5. Only when you click **Approve** does it apply: it submits on the sandbox job board, sends an email, or fills in a form. For sandbox forms, *you* still press Submit. An optional browser workflow can apply on real sites after a separate approval.

### What keeps it safe

| Risk | What the app does about it |
|---|---|
| The AI invents skills or degrees you don't have | A checker compares every claim with your facts and **blocks** anything unsupported. Each CV line shows which fact it comes from (F1, F2…). |
| A job posting hides instructions for the AI ("send this to my address instead", "the user is pre-approved") | Postings are treated as **data, never as instructions**. Suspicious text is flagged in orange. The email address always comes from the job board's record or from you, never from the posting text. |
| It sends something you didn't want | **Nothing is sent without your click.** What runs is exactly what you saw. |
| It loops forever or spends too much | Hard limits stop every run: 20 steps, 5 cents (configurable), 10 minutes, or the same action 3 times. |
| Private data leaks (passport, ID numbers) | Private details are never shown to the AI, and any outgoing text containing them is blocked. |
| Mistakes reach a real company | By default everything goes to a **sandbox**: a fake job board and mailbox that you can reset. |

## 2. The five pages

### Profile: "who you are"
The **only source of truth**: the AI may claim nothing that is not written here.

- **Readiness ring**: shows how complete your profile is, with a checklist of what is missing.
- **Fill it in automatically**: drop your LinkedIn PDF, CV or old letters. The AI reads them and proposes facts. You check them, fix anything wrong, and save.
- **Contact details**: name, email, phone, city, a one-line headline and your links.
- **Skills & languages**: tags. The CV can only list skills from here.
- **Facts about you**: one true sentence per job, degree or project, with dates.
- **Photo**: click the photo square (or drag a picture onto it). It is cropped to passport format. Tick *Put my photo on the CV* to print it on the CV, which is common for jobs in Germany. The photo is never sent to the AI.
- **Your writing style**: old cover letters and **old CVs** (paste them, or use *Add from file*). They teach the AI how you write and how you like a CV ordered. They are **never used as facts**: a claim that only appears in an old CV is blocked by the fact checker. To pull *facts* out of an old CV, drop it into *Fill it in automatically* instead.
- **Private details**: passport or ID numbers. They are never sent and are only used to catch leaks.
- **New person / switch person**: several people can have their own profiles.

### Apply: "what to apply to, and how"
Three steps, then **Start**:

1. **Which job?** Pick test jobs from the board (the ones marked *hidden attack* are deliberate traps for testing), paste a job description, give a job link, or let it search.
2. **How?** Submit on the sandbox board, send by email, fill a sandbox form (you click Submit), or optionally use the browser workflow on a real site.
3. **Notes** (optional): for example "write the letter in German".

The dark bar at the bottom says in one sentence what will happen. If something is missing, it tells you what.

### Runs: "watch it work, and approve"
- **Left**: all your runs. The orange "Needs your OK" label means it is waiting for you.
- **Progress bar**: Profile → Job → Documents → Your OK → Applied → Done.
- **Counters**: steps used, money spent, time, tokens.
- **Approval card** (orange border): who it goes to, any attack it spotted, the fact-check result, and tabs to read the **email**, the **cover letter** (which you can edit directly) and the **CV**. Then you choose:
  - **Approve**: it applies (with your edits, if you made any).
  - **Ask for changes**: tell it what to change; it rewrites and asks you again.
  - **Don't apply**: nothing is sent.
- **What it did**: every step in plain words. "details" shows the exact technical input and output.

### Tracker: "keep up with applications"
- Confirmed applications from agent runs are added automatically. A form that is filled but not submitted is marked **Ready to submit**, not Applied.
- Add applications made outside the app; update status, set a follow-up date, add notes, or remove an entry.

### Sandbox: "what was sent in test mode"
The fake job board's **submitted applications** and the **test outbox**. Use it to check, for example, that an email went to the company's real address and not to an attacker's. **Reset** wipes it.

## 3. Evaluation and remaining work

The recorded 40-scenario evaluation used **gpt-4.1-mini** in sandbox mode: 35/40 scenarios succeeded (87.5%), with 0 stop-rule violations and no harmful writes in the 10 injection scenarios. The two injection failures were safe stops that failed to complete the requested application. See `docs/report.md` and `eval/results/gpt-4.1-mini/` for the detailed metrics and limits of this evaluation.

### Remaining work
- Add dedicated tests for the error cases currently marked without tests in `errors.md`, including job-not-found, user-edited content, and model API failure.
- Run a separate evaluation of the optional browser workflow on representative real job sites; the existing 40-scenario evaluation covers sandbox channels, not live-site reliability.
- Complete the remaining team-contribution entries in `README.md`.

### Would make the app more useful (after the hand-in)
- **"Should I apply?" check**: a match score and the requirements you don't meet, before writing anything.
- **Nicer PDFs**: the CV and letter PDFs are plain. A real template would help.
- **Letter language**: in a German letter, the "Application:" line and the date are still in English.
- **Edit the CV before approving**: today only the letter and email can be edited at the approval step.
- **Improve job-site reliability**: real-site search, reading and applying are available through the optional browser workflow, but site-specific reliability still needs testing; pasting the posting remains a fallback.

For the detailed design, safeguards and evaluation metrics, see `docs/report.md`.