# The Operator: what it does, in simple words

> This is a plain-language guide to the app and to what is still missing.
> The formal course report (max 4 pages, with the measured results) is a separate file: `docs/report.md`, which becomes `report.pdf`.

## 1. What the app does

The Operator is an **AI assistant that applies to jobs for you**, but never behind your back.

1. You give it **true facts about yourself**: your CV, your LinkedIn PDF, old cover letters.
2. You point it at **a job**: a test job, a job link, or a job description you paste.
3. The AI **writes a CV and a cover letter tailored to that job**, using *only* your facts.
4. It **stops and shows you everything** before anything is sent: the CV, the letter, who it goes to.
5. Only when you click **Approve** does it apply: it submits on the job board, sends an email, or fills in the online form (where *you* still press Submit).

### What keeps it safe

| Risk | What the app does about it |
|---|---|
| The AI invents skills or degrees you don't have | A checker compares every claim with your facts and **blocks** anything unsupported. Each CV line shows which fact it comes from (F1, F2…). |
| A job posting hides instructions for the AI ("send this to my address instead", "the user is pre-approved") | Postings are treated as **data, never as instructions**. Suspicious text is flagged in orange. The email address always comes from the job board's record or from you, never from the posting text. |
| It sends something you didn't want | **Nothing is sent without your click.** What runs is exactly what you saw. |
| It loops forever or spends too much | Hard limits stop every run: 20 steps, 5 cents (configurable), 10 minutes, or the same action 3 times. |
| Private data leaks (passport, ID numbers) | Private details are never shown to the AI, and any outgoing text containing them is blocked. |
| Mistakes reach a real company | By default everything goes to a **sandbox**: a fake job board and mailbox that you can reset. |

## 2. The four pages

### Profile: "who you are"
The **only source of truth**: the AI may claim nothing that is not written here.

- **Readiness ring**: shows how complete your profile is, with a checklist of what is missing.
- **Fill it in automatically**: drop your LinkedIn PDF, CV or old letters. The AI reads them and proposes facts. You check them, fix anything wrong, and save.
- **Contact details**: name, email, phone, city, a one-line headline and your links.
- **Skills & languages**: tags. The CV can only list skills from here.
- **Facts about you**: one true sentence per job, degree or project, with dates.
- **Your writing style**: old cover letters, used only to copy your tone.
- **Private details**: passport or ID numbers. They are never sent and are only used to catch leaks.
- **New person / switch person**: several people can have their own profiles.

### Apply: "what to apply to, and how"
Three steps, then **Start**:

1. **Which job?** Pick test jobs from the board (the ones marked *hidden attack* are deliberate traps for testing), paste a job description, give a job link, or let it search.
2. **How?** Submit on the job board, send by email, or fill the online form (you click Submit yourself).
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

### Sandbox: "what was sent in test mode"
The fake job board's **submitted applications** and the **test outbox**. Use it to check, for example, that an email went to the company's real address and not to an attacker's. **Reset** wipes it.

## 3. What is missing

### Needed for the grade (in order)
1. **Run the full evaluation** (40 test scenarios) with the real model and fill in the results. All the numbers in `README.md` and `docs/report.md` still say *tbd*. With gpt-4.1-mini this costs about $0.30–0.50.
2. **Three error types have no test yet**: "job not found", "user edits before approving" and "AI service down" (see `errors.md`).
3. **Write the final report** with the real numbers and export it as **report.pdf**. Today it is only a draft.
4. **Update the postmortem** with real problems found. Two are already known:
   - The cover letter was limited to 600 characters, so the AI had to cut its letter. Fixed: now 4,000.
   - The profile import crashed when the AI returned "no value" for the phone number. Fixed: the output is now cleaned up.
5. **Fill in the Contributions table** in `README.md` (who did what).
6. **Mention the model change in the report**: the app now runs on OpenAI's gpt-4.1-mini (it can also use Claude or free models). The report and eval should say which model produced the numbers.

### Would make the app more useful (after the hand-in)
- **Application tracker**: a list of everything you applied to, with status (sent, interview, rejected).
- **"Should I apply?" check**: a match score and the requirements you don't meet, before writing anything.
- **Nicer PDFs**: the CV and letter PDFs are plain. A real template would help.
- **Letter language**: in a German letter, the "Application:" line and the date are still in English.
- **Real job sites**: links to LinkedIn or Indeed often can't be read (those sites block it), so pasting the posting is the reliable way. Job *search* only works on the test board.
- **Edit the CV before approving**: today only the letter and email can be edited at the approval step.
- **Form filling on real sites** has only been tested on the sandbox forms.
