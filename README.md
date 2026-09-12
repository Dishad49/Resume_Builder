# Talon Smart Shortlisting Engine

An explainable resume-ranking web app built with a **Hybrid ML Architecture** that blends pre-trained dense embeddings with auditable rule-based concept matching.

## Run locally

```powershell
# Create & activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies (including sentence-transformers & torch)
pip install -r requirements.txt

# Run the Flask app
python app.py
```

Open `http://127.0.0.1:5000`. Paste a job description or upload its PDF/DOCX file, then upload up to 25 candidate resumes as PDF or DOCX. Use **Try demo data** for a no-files-required walkthrough.

## Hybrid Scoring Architecture

Each applicant receives a transparent, auditable hybrid fit score:

- **55% Semantic Context Score (Dense Embeddings / Phase 1 ML Upgrade):**
  - Uses `sentence-transformers/all-MiniLM-L6-v2` to map the job description and candidate resumes into 384-dimensional dense semantic vectors.
  - Computes cosine similarity to capture true contextual meaning, domain synonyms (e.g. "frontend engineer" vs "UI developer", "RDBMS" vs "SQL"), and phrasing nuances without requiring custom training data.
  - **Graceful Resilience Layer:** If PyTorch or model weights are unavailable or in an offline environment, the system automatically falls back to dual TF-IDF (word n-grams + character n-grams) without crashing.
  - **Engine Transparency:** The active engine (`all-MiniLM-L6-v2 (Dense Embeddings)` or `TF-IDF Fallback`) is visible in the UI results header and API payload.
- **45% Rule-Based Concept & Keyword Evidence:**
  - Explicit JD terms plus a visible, editable concept/synonym map (`CONCEPTS` in `app.py`), such as Express → Node.js and MongoDB → databases.
  - Every matched and missing skill is highlighted for recruiters to inspect.

The UI shows both component scores, matched evidence, missing JD concepts, top-three explanations, candidate side-by-side comparison, and a non-decisive JD wording review.

## ML Evolution Roadmap

```
Phase 1: Pre-trained Dense Embeddings (Completed)
  └── Replaces lexical TF-IDF with all-MiniLM-L6-v2 dense embeddings while retaining TF-IDF fallback.

Phase 2: Dynamic Skill & Entity Extraction (Next)
  └── Pre-trained NER pipeline (spaCy / SkillNER) to extract emerging skills and credentials dynamically.

Phase 3: Supervised Learning-to-Rank (Future)
  └── Train a re-ranker (e.g., LightGBM / XGBoost Ranker) using recruiter decision data (shortlist/reject).
```

## Notes for the demo

- PDFs must contain selectable text. Scanned PDFs require OCR before upload. Modern `.docx` files are supported directly.
- The multi-upload flow accepts up to 25 resumes per batch and automatically deduplicates identical resumes.
- Tailor `CONCEPTS` in `app.py` before the final demo if the provided JD uses specialist technologies not in the initial map.
