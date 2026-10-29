import pytest

from chatbot import (
    NOT_FOUND_ANSWER,
    SYSTEM_PROMPT,
    answer_question_with_deepseek,
    build_context_from_chunks,
    format_chunk_source,
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
        assert "Do not use the sentence from" in SYSTEM_PROMPT

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
