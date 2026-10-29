import pytest

from chatbot import (
    NOT_FOUND_ANSWER,
    SYSTEM_PROMPT,
    answer_question_with_deepseek,
    build_context_from_chunks,
    format_chunk_source,
    verify_attributions,
)


class TestFormatChunkSource:

    def test_pdf_page(self):
        assert format_chunk_source({"page": 3}) == "Page 3"

    def test_docx_block_range(self):
        assert format_chunk_source({"block_start": 4, "block_end": 9}) == "Blocks 4-9"

    def test_docx_single_block(self):
        assert format_chunk_source({"block_start": 7, "block_end": 7}) == "Block 7"

    def test_unknown(self):
        assert format_chunk_source({}) == "Unknown source"


class TestBuildContext:

    def test_pdf_and_docx_labels(self):
        context = build_context_from_chunks(
            [
                {"page": 2, "text": "pdf text"},
                {"block_start": 1, "block_end": 4, "text": "docx text"},
            ]
        )

        assert "[Page 2]\npdf text" in context
        assert "[Blocks 1-4]\ndocx text" in context
        assert "\n\n---\n\n" in context


class TestSystemPrompt:

    def test_scope_questions_get_topic_summary_rule(self):
        assert "overall scope" in SYSTEM_PROMPT
        assert "summarize the primary" in SYSTEM_PROMPT
        assert "not addressed in the document" in SYSTEM_PROMPT

    def test_not_found_is_gated_to_unrelated_questions(self):
        assert "completely unrelated to the document's subject matter" in (
            SYSTEM_PROMPT
        )

    def test_on_topic_but_missing_detail_forbids_canned_sentence(self):
        normalized = " ".join(SYSTEM_PROMPT.split())
        assert "do not reply with the sentence from rule 4" in normalized

    def test_canned_sentence_is_exact(self):
        assert NOT_FOUND_ANSWER in SYSTEM_PROMPT
        assert NOT_FOUND_ANSWER == (
            "The document does not contain enough information to answer this "
            "question."
        )


class _FakeMessage:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _FakeCompletions:
    def __init__(self):
        self.captured = None

    def create(self, **kwargs):
        self.captured = kwargs
        return type("R", (), {"choices": [_FakeMessage("fake answer")]})


class _FakeClient:
    def __init__(self):
        self.completions = _FakeCompletions()
        self.chat = type("C", (), {"completions": self.completions})()


class TestAnswerQuestion:

    def test_passes_system_prompt_context_and_question(self, monkeypatch):
        fake = _FakeClient()
        monkeypatch.setattr("chatbot.get_deepseek_client", lambda: fake)

        chunks = [{"page": 2, "text": "solar panels generate electricity"}]
        result = answer_question_with_deepseek("What is this about?", chunks)

        assert result == "fake answer"
        messages = fake.completions.captured["messages"]
        assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
        user_prompt = messages[1]["content"]
        assert "[Page 2]" in user_prompt
        assert "solar panels generate electricity" in user_prompt
        assert "What is this about?" in user_prompt

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.setattr("chatbot.get_deepseek_client", lambda: None)

        with pytest.raises(ValueError):
            answer_question_with_deepseek("anything", [{"page": 1, "text": "x"}])


PDF_CHUNKS = [
    {
        "chunk_id": "page_1_chunk_0",
        "page": 1,
        "text": "The EN pin accepts an input voltage of 3.3 volts.",
    },
    {
        "chunk_id": "page_2_chunk_0",
        "page": 2,
        "text": "Migration patterns bring zebra herds to the river crossing "
        "each survival season, where predators wait for the weakest animals.",
    },
]

DOCX_CHUNKS = [
    {
        "chunk_id": "blocks_4-9_chunk_0",
        "block_start": 4,
        "block_end": 9,
        "text": "The device is covered by a 24-month limited warranty from "
        "the original purchase date.",
    },
]


class TestVerifyAttributions:

    def test_valid_citations_are_kept_and_grounded(self):
        answer = (
            "The enable pin accepts 3.3 volts [Page 1]. Zebra herds reach "
            "the river crossing each season [Page 2]."
        )

        report = verify_attributions(answer, PDF_CHUNKS)

        assert report["grounded"] is True
        assert report["cleaned_answer"] == answer
        assert report["removed_citations"] == []
        assert report["flagged_sentences"] == []

    def test_hallucinated_page_reference_is_stripped(self):
        answer = "The chip runs at 100 MHz [Page 99]."

        report = verify_attributions(answer, PDF_CHUNKS)

        assert report["grounded"] is False
        assert report["removed_citations"] == ["[Page 99]"]
        assert "[Page 99]" not in report["cleaned_answer"]
        assert "100 MHz" in report["cleaned_answer"]  # text survives

    def test_hallucinated_block_range_is_stripped(self):
        answer = "Warranty details continue in [Blocks 50-60]."

        report = verify_attributions(answer, DOCX_CHUNKS)

        assert report["removed_citations"] == ["[Blocks 50-60]"]
        assert "[Blocks 50-60]" not in report["cleaned_answer"]

    def test_block_subset_of_retrieved_range_is_valid(self):
        answer = "The warranty runs 24 months from purchase [Blocks 5-6]."

        report = verify_attributions(answer, DOCX_CHUNKS)

        assert report["grounded"] is True
        assert "[Blocks 5-6]" in report["cleaned_answer"]

    def test_multi_page_tag_invalid_if_any_page_missing(self):
        answer = "Voltage and migration [Pages 1, 7]."

        report = verify_attributions(answer, PDF_CHUNKS)

        assert report["removed_citations"] == ["[Pages 1, 7]"]

    def test_genuine_quote_is_kept(self):
        answer = 'The document states "the EN pin accepts an input voltage" [Page 1].'

        report = verify_attributions(answer, PDF_CHUNKS)

        assert report["grounded"] is True
        assert report["unverified_quotes"] == []

    def test_fabricated_quote_is_flagged_and_unquoted(self):
        answer = (
            'The manual warns "dragons breathe fire on Mondays" about the '
            "pin [Page 1]."
        )

        report = verify_attributions(answer, PDF_CHUNKS)

        assert report["grounded"] is False
        assert report["unverified_quotes"] == [
            "dragons breathe fire on Mondays"
        ]
        assert '"' not in report["cleaned_answer"]

    def test_cited_sentence_without_context_support_is_flagged(self):
        # Every content token is unrelated to the retrieved chunks.
        answer = "Quantum flux drives the torpedo array [Page 1]."

        report = verify_attributions(answer, PDF_CHUNKS)

        assert report["grounded"] is False
        assert len(report["flagged_sentences"]) == 1
        assert "[Page 1]" not in report["cleaned_answer"]
        assert "Quantum flux drives" in report["cleaned_answer"]

    def test_morphological_variants_count_as_coverage(self):
        # "Zebras"/"herds"/"river" appear as "zebra"/"herd(s)"/"river" in
        # the chunk; the citation must survive.
        answer = "Zebras cross the river in herds [Page 2]."

        report = verify_attributions(answer, PDF_CHUNKS)

        assert report["grounded"] is True

    def test_empty_answer_is_a_noop(self):
        report = verify_attributions("   ", PDF_CHUNKS)

        assert report["grounded"] is True
        assert report["cleaned_answer"] == "   "

    def test_markdown_bullets_survive_verification(self):
        answer = (
            "Key points:\n- The EN pin accepts 3.3 volts [Page 1].\n"
            "- Unrelated claim about warp drives [Page 1]."
        )

        report = verify_attributions(answer, PDF_CHUNKS)

        cleaned = report["cleaned_answer"]
        assert "\n" in cleaned  # structure preserved
        assert "- The EN pin accepts 3.3 volts [Page 1]." in cleaned
        assert cleaned.strip().endswith("Unrelated claim about warp drives.")

    def test_quote_with_trailing_punctuation_inside_marks_is_kept(self):
        # Regression: the LLM quotes a real context phrase but includes the
        # sentence period inside the quotation marks.
        answer = (
            'Zebras reach the river crossing each survival season '
            '"where predators wait." [Page 2].'
        )

        report = verify_attributions(answer, PDF_CHUNKS)

        assert report["grounded"] is True
        assert report["unverified_quotes"] == []
