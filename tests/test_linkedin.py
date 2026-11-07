import io
import zipfile

from fastapi.testclient import TestClient

from agent.linkedin import merge_into, read_export, to_profile_dict
from agent.profile import Profile

CSVS = {
    "Profile.csv": "First Name,Last Name,Maiden Name,Address,Birth Date,Headline,Summary,Industry,Zip Code,Geo Location,Twitter Handles,Websites,Instant Messengers\n"
                   "Lina,Haddad,,,\"Jan 1, 2002\",CS student | Data & ML,\"I like data, maps and clear docs.\",Software,,\"Darmstadt, Hesse, Germany\",,[PORTFOLIO:https://lina.example],\n",
    "Positions.csv": "Company Name,Title,Description,Location,Started On,Finished On\n"
                     "Werkwerk PLM Solutions,Working Student Technical Documentation,\"Tutorial videos and docs, in English and German\",Darmstadt,Mar 2025,\n",
    "Education.csv": "School Name,Start Date,End Date,Notes,Degree Name,Activities\nTU Darmstadt,2023,2027,,B.Sc. Computer Science,\n",
    "Skills.csv": "Name\nPython\nSQL\nPython\n",
    "Languages.csv": "Name,Proficiency\nGerman,Professional working proficiency\nArabic,Native or bilingual proficiency\n",
    "Email Addresses.csv": "Email Address,Confirmed,Primary,Updated On\nold@x.example,Yes,No,\nlina@mail.example,Yes,Yes,\n",
    "Certifications.csv": "Notes:\n\"Exported from LinkedIn\"\n\nName,Url,Authority,Started On,Finished On,License Number\nAWS Cloud Practitioner,,Amazon Web Services,Feb 2026,,\n",
    "Connections.csv": "First Name,Last Name\nSomeone,Else\n",
}


def make_zip() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, c in CSVS.items():
            z.writestr(f"Basic_LinkedInDataExport/{n}", c)
    return b.getvalue()


def test_parse_export():
    t = read_export([("Basic_LinkedInDataExport_11-04-2026.zip", make_zip())])
    assert "connections" not in t
    d = to_profile_dict(t)
    assert d["name"] == "Lina Haddad" and d["email"] == "lina@mail.example"
    assert d["location"].startswith("Darmstadt") and d["links"] == {"website1": "https://lina.example"}
    assert d["skills"] == ["Python", "SQL"]
    assert "German (Professional working proficiency)" in d["languages"]
    texts = " | ".join(f["text"] for f in d["facts"])
    assert "Working Student Technical Documentation at Werkwerk PLM Solutions" in texts and "Mar 2025 - present" in texts
    assert "B.Sc. Computer Science, TU Darmstadt" in texts
    assert "AWS Cloud Practitioner" in texts                    # parsed despite the Notes: preamble
    assert d["private"]["date_of_birth"] == "Jan 1, 2002"       # private, never shown to the model


def test_merge_keeps_existing_and_dedupes():
    base = {"user_id": "u1", "name": "Lina H.", "email": "", "skills": ["python"], "languages": ["German (B2)"],
            "facts": [{"id": "F1", "kind": "education", "text": "B.Sc. Computer Science, TU Darmstadt, 2023 - 2027"}]}
    m = merge_into(base, to_profile_dict(read_export([("x.zip", make_zip())])))
    assert m["name"] == "Lina H."                     # not overwritten
    assert m["email"] == "lina@mail.example"          # filled because it was empty
    assert m["skills"] == ["python", "SQL"]
    assert [l for l in m["languages"] if l.startswith("German")] == ["German (B2)"]
    assert [f["id"] for f in m["facts"]][0] == "F1" and len({f["id"] for f in m["facts"]}) == len(m["facts"])
    assert sum("TU Darmstadt" in f["text"] for f in m["facts"]) == 1   # duplicate education skipped
    Profile.model_validate(m)


def test_endpoint(tmp_path, monkeypatch):
    import app.server as srv
    monkeypatch.setattr(srv, "PROFILE_DIR", tmp_path)
    c = TestClient(srv.app)
    r = c.post("/api/profile/import", data={"user_id": "lina2", "base": "{}"},
               files=[("files", ("export.zip", make_zip(), "application/zip"))])
    assert r.status_code == 200, r.text
    assert r.json()["draft"]["name"] == "Lina Haddad" and r.json()["facts"] >= 4
    bad = c.post("/api/profile/import", data={"user_id": "lina2"}, files=[("files", ("cv.zip", b"PK\x05\x06" + b"\0" * 18, "application/zip"))])
    assert bad.status_code == 400


def test_linkedin_url_gets_helpful_error(tmp_path, monkeypatch):
    import app.server as srv
    monkeypatch.setattr(srv, "PROFILE_DIR", tmp_path)
    r = TestClient(srv.app).post("/api/profile/import", data={"user_id": "x1", "urls": "https://www.linkedin.com/in/someone/"})
    assert r.status_code == 400 and "Save to PDF" in r.json()["detail"]


def test_multiple_profiles(tmp_path, monkeypatch):
    import app.server as srv
    monkeypatch.setattr(srv, "PROFILE_DIR", tmp_path)
    c = TestClient(srv.app)
    for uid, name in [("nesrine", "Nesrine"), ("saloua", "Saloua")]:
        assert c.put(f"/api/profile/{uid}", json={"user_id": uid, "name": name, "email": ""}).status_code == 200
    ids = [p["user_id"] for p in c.get("/api/profiles").json()]
    assert {"nesrine", "saloua", "lina-test"} <= set(ids)
    assert c.delete("/api/profile/saloua").status_code == 200
    assert "saloua" not in [p["user_id"] for p in c.get("/api/profiles").json()]


def test_pdf_import_merges_into_existing_profile(tmp_path, monkeypatch):
    """LinkedIn 'Save to PDF' goes through the model; the result is merged, not replacing what the user has."""
    import app.server as srv
    monkeypatch.setattr(srv, "PROFILE_DIR", tmp_path)
    fake = Profile(user_id="n1", name="Nesrine B", email="n@x.example", skills=["Python", "C++"],
                   facts=[{"id": "F1", "kind": "experience", "text": "Working Student at PROSTEP, 2025 - present"}])
    monkeypatch.setattr(srv, "build_profile_with_llm", lambda uid, sources, llm: fake)
    monkeypatch.setattr(srv, "_llm", lambda: None)
    base = {"user_id": "n1", "name": "Nesrine", "email": "", "skills": ["python"],
            "facts": [{"id": "F1", "kind": "education", "text": "B.Sc. Informatik, TU Darmstadt"}]}
    import json as _j
    r = TestClient(srv.app).post("/api/profile/import", data={"user_id": "n1", "base": _j.dumps(base)},
                                 files=[("files", ("Profile.pdf", b"%PDF-fake", "application/pdf"))])
    # the fake PDF has no text layer -> clear error, nothing merged
    assert r.status_code == 400 and "could not be opened" in r.json()["detail"]
    monkeypatch.setattr(srv, "extract_text", lambda name, data: "LinkedIn profile text")
    r = TestClient(srv.app).post("/api/profile/import", data={"user_id": "n1", "base": _j.dumps(base)},
                                 files=[("files", ("Profile.pdf", b"%PDF-fake", "application/pdf"))])
    d = r.json()["draft"]
    assert d["name"] == "Nesrine" and d["email"] == "n@x.example"
    assert [f["id"] for f in d["facts"]] == ["F1", "F2"] and d["skills"] == ["python", "C++"]
