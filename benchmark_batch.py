import io
import time
import zipfile
from pypdf import PdfReader

import app

JD_TEXT = """TechNova Solutions
Junior Full Stack Developer Intern | Bengaluru (Hybrid) | 6-Month Internship

KEY RESPONSIBILITIES
Develop and maintain web application features using React (frontend) and Node.js/Express (backend)
Design and consume REST APIs; work with relational and NoSQL databases
Write clean, tested, and maintainable code; participate in code reviews
Collaborate with designers and product managers in an agile/scrum environment
Debug and resolve issues reported by QA and users

MUST-HAVE SKILLS
Proficiency in JavaScript (ES6+) and at least one modern frontend framework (React preferred)
Experience building backend services with Node.js and Express
Working knowledge of REST APIs and JSON
Familiarity with SQL or NoSQL databases (MySQL, PostgreSQL, MongoDB)
Version control experience with Git/GitHub
Degree in Computer Science, IT, or a related field

GOOD-TO-HAVE SKILLS
TypeScript
Cloud basics (AWS/GCP/Azure)
Testing frameworks (Jest, Mocha)
Docker / basic containerization
Exposure to Agile/Scrum practices
"""

with open("C:/Users/bharg/Downloads/Bhargav_Resume.docx", "rb") as f:
    BASE_DOCX_BYTES = f.read()


def make_clean_pdf(name: str, text: str) -> bytes:
    stream = f"""BT
/F1 14 Tf
50 750 Td
({name}) Tj
0 -22 Td
/F1 10 Tf
({text[:120]}) Tj
0 -18 Td
({text[120:240]}) Tj
0 -18 Td
({text[240:360]}) Tj
ET""".replace("\n", "\r\n")
    stream_bytes = stream.encode("latin1")

    obj1 = b"1 0 obj\r\n<< /Type /Catalog /Pages 2 0 R >>\r\nendobj\r\n"
    obj2 = b"2 0 obj\r\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\r\nendobj\r\n"
    obj3 = b"3 0 obj\r\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\r\nendobj\r\n"
    obj4 = f"4 0 obj\r\n<< /Length {len(stream_bytes)} >>\r\nstream\r\n".encode("latin1") + stream_bytes + b"\r\nendstream\r\nendobj\r\n"
    obj5 = b"5 0 obj\r\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\r\nendobj\r\n"

    header = b"%PDF-1.4\r\n"
    offsets = [0]
    curr = len(header)
    for obj in [obj1, obj2, obj3, obj4, obj5]:
        offsets.append(curr)
        curr += len(obj)

    xref_pos = curr
    xref = b"xref\r\n0 6\r\n0000000000 65535 f \r\n"
    for o in offsets[1:]:
        xref += f"{o:010d} 00000 n \r\n".encode("latin1")
    trailer = f"trailer\r\n<< /Size 6 /Root 1 0 R >>\r\nstartxref\r\n{xref_pos}\r\n%%EOF\r\n".encode("latin1")

    return header + obj1 + obj2 + obj3 + obj4 + obj5 + xref + trailer


def make_docx(name: str, skills_and_exp: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(BASE_DOCX_BYTES), "r") as zin:
        xml = zin.read("word/document.xml").decode("utf-8")
        injected = f"<w:p><w:r><w:t>CANDIDATE: {name} - {skills_and_exp}</w:t></w:r></w:p></w:body>"
        xml = xml.replace("</w:body>", injected)
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "word/document.xml":
                    zout.writestr(item, xml.encode("utf-8"))
                else:
                    zout.writestr(item, zin.read(item.filename))
        bio.seek(0)
        return bio.getvalue()


def build_test_batch() -> list[tuple[io.BytesIO, str]]:
    candidates_meta = [
        ("Aarav Sharma", "Senior Full Stack Dev. React, Node.js, Express REST API, PostgreSQL, MongoDB, Git, Jest testing, Docker, AWS."),
        ("Maya Iyer", "Frontend Specialist. React, JavaScript ES6, HTML, CSS, REST APIs, JSON, Git, Jest testing."),
        ("Rohan Mehta", "Backend Engineer. Node.js, Express, PostgreSQL, MySQL, REST API, JSON, Docker, Git version control."),
        ("Priya Nair", "Full Stack Intern. JavaScript, React, Node.js, Express, MongoDB, Git, Agile, Scrum sprints."),
        ("Dev Patel", "Data Analyst and Backend. Python, SQL, REST APIs, Git, Docker, MongoDB databases, statistics."),
        ("Kavita Rao", "UI/UX Developer. HTML, CSS, JavaScript, React, responsive design, Git, communication."),
        ("Suresh Kumar", "Software Engineer. JavaScript, TypeScript, Node.js, Express, Jest, Mocha, Git, AWS cloud."),
        ("Ananya Das", "Computer Science Student. JavaScript, React, Node.js, Express, REST APIs, Git, PostgreSQL."),
        ("Vikram Malhotra", "Cloud Engineer. Docker, AWS, GCP, Azure, Python, Git, CI/CD pipelines, Kubernetes."),
        ("Sneha Joshi", "QA Engineer. Testing, Jest, Mocha, pytest, JavaScript, Git, bug reporting, Jira, Agile."),
        ("Arjun Reddy", "Full Stack. JavaScript, React, Node.js, MongoDB, Git, REST APIs, JSON, Agile teamwork."),
        ("Divya Menon", "Web Developer. React, JavaScript, CSS, HTML, REST APIs, Git, Tailwind, Figma."),
        ("Aditya Verma", "Backend Developer. Node.js, Express, PostgreSQL, REST APIs, JSON, Git, Docker."),
        ("Pooja Hegde", "DevOps and Cloud Intern. AWS, Docker, Git, Linux, Python scripting, containerization."),
        ("Karan Singhania", "Frontend Engineer. JavaScript, React, TypeScript, Redux, Jest, Git, HTML, CSS."),
        ("Tanvi Bhatia", "Intern. JavaScript, React, Node.js, Express, MongoDB, Git, agile development."),
        ("Nikhil Desai", "Full Stack Developer. React, Node.js, Express, REST APIs, JSON, PostgreSQL, Docker, Git."),
        ("Rhea Pillai", "Software Intern. JavaScript, Python, SQL, Git, testing, data structures, communication."),
    ]

    files = []
    for idx, (name, text) in enumerate(candidates_meta):
        safe_name = name.replace(" ", "_")
        if idx % 2 == 0:
            pdf_bytes = make_clean_pdf(name, text)
            files.append((io.BytesIO(pdf_bytes), f"{safe_name}.pdf"))
        else:
            docx_bytes = make_docx(name, text)
            files.append((io.BytesIO(docx_bytes), f"{safe_name}.docx"))
    return files


def run_benchmark():
    print("=" * 75)
    print("RESUME RANKER PERFORMANCE BENCHMARK (18 RESUMES: 9 PDF + 9 DOCX)")
    print("=" * 75)

    client = app.app.test_client()

    # 1. Warmup check
    print("\n--- 1. Testing /api/warmup Endpoint ---")
    t0 = time.perf_counter()
    warmup_res = client.post("/api/warmup")
    t_warmup = time.perf_counter() - t0
    warmup_data = warmup_res.get_json()
    print(f"Status: {warmup_res.status_code}")
    print(f"Warmup response: {warmup_data}")
    print(f"Warmup roundtrip: {t_warmup:.4f} s")

    # 2. First realistic batch request (Warm model, after warmup)
    print("\n--- 2. Request 1: 18-Resume Batch (9 PDF + 9 DOCX) ---")
    batch_files_1 = build_test_batch()
    data_1 = {
        "jd": JD_TEXT,
        "resumes": batch_files_1,
        "semantic_weight": "55",
    }
    t_req1_start = time.perf_counter()
    res1 = client.post("/api/rank", data=data_1, content_type="multipart/form-data")
    t_req1_total = time.perf_counter() - t_req1_start
    json1 = res1.get_json()
    print(f"Status: {res1.status_code}")
    print(f"Candidates ranked: {len(json1.get('results', []))}")
    print(f"Duplicates removed: {json1.get('duplicates_removed', [])}")
    print(f"Semantic Engine: {json1.get('semantic_engine')}")
    print("Server-reported timings:")
    for k, v in json1.get("timings", {}).items():
        print(f"  - {k}: {v:.4f} s")
    print(f"Client-measured wall time: {t_req1_total:.4f} s")

    # 3. Second realistic batch request (Warm cache in same process)
    print("\n--- 3. Request 2: 18-Resume Batch (Warm Cache In-Process) ---")
    batch_files_2 = build_test_batch()
    data_2 = {
        "jd": JD_TEXT,
        "resumes": batch_files_2,
        "semantic_weight": "55",
    }
    t_req2_start = time.perf_counter()
    res2 = client.post("/api/rank", data=data_2, content_type="multipart/form-data")
    t_req2_total = time.perf_counter() - t_req2_start
    json2 = res2.get_json()
    print(f"Status: {res2.status_code}")
    print("Server-reported timings:")
    for k, v in json2.get("timings", {}).items():
        print(f"  - {k}: {v:.4f} s")
    print(f"Client-measured wall time: {t_req2_total:.4f} s")

    # 4. Third realistic batch request (Confirm consistency)
    print("\n--- 4. Request 3: 18-Resume Batch (Warm Cache In-Process) ---")
    batch_files_3 = build_test_batch()
    data_3 = {
        "jd": JD_TEXT,
        "resumes": batch_files_3,
        "semantic_weight": "55",
    }
    t_req3_start = time.perf_counter()
    res3 = client.post("/api/rank", data=data_3, content_type="multipart/form-data")
    t_req3_total = time.perf_counter() - t_req3_start
    json3 = res3.get_json()
    print(f"Status: {res3.status_code}")
    print("Server-reported timings:")
    for k, v in json3.get("timings", {}).items():
        print(f"  - {k}: {v:.4f} s")
    print(f"Client-measured wall time: {t_req3_total:.4f} s")

    print("\n" + "=" * 75)
    print("BENCHMARK COMPLETED SUCCESSFULLY")
    print("=" * 75)


if __name__ == "__main__":
    run_benchmark()
