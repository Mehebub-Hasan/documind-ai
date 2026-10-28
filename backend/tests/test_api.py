import main as main_module
from conftest import build_docx_bytes, make_user

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def upload(client, endpoint, filename, content, content_type, headers):
    return client.post(
        endpoint,
        files={"file": (filename, content, content_type)},
        headers=headers,
    )


class TestUploadPdf:

    def test_happy_path(self, client, pdf_bytes):
        user = make_user(client)

        response = upload(
            client, "/upload-pdf", "sample.pdf", pdf_bytes, PDF_CONTENT_TYPE, user["headers"]
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"].startswith("PDF uploaded")
        assert data["source_type"] == "pdf"
        assert data["document_id"]
        assert data["filename"] == "sample.pdf"
        assert data["summary"]["total_pages"] == 2
        assert data["summary"]["non_empty_pages"] == 2
        assert data["chunk_summary"]["total_chunks"] > 0
        assert (
            data["vector_index"]["total_chunks_indexed"]
            == data["chunk_summary"]["total_chunks"]
        )
        assert all(
            set(chunk.keys()) == {"chunk_id", "page", "text"}
            for chunk in data["sample_chunks"]
        )

    def test_rejects_docx_file(self, client, docx_bytes):
        user = make_user(client)

        response = upload(
            client, "/upload-pdf", "sample.docx", docx_bytes, DOCX_CONTENT_TYPE, user["headers"]
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Only PDF files are allowed."

    def test_rejects_missing_extension(self, client, pdf_bytes):
        user = make_user(client)

        response = upload(
            client, "/upload-pdf", "sample.txt", pdf_bytes, PDF_CONTENT_TYPE, user["headers"]
        )

        assert response.status_code == 400


class TestUploadDocx:

    def test_happy_path(self, client, docx_bytes):
        user = make_user(client)

        response = upload(
            client, "/upload-docx", "sample.docx", docx_bytes, DOCX_CONTENT_TYPE, user["headers"]
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"].startswith("DOCX uploaded")
        assert data["source_type"] == "docx"
        assert data["document_id"]
        assert data["summary"]["total_paragraphs"] == 3
        assert data["summary"]["total_tables"] == 1
        assert data["chunk_summary"]["total_chunks"] > 0
        assert (
            data["vector_index"]["total_chunks_indexed"]
            == data["chunk_summary"]["total_chunks"]
        )

        for chunk in data["sample_chunks"]:
            assert "block_start" in chunk
            assert "block_end" in chunk
            assert "page" not in chunk
            assert chunk["chunk_id"].startswith(("block_", "blocks_"))

    def test_rejects_pdf_file(self, client, pdf_bytes):
        user = make_user(client)

        response = upload(
            client, "/upload-docx", "sample.pdf", pdf_bytes, PDF_CONTENT_TYPE, user["headers"]
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Only .docx Word files are allowed."

    def test_rejects_legacy_doc_with_hint(self, client):
        user = make_user(client)

        response = upload(
            client, "/upload-docx", "legacy.doc", b"bytes", "application/msword", user["headers"]
        )

        assert response.status_code == 400
        assert "convert" in response.json()["detail"].lower()

    def test_rejects_corrupt_file(self, client):
        user = make_user(client)

        response = upload(
            client, "/upload-docx", "broken.docx", b"not a docx", DOCX_CONTENT_TYPE, user["headers"]
        )

        assert response.status_code == 422
        assert "valid .docx" in response.json()["detail"]

    def test_rejects_empty_document(self, client):
        user = make_user(client)
        empty_docx = build_docx_bytes()

        response = upload(
            client, "/upload-docx", "empty.docx", empty_docx, DOCX_CONTENT_TYPE, user["headers"]
        )

        assert response.status_code == 422
        assert response.json()["detail"] in {
            "No blocks were detected in the uploaded document.",
            "No readable text was extracted from the document.",
        }


class TestSearch:

    def test_pdf_results_carry_page_metadata(self, client, pdf_bytes):
        user = make_user(client)
        document_id = upload(
            client, "/upload-pdf", "sample.pdf", pdf_bytes, PDF_CONTENT_TYPE, user["headers"]
        ).json()["document_id"]

        response = client.post(
            "/search",
            json={"document_id": document_id, "question": "apple", "top_k": 2},
            headers=user["headers"],
        )

        assert response.status_code == 200
        results = response.json()["results"]
        assert results
        for result in results:
            assert set(result.keys()) == {"score", "chunk_id", "page", "text"}

    def test_docx_results_carry_block_metadata(self, client, docx_bytes):
        user = make_user(client)
        document_id = upload(
            client, "/upload-docx", "sample.docx", docx_bytes, DOCX_CONTENT_TYPE, user["headers"]
        ).json()["document_id"]

        response = client.post(
            "/search",
            json={"document_id": document_id, "question": "quarterly results", "top_k": 2},
            headers=user["headers"],
        )

        assert response.status_code == 200
        results = response.json()["results"]
        assert results
        for result in results:
            assert {"score", "chunk_id", "text", "block_start", "block_end"} == set(
                result.keys()
            )


class TestAsk:

    def test_pdf_sources_are_page_numbers(self, client, pdf_bytes, monkeypatch):
        user = make_user(client)
        document_id = upload(
            client, "/upload-pdf", "sample.pdf", pdf_bytes, PDF_CONTENT_TYPE, user["headers"]
        ).json()["document_id"]

        monkeypatch.setattr(
            main_module,
            "answer_question_with_deepseek",
            lambda question, retrieved_chunks: "Stub answer.",
        )

        response = client.post(
            "/ask",
            json={
                "document_id": document_id,
                "question": "What mentions apple?",
                "top_k": 3,
            },
            headers=user["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Stub answer."
        assert data["source_type"] == "pdf"
        assert data["sources"]
        assert all(isinstance(source, int) for source in data["sources"])
        assert all("page" in chunk for chunk in data["retrieved_chunks"])

    def test_docx_sources_are_block_ranges(self, client, docx_bytes, monkeypatch):
        user = make_user(client)
        document_id = upload(
            client, "/upload-docx", "sample.docx", docx_bytes, DOCX_CONTENT_TYPE, user["headers"]
        ).json()["document_id"]

        monkeypatch.setattr(
            main_module,
            "answer_question_with_deepseek",
            lambda question, retrieved_chunks: "Stub answer.",
        )

        response = client.post(
            "/ask",
            json={
                "document_id": document_id,
                "question": "What mentions apple?",
                "top_k": 3,
            },
            headers=user["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Stub answer."
        assert data["source_type"] == "docx"
        assert data["sources"] == ["blocks 1-4"]
        assert all("block_start" in chunk for chunk in data["retrieved_chunks"])

    def test_unknown_document_returns_404(self, client):
        user = make_user(client)

        response = client.post(
            "/ask",
            json={"document_id": "does-not-exist", "question": "hello"},
            headers=user["headers"],
        )

        assert response.status_code == 404


class TestDocumentLifecycle:

    def test_documents_listing_shows_source_type(self, client, pdf_bytes, docx_bytes):
        user = make_user(client)
        upload(client, "/upload-pdf", "a.pdf", pdf_bytes, PDF_CONTENT_TYPE, user["headers"])
        upload(client, "/upload-docx", "b.docx", docx_bytes, DOCX_CONTENT_TYPE, user["headers"])

        response = client.get("/documents", headers=user["headers"])

        assert response.status_code == 200
        data = response.json()
        assert data["total_documents"] == 2
        source_types = {doc["source_type"] for doc in data["documents"]}
        assert source_types == {"pdf", "docx"}

    def test_delete_document(self, client, docx_bytes):
        user = make_user(client)
        document_id = upload(
            client, "/upload-docx", "temp.docx", docx_bytes, DOCX_CONTENT_TYPE, user["headers"]
        ).json()["document_id"]

        response = client.delete(f"/documents/{document_id}", headers=user["headers"])

        assert response.status_code == 200
        assert (
            client.get("/documents", headers=user["headers"]).json()["total_documents"] == 0
        )
        assert (
            client.post(
                "/ask",
                json={"document_id": document_id, "question": "hello"},
                headers=user["headers"],
            ).status_code
            == 404
        )
