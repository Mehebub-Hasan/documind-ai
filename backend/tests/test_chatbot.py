from chatbot import build_context_from_chunks, format_chunk_source


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
