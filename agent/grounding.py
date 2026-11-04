"""Groundedness check: every claim in the tailored CV / letter must trace back to the profile.

Deterministic on purpose (no LLM judge): it is the safety net under the prompt.
Hard errors block saving/sending; warnings are shown to the user at the checkpoint.

What counts as a checkable claim:
  * skills / tools / technologies from a vocabulary (Kubernetes, AWS, PyTorch, ...)
  * degrees (PhD, Master, M.Sc., ...) and well-known institutions
  * years-of-experience claims ("5 years", "3+ years") and calendar years
  * spoken languages
  * fact ids: must exist; every CV item must cite at least one fact
Sentences that are explicitly about learning / not having something ("I have not yet
used Kubernetes", "eager to learn AWS") are allowed to name missing skills.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .profile import Profile

SKILL_VOCAB = [
    "python", "java", "javascript", "typescript", "c++", "c#", "rust", "golang", "kotlin", "swift", "scala", "ruby", "php",
    "matlab", "julia", "haskell", "perl", "bash", "sql", "nosql", "postgresql", "mysql", "sqlite", "mongodb", "redis",
    "cassandra", "elasticsearch", "neo4j", "snowflake", "bigquery", "databricks", "spark", "hadoop", "kafka", "airflow",
    "dbt", "pandas", "numpy", "scipy", "scikit-learn", "sklearn", "pytorch", "tensorflow", "keras", "jax", "xgboost",
    "hugging face", "transformers", "langchain", "llamaindex", "opencv", "spacy", "nltk", "fastapi", "flask", "django",
    "spring", "express", "node.js", "nodejs", "react", "angular", "vue", "svelte", "next.js", "html", "css", "tailwind",
    "graphql", "rest api", "grpc", "docker", "kubernetes", "k8s", "helm", "terraform", "ansible", "jenkins",
    "github actions", "gitlab ci", "aws", "azure", "gcp", "google cloud", "linux", "git", "jira", "figma", "tableau",
    "power bi", "excel", "sap", "salesforce", "unity", "unreal", "ros", "embedded c", "vhdl", "verilog", "arm",
    "oscilloscope", "latex", "capcut", "premiere", "after effects", "photoshop", "blender", "gtfs", "raptor",
    "machine learning", "deep learning", "nlp", "computer vision", "reinforcement learning", "statistics", "rag",
    "embeddings", "vector search", "llm", "mlops", "devops", "ci/cd", "scrum", "agile", "six sigma", "pmp",
]
DEGREE_PAT = re.compile(r"\b(ph\.?\s?d\.?|doctorate|doctoral|master(?:'s)?|m\.?\s?sc\.?|msc|m\.?\s?a\.?|mba|bachelor(?:'s)?|"
                        r"b\.?\s?sc\.?|bsc|diplom|abitur)\b", re.I)
INSTITUTION_PAT = re.compile(r"\b(MIT|Stanford|Harvard|Oxford|Cambridge|ETH Zurich|TU Munich|TUM|Caltech|Berkeley|"
                             r"Google|Amazon|Microsoft|Meta|Apple|OpenAI|Anthropic|Nvidia|SAP|Siemens|BMW|Bosch)\b")
YEARS_EXP_PAT = re.compile(r"\b(\d{1,2})\s*\+?\s*(?:years?|yrs?|jahre)\b", re.I)
YEAR_PAT = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
LANGUAGES = ["english", "german", "french", "arabic", "spanish", "italian", "portuguese", "dutch", "turkish", "russian",
             "chinese", "mandarin", "japanese", "korean", "hindi", "polish", "swedish", "greek", "hebrew", "persian"]
LEARNING_CUES = re.compile(r"\b(not yet|no (?:prior |professional )?experience|haven't|have not|eager to learn|keen to learn|"
                           r"would like to learn|want to learn|looking forward to learning|learn(?:ing)? more about|new to|"
                           r"curious about|excited to (?:learn|grow)|familiari[sz]e myself)\b", re.I)
# Words used in the vocabulary that are also ordinary English and need a stricter match
_AMBIGUOUS = {"spring", "express", "arm", "rag", "unity", "excel", "agile", "scrum", "react", "swift", "ruby", "go"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _term_re(term: str) -> re.Pattern:
    esc = re.escape(term)
    return re.compile(rf"(?<![\w+#.]){esc}(?![\w+#])", re.I if term not in _AMBIGUOUS else 0)


_TERM_RES = {t: (_term_re(t) if t not in _AMBIGUOUS else re.compile(rf"(?<![\w+#.]){re.escape(t.capitalize() if t not in ('rag', 'arm') else t.upper())}(?![\w+#])"))
             for t in SKILL_VOCAB}


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip()]


@dataclass
class GroundingReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


def _check_text(label: str, text: str, support: str, profile_skills_norm: str, langs_norm: str, rep: GroundingReport):
    sup = _norm(support)
    for sent in _sentences(text):
        learning = bool(LEARNING_CUES.search(sent))
        if not learning:
            for term, rx in _TERM_RES.items():
                if rx.search(sent) and term not in sup and term not in profile_skills_norm:
                    rep.errors.append(f"{label}: mentions '{term}' but no profile fact or listed skill supports it")
            for m in DEGREE_PAT.finditer(sent):
                tok = _norm(m.group(0)).replace(" ", "")
                sup_compact = sup.replace(" ", "")
                aliases = {tok, tok.replace(".", "")}
                if tok.startswith("ph") or tok.startswith("doctor"):
                    aliases |= {"phd", "ph.d", "ph.d.", "doctorate", "doctoral"}
                if not any(a and a in sup_compact for a in aliases):
                    rep.errors.append(f"{label}: claims degree '{m.group(0)}' that is not in the profile")
            for m in INSTITUTION_PAT.finditer(sent):
                if m.group(0).lower() not in sup:
                    rep.errors.append(f"{label}: names '{m.group(0)}' which does not appear in the profile")
            for m in YEARS_EXP_PAT.finditer(sent):
                if _norm(m.group(0)) not in sup:
                    rep.errors.append(f"{label}: claims '{m.group(0)}' of experience; not stated in the profile")
            for lang in LANGUAGES:
                if re.search(rf"\b{lang}\b", sent, re.I) and lang not in langs_norm:
                    rep.errors.append(f"{label}: mentions language '{lang.capitalize()}' that is not in the profile")
        for m in YEAR_PAT.finditer(sent):
            if m.group(0) not in support:
                rep.warnings.append(f"{label}: year {m.group(0)} not found in the cited facts")


def check_documents(profile: Profile, cv: dict | None, letter: dict | None, job: dict | None = None) -> GroundingReport:
    rep = GroundingReport()
    facts = {f.id: f.text for f in profile.facts}
    skills_norm = " | ".join(_norm(s) for s in profile.skills)
    langs_norm = " | ".join(_norm(l) for l in profile.languages)
    all_support = "\n".join(facts.values()) + "\n" + profile.headline + "\n" + "\n".join(profile.languages)
    # Job text may justify naming the company / role, but NOT skills, degrees or experience claims:
    # those words are exactly what an injected posting would try to smuggle in.
    job_names = f"{job.get('title', '')} {job.get('company', '')} {job.get('location', '')}" if job else ""

    def cite(label: str, ids: list[str]) -> str:
        bad = [i for i in ids if i not in facts]
        if bad:
            rep.errors.append(f"{label}: cites unknown fact id(s) {bad}")
        return "\n".join(facts[i] for i in ids if i in facts)

    if cv is not None:
        known = {_norm(s) for s in profile.skills}
        for s in cv.get("skills", []):
            if _norm(s) not in known:
                rep.errors.append(f"CV skills: '{s}' is not in the profile skill list")
        for l in cv.get("languages", []):
            base = _norm(l).split(" ")[0].strip("(,")
            if base not in langs_norm:
                rep.errors.append(f"CV languages: '{l}' is not in the profile")
        summ = cv.get("summary") or {}
        if summ.get("text"):
            sup = cite("CV summary", summ.get("fact_ids", [])) if summ.get("fact_ids") else all_support
            _check_text("CV summary", summ["text"], sup + "\n" + profile.headline, skills_norm, langs_norm, rep)
        for sec in cv.get("sections", []):
            for n, item in enumerate(sec.get("items", []), 1):
                label = f"CV '{sec.get('title', '?')}' item {n}"
                ids = item.get("fact_ids", [])
                if not ids:
                    rep.errors.append(f"{label}: does not cite any profile fact")
                sup = cite(label, ids)
                _check_text(label, f"{item.get('heading', '')}. {item.get('text', '')}", sup, skills_norm, langs_norm, rep)
        if cv.get("headline"):
            _check_text("CV headline", cv["headline"], all_support + "\n" + job_names, skills_norm, langs_norm, rep)

    if letter is not None:
        cite("Letter", letter.get("fact_ids", []))
        _check_text("Letter", letter.get("text", ""), all_support + "\n" + job_names, skills_norm, langs_norm, rep)

    # de-duplicate, keep order
    rep.errors = list(dict.fromkeys(rep.errors))
    rep.warnings = list(dict.fromkeys(rep.warnings))
    return rep
