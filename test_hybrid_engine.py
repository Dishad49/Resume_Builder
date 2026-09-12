import unittest
import json
import app

TECHNOVA_JD = """TechNova Solutions
Junior Full Stack Developer Intern  |  Bengaluru (Hybrid)  |  6-Month Internship

ABOUT THE ROLE
TechNova Solutions is looking for a Junior Full Stack Developer Intern to join our product engineering team.
You will work closely with senior developers to build and ship features for our internal SaaS product,
contributing across the frontend and backend of the application.

KEY RESPONSIBILITIES
Develop and maintain web application features using React (frontend) and Node.js/Express (backend)
Design and consume REST APIs; work with relational and NoSQL databases
Write clean, tested, and maintainable code; participate in code reviews
Collaborate with designers and product managers in an agile/scrum environment
Debug and resolve issues reported by QA and users

MUST-HAVE SKILLS
Proficiency in JavaScript (ES6+) and at least one modern frontend framework (React preferred)
Experience building backend services with Node.js and Express (or similar)
Working knowledge of REST APIs and JSON
Familiarity with SQL or NoSQL databases (MySQL, PostgreSQL, MongoDB)
Version control experience with Git/GitHub
Pursuing or holding a degree in Computer Science, IT, or a related field

GOOD-TO-HAVE SKILLS
TypeScript
Cloud basics (AWS/GCP/Azure)
Testing frameworks (Jest, Mocha)
Docker / basic containerization
Prior internship or personal projects deployed live
Exposure to Agile/Scrum practices

SOFT SKILLS
Strong problem-solving ability, clear communication, willingness to learn new tools quickly, and comfort working
in a fast-paced, collaborative team environment."""


class TestHybridEngine(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.jd, self.candidates = app.sample_data()

    def test_dense_semantic_scores(self):
        scores = app.semantic_scores(self.jd, [c["text"] for c in self.candidates])
        self.assertEqual(len(scores), len(self.candidates))
        for score in scores:
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)
        # Verify relative ranking for obvious matches
        self.assertGreater(scores[0], scores[-1])

    def test_tfidf_fallback(self):
        scores = app.tfidf_semantic_scores(self.jd, [c["text"] for c in self.candidates])
        self.assertEqual(len(scores), len(self.candidates))
        for score in scores:
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_fallback_when_model_is_none(self):
        orig_model = app._EMBEDDING_MODEL
        orig_init = app._EMBEDDING_INITIALIZED
        try:
            app._EMBEDDING_MODEL = None
            app._EMBEDDING_INITIALIZED = True
            scores = app.semantic_scores(self.jd, [c["text"] for c in self.candidates])
            self.assertEqual(len(scores), len(self.candidates))
            for score in scores:
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)
        finally:
            app._EMBEDDING_MODEL = orig_model
            app._EMBEDDING_INITIALIZED = orig_init

    def test_rank_function(self):
        results = app.rank(self.jd, self.candidates)
        self.assertEqual(len(results), len(self.candidates))
        ranks = [r["rank"] for r in results]
        self.assertEqual(ranks, list(range(1, len(self.candidates) + 1)))
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # Ensure new missing_must_have and missing_good_to_have fields exist
        for r in results:
            self.assertIn("missing_must_have", r)
            self.assertIn("missing_good_to_have", r)
            self.assertIn("missing", r)

    def test_api_sample_endpoint(self):
        res = self.client.post("/api/sample")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("results", data)
        self.assertIn("semantic_engine", data)
        self.assertIn("all-MiniLM-L6-v2", data["semantic_engine"])

    def test_api_compare_endpoint(self):
        results = app.rank(self.jd, self.candidates)
        res = self.client.post("/api/compare", json={"a": results[0], "b": results[1]})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("headline", data)
        self.assertIn("skills", data)
        self.assertIn("experience", data)
        self.assertIn("scores", data)

    def test_concept_aliases(self):
        # 1. JSON under rest api
        hits_json = app.concepts_in("Strong experience with JSON structures.")
        self.assertIn("rest api", hits_json)
        # 2. Mocha under testing
        hits_mocha = app.concepts_in("Unit testing with Mocha framework.")
        self.assertIn("testing", hits_mocha)
        # 3. Docker under containerization (not cloud)
        hits_docker = app.concepts_in("Container setup using Docker.")
        self.assertIn("containerization", hits_docker)
        self.assertNotIn("cloud", hits_docker)

    def test_technova_section_splitting(self):
        # 5(a): Section splitting correctly separates must-have/good-to-have text
        sections = app.split_jd_sections(TECHNOVA_JD)
        self.assertIn("must_have", sections)
        self.assertIn("good_to_have", sections)
        self.assertIn("other", sections)
        self.assertIn("JavaScript", sections["must_have"])
        self.assertIn("React", sections["must_have"])
        self.assertIn("TypeScript", sections["good_to_have"])
        self.assertIn("Docker", sections["good_to_have"])

        must_c = app.concepts_in(sections["must_have"])
        good_c = app.concepts_in(sections["good_to_have"]) - must_c

        # Expected must-haves: javascript, react, node.js, rest api (JSON), databases, git
        expected_must = {"javascript", "react", "node.js", "rest api", "databases", "git"}
        self.assertTrue(expected_must.issubset(must_c))

        # Expected good-to-haves: typescript, cloud, testing (Mocha), containerization (Docker), agile
        expected_good = {"typescript", "cloud", "testing", "containerization", "agile"}
        self.assertTrue(expected_good.issubset(good_c))

    def test_must_have_penalty_greater_than_good_to_have(self):
        # 5(b): Resume missing a must-have skill scores lower than one missing only a good-to-have skill
        # Base technical stack with all must-have concepts:
        # (javascript, react, node.js, rest api / json, databases, git)
        # Plus all good-to-have concepts:
        # (typescript, cloud / aws, testing / jest, containerization / docker, agile / scrum)

        # Resume A: Has everything EXCEPT must-have "node.js"
        resume_missing_must = (
            "Software engineer with JavaScript, TypeScript, React frontend, REST API, JSON, "
            "MySQL database, Git, AWS cloud, Jest testing, Docker containers, Agile Scrum sprints."
        )

        # Resume B: Has everything EXCEPT good-to-have "containerization / docker"
        resume_missing_good = (
            "Software engineer with JavaScript, TypeScript, React frontend, Node.js, Express, REST API, JSON, "
            "MySQL database, Git, AWS cloud, Jest testing, Agile Scrum sprints."
        )

        score_missing_must, matched_a, missing_must_a, missing_good_a = app.keyword_score(TECHNOVA_JD, resume_missing_must)
        score_missing_good, matched_b, missing_must_b, missing_good_b = app.keyword_score(TECHNOVA_JD, resume_missing_good)

        self.assertIn("node.js", missing_must_a)
        self.assertEqual(missing_must_b, [])
        self.assertIn("containerization", missing_good_b)

        # Resume missing must-have skill MUST score lower than one missing only a good-to-have skill
        self.assertLess(score_missing_must, score_missing_good)

    def test_fallback_no_headers_found(self):
        # 5(c): The fallback (no headers found) doesn't crash or return empty concept sets
        no_header_jd = (
            "Junior Full Stack Developer Intern. Build responsive web features using JavaScript, React and Node.js. "
            "Work with REST APIs and SQL or MongoDB databases. Familiarity with Git, HTML, CSS, testing and agile teamwork is preferred."
        )
        sections = app.split_jd_sections(no_header_jd)
        self.assertEqual(sections["must_have"], no_header_jd.strip())
        self.assertEqual(sections["good_to_have"], "")

        # Test concepts_in on fallback must_have
        must_c = app.concepts_in(sections["must_have"])
        self.assertGreater(len(must_c), 0)
        self.assertIn("javascript", must_c)
        self.assertIn("react", must_c)

        # Test keyword_score on fallback doesn't crash and returns valid results
        score, matched, missing_must, missing_good = app.keyword_score(no_header_jd, "Experienced React and Node.js developer.")
        self.assertGreater(score, 0.0)
        self.assertIn("react", matched)
        self.assertIn("node.js", matched)
        self.assertEqual(missing_good, [])


if __name__ == "__main__":
    unittest.main()

