from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass

from flask import Flask, jsonify, render_template, request
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

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


def extract_pdf(file) -> str:
    reader = PdfReader(io.BytesIO(file.read()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


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
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), analyzer="word", sublinear_tf=True, stop_words="english")
    matrix = vectorizer.fit_transform(corpus)
    word_scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    char_vectorizer = TfidfVectorizer(ngram_range=(3, 5), analyzer="char_wb", sublinear_tf=True)
    char_matrix = char_vectorizer.fit_transform(corpus)
    char_scores = cosine_similarity(char_matrix[0:1], char_matrix[1:]).flatten()
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
        jd = extract_pdf(request.files["jd_pdf"])
    candidates = []
    for i, file in enumerate(request.files.getlist("resumes"), 1):
        if file.filename:
            text = extract_pdf(file)
            if text.strip():
                candidates.append({"name": re.sub(r"\.pdf$", "", file.filename, flags=re.I), "text": text})
    if not jd:
        return jsonify({"error": "Add a job description or upload its PDF."}), 400
    if not candidates:
        return jsonify({"error": "Upload at least one text-based resume PDF."}), 400
    return jsonify({"jd": jd, "candidates": candidates, "results": rank(jd, candidates), "audit": audit_jd(jd)})


@app.post("/api/compare")
def compare():
    data = request.get_json()
    a, b = data["a"], data["b"]
    stronger = a if a["score"] >= b["score"] else b
    weaker = b if stronger is a else a
    edge = sorted(set(stronger["matched"]) - set(weaker["matched"]))
    message = f"{stronger['name']} ranks higher by {abs(stronger['score']-weaker['score']):.1f} points. "
    message += ("Its clearest advantage is evidence of " + ", ".join(edge) + ".") if edge else "It has a stronger combined semantic/context and explicit-keyword match."
    return jsonify({"message": message})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
