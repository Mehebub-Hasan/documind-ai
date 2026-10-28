from chunker import (
    clean_text,
    chunk_text,
    create_chunks_from_pages,
    create_chunks_from_units,
)


class TestCleanText:

    def test_collapses_whitespace(self):
        assert clean_text("hello   world\n\ntest") == "hello world test"

    def test_joins_hyphenated_line_breaks(self):
        assert clean_text("docu-\nment") == "document"

    def test_empty(self):
        assert clean_text("") == ""
        assert clean_text(None) == ""


class TestChunkText:

    def test_overlap_between_chunks(self):
        text = "x" * 2000

        chunks = chunk_text(text, chunk_size=1000, overlap=200)

        assert [len(chunk) for chunk in chunks] == [1000, 1000, 400]
        assert chunks[1][:200] == chunks[0][800:1000]
        assert chunks[2][:200] == chunks[1][800:1000]

    def test_long_text_produces_overlap_tail_chunk(self):
        chunks = chunk_text("x" * 2500, chunk_size=1000, overlap=200)

        assert [len(chunk) for chunk in chunks] == [1000, 1000, 900, 100]

    def test_short_text_single_chunk(self):
        assert chunk_text("hello world", chunk_size=1000, overlap=200) == [
            "hello world"
        ]

    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []


class TestCreateChunksFromPages:

    def test_pdf_chunk_shape_matches_legacy_format(self):
        pages = [
            {"page": 1, "text": "x" * 2500},
            {"page": 2, "text": "y" * 300},
        ]

        chunks = create_chunks_from_pages(pages, chunk_size=1000, overlap=200)

        assert [chunk["chunk_id"] for chunk in chunks] == [
            "page_1_chunk_1",
            "page_1_chunk_2",
            "page_1_chunk_3",
            "page_1_chunk_4",
            "page_2_chunk_1",
        ]
        assert all(
            set(chunk.keys()) == {"chunk_id", "page", "text"} for chunk in chunks
        )
        assert [chunk["page"] for chunk in chunks] == [1, 1, 1, 1, 2]
        assert all(chunk["text"] for chunk in chunks)

    def test_empty_pages_produce_no_chunks(self):
        assert create_chunks_from_pages([]) == []
        assert create_chunks_from_pages([{"page": 1, "text": ""}]) == []


class TestCreateChunksFromUnits:

    def test_metadata_passthrough_and_chunk_ids(self):
        units = [
            {
                "label": "blocks_4-9",
                "text": "x" * 1500,
                "meta": {"block_start": 4, "block_end": 9},
            },
            {
                "label": "block_12",
                "text": "y" * 100,
                "meta": {"block_start": 12, "block_end": 12},
            },
        ]

        chunks = create_chunks_from_units(units, chunk_size=1000, overlap=200)

        assert [chunk["chunk_id"] for chunk in chunks] == [
            "blocks_4-9_chunk_1",
            "blocks_4-9_chunk_2",
            "block_12_chunk_1",
        ]
        assert chunks[0]["block_start"] == 4
        assert chunks[0]["block_end"] == 9
        assert chunks[1]["block_start"] == 4
        assert chunks[2]["block_start"] == 12
        assert chunks[2]["block_end"] == 12
        assert all("page" not in chunk for chunk in chunks)
