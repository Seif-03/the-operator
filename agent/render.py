"""Render the tailored CV and the letter to PDF (reportlab)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

_ss = getSampleStyleSheet()
NAME = ParagraphStyle("name", parent=_ss["Title"], fontSize=20, spaceAfter=2, alignment=0)
SUB = ParagraphStyle("sub", parent=_ss["Normal"], fontSize=9.5, textColor="#555555", spaceAfter=8)
H = ParagraphStyle("h", parent=_ss["Heading3"], fontSize=11.5, textColor="#1f4e79", spaceBefore=10, spaceAfter=3)
BODY = ParagraphStyle("b", parent=_ss["Normal"], fontSize=10, leading=13.5)
ITEM = ParagraphStyle("i", parent=BODY, leftIndent=8, spaceAfter=4)


def _p(t: str, st=BODY) -> Paragraph:
    return Paragraph(escape(t or "").replace("\n", "<br/>"), st)


def render_cv(profile, cv: dict, path: Path) -> Path:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"CV {profile.name}", author=profile.name)
    contact = " · ".join(x for x in [profile.email, profile.phone, profile.location, *profile.links.values()] if x)
    els = [_p(profile.name, NAME), _p(cv.get("headline", profile.headline), SUB), _p(contact, SUB)]
    if (cv.get("summary") or {}).get("text"):
        els += [_p("Profile", H), _p(cv["summary"]["text"])]
    for sec in cv.get("sections", []):
        els.append(_p(sec.get("title", ""), H))
        for it in sec.get("items", []):
            head = f"<b>{escape(it.get('heading', ''))}</b>"
            txt = escape(it.get("text", ""))
            els.append(Paragraph(f"{head}<br/>{txt}" if txt else head, ITEM))
    if cv.get("skills"):
        els += [_p("Skills", H), _p(", ".join(cv["skills"]))]
    if cv.get("languages"):
        els += [_p("Languages", H), _p(", ".join(cv["languages"]))]
    doc.build(els)
    return path


def render_letter(profile, job: dict, letter_text: str, path: Path) -> Path:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
                            title=f"Cover letter {profile.name}", author=profile.name)
    els = [_p(profile.name, BODY), _p(" · ".join(x for x in [profile.email, profile.phone, profile.location] if x), SUB),
           Spacer(1, 8), *[_p(job[k], BODY) for k in ("company", "location") if job.get(k)], Spacer(1, 10),
           _p(date.today().strftime("%d %B %Y"), BODY), Spacer(1, 10),
           Paragraph(f"<b>Application: {escape(job.get('title', ''))}</b>", BODY), Spacer(1, 10)]
    for para in [p for p in letter_text.split("\n\n") if p.strip()]:
        els += [_p(para.strip()), Spacer(1, 7)]
    doc.build(els)
    return path
