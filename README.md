# InternLoom Smart Shortlisting Engine

An explainable resume-ranking web app built for the InternLoom AI Hackathon.

## Run locally

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. Paste a job description or upload its PDF/DOCX file, then upload up to 25 candidate resumes as PDF or DOCX. Use **Try demo data** for a no-files-required walkthrough.

## How scoring works

Each applicant receives a transparent hybrid score:

- **55% semantic/context score:** TF-IDF word and phrase vectors plus character n-grams, compared to the JD using cosine similarity. This recognizes related contextual language and remains robust to light formatting/typing variations.
- **45% keyword evidence:** explicit JD terms plus a visible, editable concept/synonym map (`CONCEPTS` in `app.py`), such as Express → Node.js and MongoDB → databases.

The UI shows both component scores, matched evidence, and missing JD concepts. It also includes top-three explanations, a candidate comparison question, and a non-decisive JD wording review. Scores are produced by the local matching pipeline—no LLM is asked to judge a resume.

## Notes for the demo

- PDFs must contain selectable text. Scanned PDFs require OCR before upload. Modern `.docx` files are supported directly.
- The provided event statement mentioned 18 organizer resumes, but those files were not available in the supplied Downloads folder. The multi-upload flow is ready for them.
- Tailor `CONCEPTS` before the final demo if the provided JD uses specialist technologies not in the initial map.
