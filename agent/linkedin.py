"""Import the official LinkedIn data export (Settings -> Data privacy -> Get a copy of your data).

The export is a ZIP of CSV files. We parse it deterministically (no model, nothing invented):
Profile.csv, Positions.csv, Education.csv, Skills.csv, Languages.csv, Certifications.csv,
Projects.csv, Honors.csv, Volunteering.csv, Email Addresses.csv, PhoneNumbers.csv.
Missing files or columns are skipped. Birth date goes to `private` (never shown to the model).
"""
from __future__ import annotations

import csv
import io
import re
import zipfile

KNOWN = {"profile", "positions", "education", "skills", "languages", "certifications", "projects", "honors",
         "volunteering", "email addresses", "phonenumbers", "phone numbers"}


def _key(name: str) -> str:
    base = re.sub(r"\.csv$", "", name.replace("\\", "/").split("/")[-1], flags=re.I)
    return base.strip().lower().replace("_", " ")


def _rows(text: str) -> list[dict]:
    """LinkedIn CSVs sometimes start with 'Notes:' lines before the header; skip them."""
    lines = text.lstrip("﻿").splitlines()
    start = 0
    for i, l in enumerate(lines[:10]):
        if "," in l and not l.lower().startswith("notes"):
            start = i
            break
    rdr = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rdr]


def read_export(files: list[tuple[str, bytes]]) -> dict[str, list[dict]]:
    """files = [(filename, bytes)]: a .zip export and/or individual CSVs."""
    tables: dict[str, list[dict]] = {}
    for name, data in files:
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if n.lower().endswith(".csv") and _key(n) in KNOWN:
                        tables[_key(n)] = _rows(z.read(n).decode("utf-8", errors="replace"))
        elif name.lower().endswith(".csv") and _key(name) in KNOWN:
            tables[_key(name)] = _rows(data.decode("utf-8", errors="replace"))
    if "phone numbers" in tables:
        tables["phonenumbers"] = tables.pop("phone numbers")
    return tables


def _g(r: dict, *names: str) -> str:
    for n in names:
        if r.get(n.lower()):
            return r[n.lower()]
    return ""


def _dates(a: str, b: str) -> str:
    if not a and not b:
        return ""
    return f"{a or '?'} - {b or 'present'}"


def _sentence(*parts: str) -> str:
    s = ", ".join(p for p in parts if p)
    return re.sub(r"\s+", " ", s)[:600]


def to_profile_dict(tables: dict[str, list[dict]]) -> dict:
    out = {"name": "", "email": "", "phone": "", "location": "", "links": {}, "headline": "",
           "skills": [], "languages": [], "facts": [], "old_letters": [], "private": {}}
    p = (tables.get("profile") or [{}])[0]
    out["name"] = " ".join(x for x in [_g(p, "First Name"), _g(p, "Last Name")] if x)
    out["headline"] = _g(p, "Headline")
    out["location"] = _g(p, "Geo Location", "Location")
    for w in re.findall(r"https?://[^\s,\]\[]+", _g(p, "Websites")):
        out["links"][f"website{len(out['links']) + 1}"] = w
    if _g(p, "Birth Date"):
        out["private"]["date_of_birth"] = _g(p, "Birth Date")

    emails = tables.get("email addresses", [])
    prim = [e for e in emails if _g(e, "Primary").lower() == "yes"] or emails
    if prim:
        out["email"] = _g(prim[0], "Email Address")
    phones = tables.get("phonenumbers", [])
    if phones:
        out["phone"] = _g(phones[0], "Number")

    facts: list[tuple[str, str]] = []
    if _g(p, "Summary"):
        facts.append(("other", "LinkedIn summary: " + _g(p, "Summary")))
    for r in tables.get("positions", []):
        title, comp = _g(r, "Title"), _g(r, "Company Name")
        head = f"{title} at {comp}" if title and comp else title or comp
        desc = _g(r, "Description")
        facts.append(("experience", _sentence(head, _g(r, "Location"), _dates(_g(r, "Started On"), _g(r, "Finished On")))
                      + (f": {desc}" if desc else "")))
    for r in tables.get("education", []):
        facts.append(("education", _sentence(_g(r, "Degree Name"), _g(r, "School Name"),
                                             _dates(_g(r, "Start Date"), _g(r, "End Date")), _g(r, "Notes"), _g(r, "Activities"))))
    for r in tables.get("certifications", []):
        facts.append(("certification", _sentence(_g(r, "Name"), _g(r, "Authority"), _g(r, "Started On"))))
    for r in tables.get("projects", []):
        desc = _g(r, "Description")
        facts.append(("project", _sentence("Project: " + _g(r, "Title"), _dates(_g(r, "Started On"), _g(r, "Finished On")))
                      + (f": {desc}" if desc else "")))
    for r in tables.get("honors", []):
        facts.append(("award", _sentence(_g(r, "Title"), _g(r, "Issued On"), _g(r, "Description"))))
    for r in tables.get("volunteering", []):
        role, org = _g(r, "Role"), _g(r, "Company Name")
        facts.append(("volunteering", _sentence(f"{role} at {org}" if role and org else role or org, _g(r, "Cause"),
                                                _dates(_g(r, "Started On"), _g(r, "Finished On")), _g(r, "Description"))))
    out["facts"] = [{"kind": k, "text": t[:600]} for k, t in facts if len(t.strip()) >= 3]
    out["skills"] = list(dict.fromkeys(_g(r, "Name") for r in tables.get("skills", []) if _g(r, "Name")))
    out["languages"] = [f"{_g(r, 'Name')} ({_g(r, 'Proficiency')})" if _g(r, "Proficiency") else _g(r, "Name")
                        for r in tables.get("languages", []) if _g(r, "Name")]
    return out


def merge_into(base: dict, li: dict) -> dict:
    """Add LinkedIn data to an existing profile without overwriting what the user already has.
    New facts get fresh ids; duplicate facts, skills and languages are skipped."""
    m = dict(base)
    for k in ("name", "email", "phone", "location", "headline"):
        if not m.get(k) and li.get(k):
            m[k] = li[k]
    m["links"] = {**li.get("links", {}), **(m.get("links") or {})}
    have = {s.lower() for s in m.get("skills", [])}
    m["skills"] = list(m.get("skills", [])) + [s for s in li["skills"] if s.lower() not in have]
    have_l = {l.split(" (")[0].lower() for l in m.get("languages", [])}
    m["languages"] = list(m.get("languages", [])) + [l for l in li["languages"] if l.split(" (")[0].lower() not in have_l]
    facts = list(m.get("facts", []))
    texts = {re.sub(r"\W+", " ", f["text"].lower()).strip() for f in facts}
    n = max([int(f["id"][1:]) for f in facts if re.match(r"^F\d+$", f.get("id", ""))] + [0])
    for f in li["facts"]:
        norm = re.sub(r"\W+", " ", f["text"].lower()).strip()
        if norm in texts:
            continue
        n += 1
        facts.append({"id": f"F{n}", "kind": f["kind"], "text": f["text"]})
        texts.add(norm)
    m["facts"] = facts
    old = list(m.get("old_letters") or [])
    m["old_letters"] = old + [l for l in li.get("old_letters", []) if l and l not in old]
    m["private"] = {**li.get("private", {}), **(m.get("private") or {})}
    return m
