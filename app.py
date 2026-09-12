from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from xml.etree import ElementTree

from flask import Flask, jsonify, render_template, request
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
MAX_RESUMES = 25
ALLOWED_DOCUMENT_SUFFIXES = (".pdf", ".docx")

# Canonical concepts deliberately make semantic matching visible and auditable.
# Add role-specific entries here as the product grows.
CONCEPTS = {
    "javascript": ["javascript", "js", "ecmascript"],
    "typescript": ["typescript", "ts"],
    "react": ["react", "reactjs", "react.js"],
    "node.js": ["node", "nodejs", "node.js", "express", "expressjs"],
    "python": ["python", "flask", "django", "fastapi"],
    "java": ["java", "spring", "spring boot"],
    "databases": ["database", "databases", "sql", "mysql", "postgresql", "mongodb", "mongo", "sqlite"],
    "rest api": ["rest", "restful", "api", "apis", "endpoint", "endpoints", "graphql"],
    "git": ["git", "github", "gitlab", "version control"],
    "html css": ["html", "css", "tailwind", "bootstrap", "responsive"],
    "cloud": ["aws", "azure", "gcp", "cloud", "docker", "kubernetes"],
    "testing": ["testing", "tests", "jest", "pytest", "unit test", "qa"],
    "agile": ["agile", "scrum", "sprint", "jira"],
    "communication": ["communication", "collaboration", "teamwork", "stakeholder"],
}
STOP = {"the", "and", "with", "for", "from", "that", "this", "will", "have", "are", "our", "your", "you", "into", "using", "work", "role", "candidate", "skills", "experience", "years", "about", "their", "they", "all", "who", "not", "but", "job", "team", "a", "an", "of", "to", "in", "on", "at", "is", "as", "be", "or"}


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z+#.]{1,}", plain(text)) if t not in STOP]


def extract_docx(data: bytes) -> str:
    """Read paragraph and table text from a modern Microsoft Word document."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as document:
            root = ElementTree.fromstring(document.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError("The Word document could not be read.") from exc
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_document(file) -> str:
    filename = file.filename or "document"
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if f".{suffix}" not in ALLOWED_DOCUMENT_SUFFIXES:
        raise ValueError("Only PDF and DOCX files are supported.")
    try:
        data = file.read()
        if suffix == "pdf":
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            text = extract_docx(data)
    except Exception as exc:
        raise ValueError(f"Could not read {filename}. Make sure it is a valid PDF or DOCX file.") from exc
    if not text.strip():
        raise ValueError(f"{filename} has no readable text. OCR scanned PDFs before uploading.")
    return text


def concepts_in(text: str) -> set[str]:
    normalized = plain(text)
    hits = set()
    for concept, aliases in CONCEPTS.items():
        if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", normalized) for alias in aliases):
            hits.add(concept)
    return hits


def jd_keywords(jd: str) -> list[str]:
    counts = Counter(tokens(jd))
    return [term for term, _ in counts.most_common(24)]


def keyword_score(jd: str, resume: str) -> tuple[float, list[str], list[str]]:
    jd_concepts, cv_concepts = concepts_in(jd), concepts_in(resume)
    concept_matches = sorted(jd_concepts & cv_concepts)
    missing = sorted(jd_concepts - cv_concepts)
    terms = set(jd_keywords(jd))
    exact_matches = sorted(term for term in terms if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", plain(resume)))
    # 65% named/normalized technical concepts + 35% literal JD wording.
    concept_part = len(concept_matches) / max(len(jd_concepts), 1)
    literal_part = len(exact_matches) / max(len(terms), 1)
    return 100 * (0.65 * concept_part + 0.35 * literal_part), concept_matches, missing


def semantic_scores(jd: str, resumes: list[str]) -> list[float]:
    # Word + character n-grams capture contextual phrases and formatting variants,
    # then cosine similarity measures meaning beyond exact whole-keyword overlap.
    corpus = [plain(jd)] + [plain(x) for x in resumes]
    try:
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), analyzer="word", sublinear_tf=True, stop_words="english")
        matrix = vectorizer.fit_transform(corpus)
        word_scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    except ValueError:  # Very short or punctuation-only input has no word vocabulary.
        word_scores = [0.0] * len(resumes)
    try:
        char_vectorizer = TfidfVectorizer(ngram_range=(3, 5), analyzer="char_wb", sublinear_tf=True)
        char_matrix = char_vectorizer.fit_transform(corpus)
        char_scores = cosine_similarity(char_matrix[0:1], char_matrix[1:]).flatten()
    except ValueError:
        char_scores = [0.0] * len(resumes)
    return [100 * (0.72 * word + 0.28 * char) for word, char in zip(word_scores, char_scores)]


def rank(jd: str, candidates: list[dict]) -> list[dict]:
    sem = semantic_scores(jd, [c["text"] for c in candidates])
    results = []
    for candidate, semantic in zip(candidates, sem):
        keyword, matched, missing = keyword_score(jd, candidate["text"])
        # Explicit 55/45 hybrid weighting—both components are always retained.
        final = 0.55 * semantic + 0.45 * keyword
        results.append({"name": candidate["name"], "score": round(final, 1), "semantic": round(semantic, 1),
                        "keyword": round(keyword, 1), "matched": matched, "missing": missing,
                        "text": candidate["text"]})
    results.sort(key=lambda x: x["score"], reverse=True)
    for i, result in enumerate(results, 1):
        result["rank"] = i
    return results


def sample_data():
    jd = """Junior Full Stack Developer Intern. Build responsive web features using JavaScript, React and Node.js. Work with REST APIs and SQL or MongoDB databases. Familiarity with Git, HTML, CSS, testing and agile teamwork is preferred."""
    resumes = [
        ("Aarav Sharma", "Full stack developer. Built responsive React and Node.js applications with Express REST APIs, MongoDB, Git and Jest testing. Collaborated in Agile sprints."),
        ("Maya Iyer", "Computer science student with JavaScript, React, HTML and CSS. Created a Flask REST API with PostgreSQL and deployed team projects using GitHub."),
        ("Rohan Mehta", "Backend intern using Python, Django, SQL, RESTful APIs and Docker. Familiar with Git, testing, Scrum and responsive frontend basics."),
        ("Nisha Kapoor", "UI designer experienced in Figma, CSS, accessibility and user research. Built portfolio pages with HTML and basic JavaScript."),
        ("Dev Patel", "Data analyst skilled in Python, pandas, Excel, SQL reporting and Tableau dashboards."),
    ]
    return jd, [{"name": name, "text": text} for name, text in resumes]


def audit_jd(jd: str) -> list[str]:
    """Flags wording to review; these are prompts, never automatic rejection rules."""
    checks = {
        r"\b(rockstar|ninja|superstar)\b": "Replace hype language with the concrete capabilities needed for the role.",
        r"\b(young|youthful|recent graduate)\b": "Age-adjacent wording may narrow the applicant pool; state the required experience instead.",
        r"\b(native english|native speaker)\b": "Specify communication proficiency rather than native-speaker status.",
        r"\b(he|she|his|her)\b": "Use gender-neutral role language where possible.",
        r"\b([5-9]|10)\+? years\b": "Check whether the requested experience is proportionate for an internship or junior role.",
    }
    return [message for pattern, message in checks.items() if re.search(pattern, plain(jd))]


def experience_profile(text: str) -> dict:
    """Extract lightweight, reviewable evidence of hands-on experience from resume text."""
    normalized = plain(text)
    years = [float(value) for value in re.findall(r"\b(\d{1,2}(?:\.\d+)?)\+?\s*(?:years?|yrs?)\b", normalized)]
    action_verbs = [
        verb for verb in ("built", "developed", "implemented", "created", "designed", "deployed", "led", "delivered")
        if re.search(rf"\b{verb}\b", normalized)
    ]
    roles = [role for role in ("internship", "intern", "freelance", "engineer", "developer") if re.search(rf"\b{role}\b", normalized)]
    return {"years": max(years, default=None), "actions": action_verbs, "roles": roles}


def describe_experience(candidate: dict) -> str:
    profile = experience_profile(candidate.get("text", ""))
    details = []
    if profile["years"] is not None:
        details.append(f"states up to {profile['years']:g} years of experience")
    if profile["roles"]:
        details.append("mentions " + ", ".join(profile["roles"][:2]))
    if profile["actions"]:
        details.append("shows hands-on work through " + ", ".join(profile["actions"][:4]))
    return "; ".join(details) if details else "does not make duration or delivery evidence explicit"


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/api/sample")
def sample():
    jd, candidates = sample_data()
    return jsonify({"jd": jd, "candidates": candidates, "results": rank(jd, candidates), "audit": audit_jd(jd)})


@app.post("/api/rank")
def api_rank():
    jd = request.form.get("jd", "").strip()
    if not jd and request.files.get("jd_pdf") and request.files["jd_pdf"].filename:
        try:
            jd = extract_document(request.files["jd_pdf"])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    uploaded_resumes = [file for file in request.files.getlist("resumes") if file.filename]
    if len(uploaded_resumes) > MAX_RESUMES:
        return jsonify({"error": f"Upload at most {MAX_RESUMES} resumes at a time."}), 400
    candidates = []
    for file in uploaded_resumes:
        try:
            text = extract_document(file)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        candidates.append({"name": re.sub(r"\.(pdf|docx)$", "", file.filename, flags=re.I), "text": text})
    if not jd:
        return jsonify({"error": "Add a job description or upload its PDF."}), 400
    if not candidates:
        return jsonify({"error": "Upload at least one text-based resume PDF or DOCX file."}), 400
    return jsonify({"jd": jd, "candidates": candidates, "results": rank(jd, candidates), "audit": audit_jd(jd)})


@app.post("/api/compare")
def compare():
    data = request.get_json(silent=True) or {}
    a, b = data.get("a"), data.get("b")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return jsonify({"error": "Choose two candidates to compare."}), 400
    stronger = a if a["score"] >= b["score"] else b
    weaker = b if stronger is a else a
    edge = sorted(set(stronger["matched"]) - set(weaker["matched"]))
    weaker_edge = sorted(set(weaker["matched"]) - set(stronger["matched"]))
    shared = sorted(set(stronger["matched"]) & set(weaker["matched"]))
    skill_points = []
    if edge:
        skill_points.append(f"{stronger['name']} uniquely shows explicit evidence of: {', '.join(edge)}.")
    else:
        skill_points.append("Both resumes show the same named JD concepts; the difference comes from contextual and literal-term relevance.")
    if weaker_edge:
        skill_points.append(f"{weaker['name']} uniquely shows: {', '.join(weaker_edge)}.")
    if shared:
        skill_points.append(f"Both candidates demonstrate: {', '.join(shared)}.")
    return jsonify({
        "headline": f"{stronger['name']} ranks higher by {abs(stronger['score']-weaker['score']):.1f} points.",
        "skills": skill_points,
        "experience": [
            f"{stronger['name']}: {describe_experience(stronger)}.",
            f"{weaker['name']}: {describe_experience(weaker)}.",
        ],
        "scores": [
            f"{stronger['name']}: semantic {stronger['semantic']}/100 · keyword {stronger['keyword']}/100.",
            f"{weaker['name']}: semantic {weaker['semantic']}/100 · keyword {weaker['keyword']}/100.",
        ],
        "note": "The ranking combines relevant named skills with contextual similarity across the resume.",
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
