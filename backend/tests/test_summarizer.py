import json

import pytest

import summarizer
from summarizer import (
    build_extractive_summary,
    generate_document_summary,
    generate_llm_summary,
    select_summary_chunks,
)


def pdf_chunks(count):
    return [
        {
            "chunk_id": f"page_{i}_chunk_0",
            "page": i + 1,
            "text": (
                f"Section {i + 1} covers topic number {i + 1} in detail. "
                "This second sentence adds context. A third sentence closes it out."
            ),
        }
        for i in range(count)
    ]


def docx_chunks(count):
    return [
        {
            "chunk_id": f"blocks_{i + 1}-{i + 3}_chunk_0",
            "block_start": i + 1,
            "block_end": i + 3,
            "text": f"Docx block group {i + 1} text. Another sentence here.",
        }
        for i in range(count)
    ]


class TestSelectSummaryChunks:

    def test_short_documents_keep_all_chunks(self):
        chunks = pdf_chunks(4)

        selected = select_summary_chunks(chunks, max_chunks=8)

        assert selected == chunks

    def test_long_documents_sample_evenly_with_first_and_last(self):
        chunks = pdf_chunks(30)

        selected = select_summary_chunks(chunks, max_chunks=8)

        assert len(selected) == 8
        assert selected[0]["page"] == 1
        assert selected[-1]["page"] == 30
        pages = [chunk["page"] for chunk in selected]
        assert pages == sorted(pages)


class TestExtractiveSummary:

    def test_overview_and_pdf_takeaways(self):
        summary = build_extractive_summary(pdf_chunks(5))

        assert summary["method"] == "extractive"
        assert summary["overview"].startswith("Section 1 covers topic number 1")
        assert len(summary["takeaways"]) == 3

        sources = [item["source"] for item in summary["takeaways"]]
        assert sources == ["Page 1", "Page 3", "Page 5"]

    def test_docx_takeaways_use_block_labels(self):
        summary = build_extractive_summary(docx_chunks(3))

        sources = [item["source"] for item in summary["takeaways"]]
        assert sources == ["Blocks 1-3", "Blocks 2-4", "Blocks 3-5"]

    def test_respects_length_caps(self):
        long_chunk = {
            "chunk_id": "page_1_chunk_0",
            "page": 1,
            "text": " ".join(f"sentence{i} with some padding words." for i in range(200)),
        }

        summary = build_extractive_summary([long_chunk])

        assert len(summary["overview"]) <= 340
        assert len(summary["takeaways"][0]["text"]) <= 220

    def test_single_chunk_yields_single_takeaway(self):
        summary = build_extractive_summary(pdf_chunks(1))

        assert len(summary["takeaways"]) == 1
        assert summary["takeaways"][0]["source"] == "Page 1"


class _FakeSummaryClient:
    def __init__(self, content):
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message})()
        self._response = type("R", (), {"choices": [choice]})()
        self.completions = self
        self.chat = self

    def create(self, **kwargs):
        self.captured = kwargs
        return self._response


def llm_payload(overview, takeaways):
    return json.dumps({"overview": overview, "takeaways": takeaways})


class TestLlmSummary:

    def test_valid_json_is_parsed_and_kept(self, monkeypatch):
        payload = llm_payload(
            "The report covers quarterly results.",
            [
                {"text": "Revenue grew.", "source": "Page 1"},
                {"text": "Costs fell.", "source": "Page 2"},
                {"text": "Outlook is stable.", "source": "Page 3"},
            ],
        )
        fake = _FakeSummaryClient(payload)
        monkeypatch.setattr("summarizer.get_deepseek_client", lambda: fake)

        summary = generate_llm_summary(pdf_chunks(3))

        assert summary["method"] == "llm"
        assert summary["overview"] == "The report covers quarterly results."
        assert [t["source"] for t in summary["takeaways"]] == [
            "Page 1", "Page 2", "Page 3",
        ]

    def test_takeaway_with_invented_source_is_dropped(self, monkeypatch):
        payload = llm_payload(
            "Overview.",
            [
                {"text": "Grounded point.", "source": "Page 1"},
                {"text": "Fabricated point.", "source": "Page 99"},
            ],
        )
        fake = _FakeSummaryClient(payload)
        monkeypatch.setattr("summarizer.get_deepseek_client", lambda: fake)

        summary = generate_llm_summary(pdf_chunks(3))

        assert [t["text"] for t in summary["takeaways"]] == ["Grounded point."]

    def test_code_fenced_json_is_handled(self, monkeypatch):
        payload = f"```json\n{llm_payload('Fenced overview.', [{'text': 'Point.', 'source': 'Page 1'}])}\n```"
        fake = _FakeSummaryClient(payload)
        monkeypatch.setattr("summarizer.get_deepseek_client", lambda: fake)

        summary = generate_llm_summary(pdf_chunks(1))

        assert summary["overview"] == "Fenced overview."

    def test_unparseable_output_returns_none(self, monkeypatch):
        fake = _FakeSummaryClient("not json at all")
        monkeypatch.setattr("summarizer.get_deepseek_client", lambda: fake)

        assert generate_llm_summary(pdf_chunks(2)) is None

    def test_api_failure_returns_none(self, monkeypatch):
        class _Boom:
            def create(self, **kwargs):
                raise RuntimeError("api down")

        class _Client:
            def __init__(self):
                self.completions = _Boom()
                self.chat = type("C", (), {"completions": self.completions})()

        monkeypatch.setattr("summarizer.get_deepseek_client", lambda: _Client())

        assert generate_llm_summary(pdf_chunks(2)) is None

    def test_no_client_returns_none(self, monkeypatch):
        monkeypatch.setattr("summarizer.get_deepseek_client", lambda: None)

        assert generate_llm_summary(pdf_chunks(2)) is None


class TestGenerateDocumentSummary:

    def test_falls_back_to_extractive_without_llm(self, monkeypatch):
        monkeypatch.setattr("summarizer.get_deepseek_client", lambda: None)

        summary = generate_document_summary(pdf_chunks(4))

        assert summary["method"] == "extractive"
        assert len(summary["takeaways"]) == 3

    def test_prefers_llm_when_available(self, monkeypatch):
        payload = llm_payload(
            "LLM overview.",
            [{"text": "Point.", "source": "Page 1"}],
        )
        fake = _FakeSummaryClient(payload)
        monkeypatch.setattr("summarizer.get_deepseek_client", lambda: fake)

        summary = generate_document_summary(pdf_chunks(2))

        assert summary["method"] == "llm"

    def test_empty_document_raises(self):
        with pytest.raises(ValueError):
            generate_document_summary([])
