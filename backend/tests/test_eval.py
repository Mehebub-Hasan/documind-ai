import json

import pytest

from eval.metrics import (
    JudgeError,
    _clamp_score,
    _parse_judge_json,
    score_answer_relevance,
    score_context_relevance,
    score_groundedness,
)
from eval.runner import aggregate_results, render_table


class _FakeJudgeClient:
    """DeepSeek stand-in returning a canned completion."""

    def __init__(self, content):
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message})()
        self._response = type("R", (), {"choices": [choice]})()
        self.chat = type("Chat", (), {"completions": self})()
        self.captured = None

    def create(self, **kwargs):
        self.captured = kwargs
        return self._response


CHUNKS = [
    {"page": 2, "text": "Readings were logged every five minutes for 72 hours."},
    {"page": 3, "text": "The mean absolute error was 2.3 percentage points."},
]


@pytest.fixture
def fake_judge(monkeypatch):
    def _install(content):
        client = _FakeJudgeClient(content)
        monkeypatch.setattr("eval.metrics.get_deepseek_client", lambda: client)
        return client

    return _install


class TestParseJudgeJson:

    def test_plain_json(self):
        assert _parse_judge_json('{"score": 0.5}') == {"score": 0.5}

    def test_code_fenced_json(self):
        assert _parse_judge_json('```json\n{"score": 1}\n```') == {"score": 1}

    def test_unparseable_raises_judge_error(self):
        with pytest.raises(JudgeError):
            _parse_judge_json("no json here")

    def test_non_object_raises_judge_error(self):
        with pytest.raises(JudgeError):
            _parse_judge_json("[1, 2, 3]")


class TestClampScore:

    def test_bounds_and_coercion(self):
        assert _clamp_score(1.5) == 1.0
        assert _clamp_score(-0.2) == 0.0
        assert _clamp_score("0.75") == 0.75
        assert _clamp_score(None) == 0.0
        assert _clamp_score("garbage") == 0.0


class TestScoreFunctions:

    def test_context_relevance_happy_path(self, fake_judge):
        client = fake_judge('{"score": 0.9, "reasoning": "Directly relevant."}')

        result = score_context_relevance("How long was logging?", CHUNKS)

        assert result == {"score": 0.9, "reasoning": "Directly relevant."}
        sent = client.captured["messages"][1]["content"]
        assert "How long was logging?" in sent
        assert "five minutes" in sent  # chunk text included
        assert client.captured["response_format"] == {"type": "json_object"}

    def test_groundedness_reports_hallucinated_claims(self, fake_judge):
        fake_judge(
            json.dumps(
                {
                    "score": 0.5,
                    "hallucinated_claims": ["The sensor costs $40."],
                    "reasoning": "One claim unsupported.",
                }
            )
        )

        result = score_groundedness(CHUNKS, "MAE was 2.3 points. The sensor costs $40.")

        assert result["score"] == 0.5
        assert result["hallucinated_claims"] == ["The sensor costs $40."]

    def test_groundedness_tolerates_missing_claim_list(self, fake_judge):
        fake_judge('{"score": 1.0}')

        result = score_groundedness(CHUNKS, "Refusal answer.")

        assert result["hallucinated_claims"] == []
        assert result["score"] == 1.0

    def test_answer_relevance_passes_expected_refusal_note(self, fake_judge):
        client = fake_judge('{"score": 1.0, "reasoning": "Clear refusal."}')

        score_answer_relevance(
            "What was the budget?", "I cannot find this information.",
            expected_refusal=True,
        )

        assert "intentionally unanswerable" in client.captured["messages"][1]["content"]

    def test_missing_api_key_raises_judge_error(self, monkeypatch):
        monkeypatch.setattr("eval.metrics.get_deepseek_client", lambda: None)

        with pytest.raises(JudgeError):
            score_answer_relevance("q", "a")

    def test_api_failure_raises_judge_error(self, monkeypatch):
        class _Broken:
            def __init__(self):
                self.chat = type("C", (), {"completions": self})()

            def create(self, **kwargs):
                raise RuntimeError("api down")

        monkeypatch.setattr("eval.metrics.get_deepseek_client", lambda: _Broken())

        with pytest.raises(JudgeError):
            score_answer_relevance("q", "a")


class TestAggregateAndRender:

    def test_aggregate_averages_only_scored_cases(self):
        results = [
            {
                "metrics": {
                    "context_relevance": {"score": 0.8},
                    "groundedness": {"score": 1.0},
                    "answer_relevance": {"score": 0.6},
                }
            },
            {
                "metrics": {
                    "context_relevance": {"score": 0.4},
                    "groundedness": {"error": "judge down"},
                    "answer_relevance": {"score": 0.8},
                }
            },
        ]

        aggregates = aggregate_results(results)

        assert aggregates["context_relevance"]["average_score"] == 0.6
        assert aggregates["context_relevance"]["cases_scored"] == 2
        assert aggregates["groundedness"]["average_score"] == 1.0  # 1 case only
        assert aggregates["groundedness"]["cases_scored"] == 1

    def test_aggregate_handles_no_scores(self):
        aggregates = aggregate_results(
            [{"metrics": {"context_relevance": {"error": "down"}}}]
        )

        assert aggregates["context_relevance"]["average_score"] is None

    def test_render_table_shows_scores_and_errors(self):
        results = [
            {
                "id": "direct-01",
                "category": "direct_extraction",
                "refusal_detected": False,
                "metrics": {
                    "context_relevance": {"score": 0.9},
                    "groundedness": {"score": 1.0},
                    "answer_relevance": {"score": 0.8},
                },
            },
            {
                "id": "out-of-scope-01",
                "category": "unanswerable",
                "refusal_detected": True,
                "metrics": {
                    "context_relevance": {"error": "judge down"},
                    "groundedness": {"score": 1.0},
                    "answer_relevance": {"score": 1.0},
                },
            },
        ]
        aggregates = aggregate_results(results)

        table = render_table(results, aggregates)

        assert "direct-01" in table
        assert "out-of-scope-01" in table
        assert "ERR" in table  # failed judge visible
        assert "AVERAGE" in table


# ---------------------------------------------------------------------------
# Part 3: golden dataset, deterministic checks, regression gates
# ---------------------------------------------------------------------------

import json as json_module
from pathlib import Path

from eval.benchmark_documents import build_document_bytes
from eval.runner import (
    case_checks,
    citations_ok,
    evaluate_gates,
    facts_matched_ratio,
    normalize_case,
    sources_to_ranges,
)

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
GOLDEN = json_module.loads(
    (EVAL_DIR / "golden_dataset.json").read_text(encoding="utf-8")
)
VALID_CATEGORIES = {"direct_fact", "multi_chunk", "unanswerable", "citation_integrity"}


class TestGoldenDatasetSchema:

    def test_has_fifteen_unique_cases(self):
        cases = GOLDEN["cases"]
        assert len(cases) == 15
        assert len({case["id"] for case in cases}) == 15

    def test_categories_are_valid_and_balanced(self):
        categories = {case["category"] for case in GOLDEN["cases"]}
        assert categories <= VALID_CATEGORIES
        assert "direct_fact" in categories
        assert "multi_chunk" in categories
        assert "unanswerable" in categories
        assert "citation_integrity" in categories

    def test_answerable_cases_carry_facts_and_citations(self):
        for case in GOLDEN["cases"]:
            if case["category"] == "unanswerable":
                assert case["allow_refusal"] is True, case["id"]
                assert case["expected_facts"] == [], case["id"]
            else:
                assert case["allow_refusal"] is False, case["id"]
                assert case["expected_facts"], case["id"]
                assert case["expected_citations"], case["id"]

    def test_document_key_is_registered(self):
        filename, content, content_type = build_document_bytes(GOLDEN["document"])
        assert filename.endswith(".docx")
        assert content[:2] == b"PK"  # a real zip container (docx)
        assert "wordprocessingml" in content_type

    def test_expected_citation_ranges_are_well_formed(self):
        import re as re_module

        for case in GOLDEN["cases"]:
            for citation in case["expected_citations"]:
                assert re_module.fullmatch(
                    r"Blocks? \d+(-\d+)?", citation
                ), (case["id"], citation)


class TestDeterministicChecks:

    def test_facts_matched_ratio_perfect_and_partial(self):
        answer = "The mux selects one of four data inputs and routes it to the output."

        assert facts_matched_ratio(
            ["Selects one of four data inputs"], answer
        ) == 1.0
        # Paraphrase-tolerant but not omniscient:
        ratio = facts_matched_ratio(
            ["Uses the 74HC153 chip", "Selects one of four data inputs"], answer
        )
        assert ratio == 0.5

    def test_facts_matched_ratio_empty_facts_is_one(self):
        assert facts_matched_ratio([], "anything") == 1.0

    def test_sources_to_ranges_handles_both_source_types(self):
        assert sources_to_ranges([2, 3]) == [(2, 2), (3, 3)]
        assert sources_to_ranges(["blocks 4-9", "block 7"]) == [(4, 9), (7, 7)]

    def test_citations_ok_overlap_semantics(self):
        sources = ["blocks 4-9"]

        assert citations_ok(["Blocks 5-6"], sources) is True  # inside
        assert citations_ok(["Blocks 1-3"], sources) is False  # disjoint
        assert citations_ok(["Blocks 4-12"], sources) is True  # overlap
        assert citations_ok([], sources) is None  # not applicable

    def test_citations_ok_page_sources(self):
        assert citations_ok(["Page 2"], [1, 2, 3]) is True
        assert citations_ok(["Page 7"], [1, 2, 3]) is False

    def test_case_checks_refusal_semantics(self):
        refused = {"refusal_detected": True, "sources": [], "answer": "I cannot find this information in the provided document."}
        answered = {"refusal_detected": False, "sources": ["blocks 4-9"], "answer": "It uses the 74HC153 [Blocks 4-9]."}

        assert case_checks(normalize_case({"id": "u", "question": "q", "allow_refusal": True}), refused)["refusal_ok"] is True
        assert case_checks(normalize_case({"id": "u", "question": "q", "allow_refusal": True}), answered)["refusal_ok"] is False
        assert case_checks(normalize_case({"id": "a", "question": "q", "allow_refusal": False}), answered)["refusal_ok"] is True
        assert case_checks(normalize_case({"id": "a", "question": "q", "allow_refusal": False}), refused)["refusal_ok"] is False

    def test_normalize_case_maps_legacy_schema(self):
        legacy = normalize_case(
            {"id": "x", "category": "c", "question": "q", "expected_refusal": True}
        )
        assert legacy["allow_refusal"] is True
        assert legacy["top_k"] == 6


class TestEvaluateGates:

    def _aggregates(self, ctx=0.9, ground=0.9, ans=0.9):
        return {
            "context_relevance": {"average_score": ctx, "cases_scored": 5},
            "groundedness": {"average_score": ground, "cases_scored": 5},
            "answer_relevance": {"average_score": ans, "cases_scored": 5},
        }

    def test_clean_run_passes(self):
        failures = evaluate_gates(
            self._aggregates(), [], {"min_groundedness": 0.8, "min_answer_relevance": 0.7, "min_context_relevance": 0.5}
        )
        assert failures == []

    def test_groundedness_regression_fails(self):
        failures = evaluate_gates(
            self._aggregates(ground=0.6), [], {"min_groundedness": 0.8}
        )
        assert len(failures) == 1
        assert "min_groundedness" in failures[0]

    def test_per_case_check_failures_listed(self):
        results = [
            {"id": "tc_03", "allow_refusal": False, "refusal_detected": True, "checks": {"refusal_ok": False, "citations_ok": None}},
            {"id": "tc_10", "allow_refusal": False, "refusal_detected": False, "checks": {"refusal_ok": True, "citations_ok": False}},
        ]

        failures = evaluate_gates(self._aggregates(), results, {"min_groundedness": 0.8})

        assert any("tc_03" in f and "refusal" in f for f in failures)
        assert any("tc_10" in f and "citation" in f for f in failures)

    def test_missing_scores_do_not_crash_gates(self):
        aggregates = {key: {"average_score": None, "cases_scored": 0} for key in
                      ("context_relevance", "groundedness", "answer_relevance")}

        assert evaluate_gates(aggregates, [], {"min_groundedness": 0.8}) == []


class TestRefusalDetection:

    def test_prefix_match_allows_elaboration(self):
        from chatbot import NOT_FOUND_ANSWER, is_refusal_answer

        assert is_refusal_answer(
            NOT_FOUND_ANSWER + " It describes three lab circuits [Blocks 1-12]."
        )
        assert is_refusal_answer(
            "  I cannot find this information in the provided document."
        )
        assert not is_refusal_answer(
            "The multiplexer was implemented with the 74HC153."
        )
        assert not is_refusal_answer("")

    def test_judge_confirmed_refusal_fallback(self):
        pipeline = {"refusal_detected": False, "sources": ["blocks 1-12"], "answer": "The document does not mention..."}
        case = normalize_case({"id": "u", "question": "q", "allow_refusal": True})

        # No metrics yet: cannot confirm -> fail.
        assert case_checks(case, pipeline)["refusal_ok"] is False

        # Judges confirm a safe refusal in the model's own words.
        metrics = {
            "groundedness": {"score": 1.0, "hallucinated_claims": []},
            "answer_relevance": {"score": 0.9},
        }
        assert case_checks(case, pipeline, metrics)["refusal_ok"] is True

        # A hallucinated answer is never confirmed as a refusal.
        bad_metrics = {
            "groundedness": {"score": 0.5, "hallucinated_claims": ["invented"]},
            "answer_relevance": {"score": 0.9},
        }
        assert case_checks(case, pipeline, bad_metrics)["refusal_ok"] is False
