from __future__ import annotations

import io
import os
import re
import time
import zipfile
import hashlib
import threading
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
    "rest api": ["rest", "restful", "api", "apis", "endpoint", "endpoints", "graphql", "json"],
    "git": ["git", "github", "gitlab", "version control"],
    "html css": ["html", "css", "tailwind", "bootstrap", "responsive"],
    # Docker / Containerization: Decoupled from "cloud" into its own concept.
    # Reason: Structured JDs (such as TechNova) list "Cloud basics (AWS/GCP/Azure)" and
    # "Docker / basic containerization" as separate items under "good-to-have". Separating them
    # prevents Docker alone from falsely fulfilling cloud requirements, and allows granular,
    # independent gap detection for container vs cloud infrastructure.
    "cloud": ["aws", "azure", "gcp", "cloud"],
    "containerization": ["docker", "kubernetes", "container", "containers", "containerization"],
    "testing": ["testing", "tests", "jest", "mocha", "pytest", "unit test", "qa"],
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


def split_jd_sections(jd_text: str) -> dict[str, str]:
    """Detects common section headers case-insensitively using regex and splits the JD text
    into {'must_have': '...', 'good_to_have': '...', 'other': '...'}.
    If no recognizable headers are found, puts the entire JD text into 'must_have' as safe fallback.
    """
    if not jd_text or not jd_text.strip():
        return {"must_have": "", "good_to_have": "", "other": ""}

    # 1. Match section headers at line boundaries (multiline mode)
    header_pattern = re.compile(
        r"(?m)^[ \t*#-_]*(?:"
        r"(?P<must_have>must[\s-]have(?:\s+(?:skills?|requirements?|qualifications?))?|required(?:\s+(?:skills?|qualifications?|requirements?))?|core\s+skills?|minimum\s+qualifications?|basic\s+qualifications?)"
        r"|(?P<good_to_have>good[\s-]to[\s-]have(?:\s+(?:skills?|requirements?|qualifications?))?|nice[\s-]to[\s-]have(?:\s+(?:skills?|requirements?|qualifications?))?|preferred(?:\s+(?:skills?|qualifications?|requirements?))?|desired(?:\s+skills?)?|bonus(?:\s+skills?)?|pluses?)"
        r"|(?P<other>about(?:\s+(?:the\s+role|us|the\s+company))?|key\s+responsibilities|responsibilities|what\s+you(?:'ll|\s+will)\s+do|soft\s+skills|benefits|what\s+we\s+offer|compensation|who\s+you\s+are|overview)"
        r")[ \t*#:_]*$",
        re.IGNORECASE,
    )

    matches = list(header_pattern.finditer(jd_text))

    # 2. If no line-level headers found, try inline boundary matching (for unformatted/inline JDs)
    if not matches:
        inline_pattern = re.compile(
            r"(?:^|[.\n;]\s*)(?:"
            r"(?P<must_have>must[\s-]have(?:\s+(?:skills?|requirements?|qualifications?))?|required(?:\s+(?:skills?|qualifications?|requirements?))?|core\s+skills?)"
            r"|(?P<good_to_have>good[\s-]to[\s-]have(?:\s+(?:skills?|requirements?|qualifications?))?|nice[\s-]to[\s-]have(?:\s+(?:skills?|requirements?|qualifications?))?|preferred(?:\s+(?:skills?|qualifications?|requirements?))?|bonus(?:\s+skills?)?)"
            r"|(?P<other>key\s+responsibilities|responsibilities|soft\s+skills)"
            r")[:\s-]+",
            re.IGNORECASE,
        )
        matches = list(inline_pattern.finditer(jd_text))

    if not matches:
        return {"must_have": jd_text.strip(), "good_to_have": "", "other": ""}

    sections: dict[str, list[str]] = {"must_have": [], "good_to_have": [], "other": []}
    if matches[0].start() > 0:
        preamble = jd_text[:matches[0].start()].strip()
        if preamble:
            sections["other"].append(preamble)

    for i, m in enumerate(matches):
        category = m.lastgroup or "other"
        end = matches[i + 1].start() if i + 1 < len(matches) else len(jd_text)
        chunk = jd_text[m.end():end].strip()
        if chunk:
            sections[category].append(chunk)

    result = {k: "\n".join(v).strip() for k, v in sections.items()}
    if not result["must_have"] and not result["good_to_have"]:
        result["must_have"] = jd_text.strip()
    return result


# Tunable fixed penalty deducted per missing must-have concept.
# Why a flat penalty in addition to ratio weighting:
# Importance ratios (e.g. 0.85 / 0.15) alone get diluted across nested scoring stages:
# the concept ratio is 65% of the keyword score, which in turn is only 45% of the overall hybrid score.
# Under ratio weighting alone, a missing critical requirement only changes the final score by 2-3 points.
# Adding a direct flat deduction guarantees high-visibility accountability for non-negotiable role requirements
# in the final score, while good-to-have gaps only modulate the ratio without incurring this penalty.
MUST_HAVE_GAP_PENALTY = 8.0


def score_candidate_keywords(
    resume: str,
    jd_must_concepts: set[str],
    jd_good_concepts: set[str],
    terms: set[str],
) -> tuple[float, list[str], list[str], list[str]]:
    cv_concepts = concepts_in(resume)

    must_matches = jd_must_concepts & cv_concepts
    good_matches = jd_good_concepts & cv_concepts
    all_matched = sorted((jd_must_concepts | jd_good_concepts) & cv_concepts)

    missing_must = sorted(jd_must_concepts - cv_concepts)
    missing_good = sorted(jd_good_concepts - cv_concepts)

    # Concept component: 85% must-have match ratio + 15% good-to-have match ratio
    if jd_must_concepts and jd_good_concepts:
        must_ratio = len(must_matches) / len(jd_must_concepts)
        good_ratio = len(good_matches) / len(jd_good_concepts)
        concept_part = 0.85 * must_ratio + 0.15 * good_ratio
    elif jd_must_concepts:
        concept_part = len(must_matches) / len(jd_must_concepts)
    elif jd_good_concepts:
        concept_part = len(good_matches) / len(jd_good_concepts)
    else:
        concept_part = 0.0

    # 35% literal JD term overlap
    resume_plain = plain(resume)
    exact_matches = sorted(term for term in terms if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", resume_plain))
    literal_part = len(exact_matches) / max(len(terms), 1)

    raw_score = 100 * (0.65 * concept_part + 0.35 * literal_part)

    # Direct flat penalty for each missing must-have concept (good-to-have gaps do NOT trigger this penalty)
    must_have_penalty = MUST_HAVE_GAP_PENALTY * len(missing_must)
    final_score = max(0.0, raw_score - must_have_penalty)

    return round(final_score, 1), all_matched, missing_must, missing_good


def keyword_score(jd: str, resume: str) -> tuple[float, list[str], list[str], list[str]]:
    sections = split_jd_sections(jd)
    jd_must_concepts = concepts_in(sections["must_have"])
    jd_good_concepts = concepts_in(sections["good_to_have"]) - jd_must_concepts
    if not jd_must_concepts and not jd_good_concepts:
        jd_must_concepts = concepts_in(jd)
    terms = set(jd_keywords(jd))
    return score_candidate_keywords(resume, jd_must_concepts, jd_good_concepts, terms)


_EMBEDDING_LOCK = threading.Lock()
_EMBEDDING_MODEL = None
_EMBEDDING_INITIALIZED = False
_ACTIVE_ENGINE = "uninitialized"


def get_embedding_model():
    """Lazily load SentenceTransformer model as a true singleton with fallback to None on error."""
    global _EMBEDDING_MODEL, _EMBEDDING_INITIALIZED, _ACTIVE_ENGINE
    if _EMBEDDING_INITIALIZED:
        return _EMBEDDING_MODEL
    with _EMBEDDING_LOCK:
        if _EMBEDDING_INITIALIZED:
            return _EMBEDDING_MODEL
        print("[MODEL LOAD] Loading SentenceTransformer embedding model...", flush=True)
        try:
            from sentence_transformers import SentenceTransformer
            try:
                # Fast path: Load from local cache to prevent remote HuggingFace Hub network checks
                _EMBEDDING_MODEL = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
            except Exception:
                # Fallback: Download if not available in local cache
                _EMBEDDING_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
            _ACTIVE_ENGINE = "all-MiniLM-L6-v2 (Dense Embeddings)"
        except Exception as exc:
            _EMBEDDING_MODEL = None
            _ACTIVE_ENGINE = f"TF-IDF Fallback ({exc.__class__.__name__})"
        _EMBEDDING_INITIALIZED = True
        return _EMBEDDING_MODEL


def get_semantic_engine_info() -> str:
    get_embedding_model()
    return _ACTIVE_ENGINE


def tfidf_semantic_scores(jd: str, resumes: list[str]) -> list[float]:
    """Fallback semantic scorer using word and character n-gram TF-IDF vectors."""
    if not resumes:
        return []
    corpus = [plain(jd)] + [plain(x) for x in resumes]
    try:
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), analyzer="word", sublinear_tf=True, stop_words="english")
        matrix = vectorizer.fit_transform(corpus)
        word_scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    except ValueError:
        word_scores = [0.0] * len(resumes)
    try:
        char_vectorizer = TfidfVectorizer(ngram_range=(3, 5), analyzer="char_wb", sublinear_tf=True)
        char_matrix = char_vectorizer.fit_transform(corpus)
        char_scores = cosine_similarity(char_matrix[0:1], char_matrix[1:]).flatten()
    except ValueError:
        char_scores = [0.0] * len(resumes)
    return [round(float(100 * (0.72 * word + 0.28 * char)), 1) for word, char in zip(word_scores, char_scores)]


def dense_semantic_scores(jd: str, resumes: list[str], model) -> list[float]:
    """Compute dense contextual semantic similarity in a single batched Sentence Transformer call."""
    if not resumes:
        return []
    jd_cleaned = plain(jd)
    cv_cleaned = [plain(x) for x in resumes]
    all_texts = [jd_cleaned] + cv_cleaned
    # Single batched encode call for JD and all resumes combined
    all_embs = model.encode(
        all_texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    jd_emb = all_embs[0:1]
    cv_embs = all_embs[1:]
    sims = cosine_similarity(jd_emb, cv_embs).flatten()
    return [round(float(max(0.0, sim) * 100), 1) for sim in sims]


def semantic_scores(jd: str, resumes: list[str]) -> list[float]:
    """Compute semantic scores preferring dense embeddings with automated TF-IDF fallback."""
    if not resumes:
        return []
    model = get_embedding_model()
    if model is not None:
        try:
            return dense_semantic_scores(jd, resumes, model)
        except Exception:
            pass
    return tfidf_semantic_scores(jd, resumes)


def rank_with_timings(
    jd: str,
    candidates: list[dict],
    semantic_weight: float = 0.55,
    required: set[str] | None = None,
) -> tuple[list[dict], dict[str, float]]:
    required = required or set()
    semantic_weight = min(max(semantic_weight, 0.0), 1.0)
    keyword_weight = 1 - semantic_weight

    t_dense_start = time.perf_counter()
    sem = semantic_scores(jd, [c["text"] for c in candidates])
    t_dense = time.perf_counter() - t_dense_start

    t_kw_start = time.perf_counter()
    # Pre-parse JD sections, concepts, and keywords ONCE across all candidates
    sections = split_jd_sections(jd)
    jd_must_concepts = concepts_in(sections["must_have"])
    jd_good_concepts = concepts_in(sections["good_to_have"]) - jd_must_concepts
    if not jd_must_concepts and not jd_good_concepts:
        jd_must_concepts = concepts_in(jd)
    terms = set(jd_keywords(jd))

    results = []
    for candidate, semantic in zip(candidates, sem):
        keyword, matched, missing_must, missing_good = score_candidate_keywords(
            candidate["text"],
            jd_must_concepts,
            jd_good_concepts,
            terms,
        )
        # Explicit 55/45 hybrid weighting—both components are always retained.
        final = semantic_weight * semantic + keyword_weight * keyword
        results.append({
            "name": candidate["name"],
            "score": round(final, 1),
            "semantic": round(semantic, 1),
            "keyword": round(keyword, 1),
            "matched": matched,
            "missing": sorted(set(missing_must + missing_good)),
            "missing_must_have": missing_must,
            "missing_good_to_have": missing_good,
            "required_missing": sorted(required - set(matched)),
            "text": candidate["text"],
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    for i, result in enumerate(results, 1):
        result["rank"] = i
    t_kw = time.perf_counter() - t_kw_start

    return results, {"dense_sec": t_dense, "keyword_sec": t_kw}


def rank(jd: str, candidates: list[dict], semantic_weight: float = 0.55, required: set[str] | None = None) -> list[dict]:
    results, _ = rank_with_timings(jd, candidates, semantic_weight, required)
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
    summary = "; ".join(details) if details else "does not make duration or delivery evidence explicit"
    missing_must = candidate.get("missing_must_have", [])
    missing_good = candidate.get("missing_good_to_have", [])
    if missing_must:
        summary += f" | CRITICAL MUST-HAVE GAP: lacks {', '.join(missing_must)}"
    elif missing_good:
        summary += f" | Preferred gap: missing good-to-have {', '.join(missing_good)}"
    return summary


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/api/sample")
def sample():
    jd, candidates = sample_data()
    return jsonify({
        "jd": jd,
        "candidates": candidates,
        "results": rank(jd, candidates),
        "audit": audit_jd(jd),
        "semantic_engine": get_semantic_engine_info(),
    })


@app.post("/api/rank")
def api_rank():
    t_start = time.perf_counter()

    # 1. Model retrieval
    t_model_start = time.perf_counter()
    _ = get_embedding_model()
    t_model = time.perf_counter() - t_model_start

    # 2. Document extraction
    t_extract_start = time.perf_counter()
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
    seen_resumes = set()
    duplicates_removed = []
    for file in uploaded_resumes:
        try:
            text = extract_document(file)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        fingerprint = hashlib.sha256(plain(text).encode("utf-8")).hexdigest()
        if fingerprint in seen_resumes:
            duplicates_removed.append(file.filename)
            continue
        seen_resumes.add(fingerprint)
        candidates.append({"name": re.sub(r"\.(pdf|docx)$", "", file.filename, flags=re.I), "text": text})
    t_extract = time.perf_counter() - t_extract_start

    if not jd:
        return jsonify({"error": "Add a job description or upload its PDF."}), 400
    if not candidates:
        return jsonify({"error": "Upload at least one text-based resume PDF or DOCX file."}), 400
    try:
        semantic_weight = float(request.form.get("semantic_weight", 55)) / 100
    except ValueError:
        semantic_weight = 0.55
    required = {plain(term) for term in request.form.get("required_skills", "").split(",") if plain(term)}
    known_required = {concept for concept in CONCEPTS if concept in required}

    results, engine_timings = rank_with_timings(jd, candidates, semantic_weight, known_required)

    t_total = time.perf_counter() - t_start

    timings = {
        "model_retrieval_sec": round(t_model, 4),
        "file_extraction_sec": round(t_extract, 4),
        "dense_embedding_sec": round(engine_timings["dense_sec"], 4),
        "keyword_scoring_sec": round(engine_timings["keyword_sec"], 4),
        "total_request_sec": round(t_total, 4),
    }

    return jsonify({
        "jd": jd,
        "candidates": candidates,
        "results": results,
        "audit": audit_jd(jd),
        "weights": {"semantic": round(semantic_weight * 100), "keyword": round((1 - semantic_weight) * 100)},
        "required": sorted(known_required),
        "duplicates_removed": duplicates_removed,
        "semantic_engine": get_semantic_engine_info(),
        "timings": timings,
    })


@app.route("/api/warmup", methods=["GET", "POST"])
def api_warmup():
    """Warmup endpoint to pre-load the model and warm up PyTorch/tokenizer threads."""
    t0 = time.perf_counter()
    model = get_embedding_model()
    if model is not None:
        try:
            model.encode(["warmup probe sentence"], show_progress_bar=False, normalize_embeddings=True)
        except Exception:
            pass
    warmup_sec = round(time.perf_counter() - t0, 4)
    return jsonify({
        "status": "ready",
        "semantic_engine": get_semantic_engine_info(),
        "warmup_sec": warmup_sec,
    })


def warmup_server():
    """Hook to pre-load the embedding model at server launch."""
    try:
        get_embedding_model()
    except Exception as exc:
        print(f"[WARMUP ERROR] Preload failed: {exc}", flush=True)


@app.post("/api/compare")
def compare():
    data = request.get_json(silent=True) or {}
    a, b = data.get("a"), data.get("b")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return jsonify({"error": "Choose two candidates to compare."}), 400
    stronger = a if a["score"] >= b["score"] else b
    weaker = b if stronger is a else a
    edge = sorted(set(stronger.get("matched", [])) - set(weaker.get("matched", [])))
    weaker_edge = sorted(set(weaker.get("matched", [])) - set(stronger.get("matched", [])))
    shared = sorted(set(stronger.get("matched", [])) & set(weaker.get("matched", [])))

    stronger_must = stronger.get("missing_must_have", [])
    weaker_must = weaker.get("missing_must_have", [])
    stronger_good = stronger.get("missing_good_to_have", [])
    weaker_good = weaker.get("missing_good_to_have", [])

    skill_points = []
    if edge:
        skill_points.append(f"{stronger['name']} uniquely shows explicit evidence of: {', '.join(edge)}.")
    else:
        skill_points.append("Both resumes show the same named JD concepts; the difference comes from contextual and literal-term relevance.")
    if weaker_edge:
        skill_points.append(f"{weaker['name']} uniquely shows: {', '.join(weaker_edge)}.")
    if shared:
        skill_points.append(f"Both candidates demonstrate: {', '.join(shared)}.")

    # Distinctly call out must-have gaps with highest priority
    if weaker_must:
        skill_points.append(f"CRITICAL MUST-HAVE GAP: {weaker['name']} lacks {', '.join(weaker_must)}.")
    if stronger_must:
        skill_points.append(f"MUST-HAVE GAP: {stronger['name']} lacks {', '.join(stronger_must)}.")
    if weaker_good:
        skill_points.append(f"Good-to-have gap: {weaker['name']} does not mention {', '.join(weaker_good)}.")
    if stronger_good:
        skill_points.append(f"Good-to-have gap: {stronger['name']} does not mention {', '.join(stronger_good)}.")
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
        "note": f"The ranking combines relevant named skills with contextual similarity via {get_semantic_engine_info()}.",
    })


if __name__ == "__main__":
    warmup_server()
    app.run(debug=True, port=5000)

