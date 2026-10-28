import uuid

import document_store
from conftest import make_user
from test_api import PDF_CONTENT_TYPE, upload


class TestRegistrationAndLogin:

    def test_register_returns_token_and_profile(self, client):
        response = client.post(
            "/auth/register",
            json={
                "email": "alice@example.com",
                "password": "Password123!",
                "name": "Alice",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["token"]
        assert data["user"]["email"] == "alice@example.com"
        assert data["user"]["name"] == "Alice"
        assert data["user"]["id"]
        assert "password" not in data["user"]
        assert "password_hash" not in str(data)

    def test_register_rejects_duplicate_email(self, client):
        payload = {
            "email": "duplicate@example.com",
            "password": "Password123!",
            "name": "First",
        }
        assert client.post("/auth/register", json=payload).status_code == 200

        response = client.post(
            "/auth/register",
            json={**payload, "name": "Second"},
        )

        assert response.status_code == 409

    def test_register_validates_input(self, client):
        bad_email = client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "Password123!", "name": "A"},
        )
        assert bad_email.status_code == 400

        short_password = client.post(
            "/auth/register",
            json={"email": "ok@example.com", "password": "short", "name": "A"},
        )
        assert short_password.status_code == 400

        empty_name = client.post(
            "/auth/register",
            json={"email": "ok@example.com", "password": "Password123!", "name": "  "},
        )
        assert empty_name.status_code == 400

    def test_login_success(self, client):
        client.post(
            "/auth/register",
            json={
                "email": "login@example.com",
                "password": "Password123!",
                "name": "Login User",
            },
        )

        response = client.post(
            "/auth/login",
            json={"email": "login@example.com", "password": "Password123!"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["token"]
        assert data["user"]["email"] == "login@example.com"

    def test_login_rejects_wrong_password(self, client):
        client.post(
            "/auth/register",
            json={
                "email": "login2@example.com",
                "password": "Password123!",
                "name": "Login User",
            },
        )

        response = client.post(
            "/auth/login",
            json={"email": "login2@example.com", "password": "WrongPassword!"},
        )

        assert response.status_code == 401

    def test_login_rejects_unknown_email(self, client):
        response = client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "Password123!"},
        )

        assert response.status_code == 401

    def test_auth_me_returns_profile(self, client):
        user = make_user(client)

        response = client.get("/auth/me", headers=user["headers"])

        assert response.status_code == 200
        assert response.json()["user"]["id"] == user["user"]["id"]

    def test_auth_me_rejects_invalid_token(self, client):
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer not-a-real-token"},
        )

        assert response.status_code == 401


class TestUnauthenticatedAccess:

    def test_upload_pdf_requires_auth(self, client, pdf_bytes):
        response = client.post(
            "/upload-pdf",
            files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 401

    def test_upload_docx_requires_auth(self, client):
        response = client.post(
            "/upload-docx",
            files={"file": ("sample.docx", b"x", "application/octet-stream")},
        )
        assert response.status_code == 401

    def test_documents_requires_auth(self, client):
        assert client.get("/documents").status_code == 401

    def test_ask_requires_auth(self, client):
        response = client.post(
            "/ask",
            json={"document_id": "any", "question": "hello"},
        )
        assert response.status_code == 401

    def test_search_requires_auth(self, client):
        response = client.post(
            "/search",
            json={"document_id": "any", "question": "hello"},
        )
        assert response.status_code == 401

    def test_messages_requires_auth(self, client):
        assert client.get("/documents/some-id/messages").status_code == 401

    def test_delete_requires_auth(self, client):
        assert client.delete("/documents/some-id").status_code == 401


class TestCrossUserIsolation:

    def test_documents_listing_only_shows_own_documents(self, client, pdf_bytes):
        user_a = make_user(client, email=f"a-{uuid.uuid4().hex[:8]}@example.com")
        user_b = make_user(client, email=f"b-{uuid.uuid4().hex[:8]}@example.com")

        upload(
            client,
            "/upload-pdf",
            "secret.pdf",
            pdf_bytes,
            PDF_CONTENT_TYPE,
            user_a["headers"],
        )

        listing_b = client.get("/documents", headers=user_b["headers"]).json()
        listing_a = client.get("/documents", headers=user_a["headers"]).json()

        assert listing_b["total_documents"] == 0
        assert listing_a["total_documents"] == 1

    def test_user_b_cannot_ask_search_view_or_delete_user_a_document(
        self, client, pdf_bytes
    ):
        user_a = make_user(client, email=f"a-{uuid.uuid4().hex[:8]}@example.com")
        user_b = make_user(client, email=f"b-{uuid.uuid4().hex[:8]}@example.com")

        document_id = upload(
            client,
            "/upload-pdf",
            "secret.pdf",
            pdf_bytes,
            PDF_CONTENT_TYPE,
            user_a["headers"],
        ).json()["document_id"]

        ask = client.post(
            "/ask",
            json={"document_id": document_id, "question": "What is inside?"},
            headers=user_b["headers"],
        )
        search = client.post(
            "/search",
            json={"document_id": document_id, "question": "What is inside?"},
            headers=user_b["headers"],
        )
        messages = client.get(
            f"/documents/{document_id}/messages", headers=user_b["headers"]
        )
        delete = client.delete(f"/documents/{document_id}", headers=user_b["headers"])

        assert ask.status_code == 404
        assert search.status_code == 404
        assert messages.status_code == 404
        assert delete.status_code == 404

        # User A's document is untouched by all of User B's attempts.
        listing_a = client.get("/documents", headers=user_a["headers"]).json()
        assert listing_a["total_documents"] == 1
        assert (
            client.get(
                f"/documents/{document_id}/messages", headers=user_a["headers"]
            ).status_code
            == 200
        )


class TestPersistenceRecovery:

    def test_restart_recovers_documents_history_and_retrieval(
        self, client, pdf_bytes, monkeypatch
    ):
        import main as main_module

        user = make_user(client)
        document_id = upload(
            client,
            "/upload-pdf",
            "persist.pdf",
            pdf_bytes,
            PDF_CONTENT_TYPE,
            user["headers"],
        ).json()["document_id"]

        monkeypatch.setattr(
            main_module,
            "answer_question_with_deepseek",
            lambda question, retrieved_chunks: "Stub answer.",
        )
        ask = client.post(
            "/ask",
            json={"document_id": document_id, "question": "What mentions apple?"},
            headers=user["headers"],
        )
        assert ask.status_code == 200

        # Simulate a server restart: drop every in-memory cache.
        document_store.clear_cache()

        listing = client.get("/documents", headers=user["headers"]).json()
        assert listing["total_documents"] == 1
        assert listing["documents"][0]["document_id"] == document_id

        messages = client.get(
            f"/documents/{document_id}/messages", headers=user["headers"]
        ).json()["messages"]
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[1]["content"] == "Stub answer."

        search = client.post(
            "/search",
            json={"document_id": document_id, "question": "apple", "top_k": 2},
            headers=user["headers"],
        )
        assert search.status_code == 200
        assert search.json()["results"]

    def test_missing_index_file_is_rebuilt_from_database(self, client, pdf_bytes):
        user = make_user(client)
        document_id = upload(
            client,
            "/upload-pdf",
            "rebuild.pdf",
            pdf_bytes,
            PDF_CONTENT_TYPE,
            user["headers"],
        ).json()["document_id"]

        index_path = document_store.index_path_for(document_id)
        assert index_path.exists()
        index_path.unlink()
        document_store.clear_cache()

        search = client.post(
            "/search",
            json={"document_id": document_id, "question": "apple", "top_k": 2},
            headers=user["headers"],
        )

        assert search.status_code == 200
        assert search.json()["results"]
        assert index_path.exists()  # rebuilt and saved back to disk

    def test_delete_removes_upload_and_index_files(self, client, pdf_bytes):
        from database import SessionLocal
        from models import Document as DocumentModel

        user = make_user(client)
        document_id = upload(
            client,
            "/upload-pdf",
            "cleanup.pdf",
            pdf_bytes,
            PDF_CONTENT_TYPE,
            user["headers"],
        ).json()["document_id"]

        db = SessionLocal()
        try:
            document = (
                db.query(DocumentModel)
                .filter(DocumentModel.id == document_id)
                .one()
            )
            stored_path = document.stored_path
            index_path = document.index_path
        finally:
            db.close()

        assert stored_path and index_path

        response = client.delete(
            f"/documents/{document_id}", headers=user["headers"]
        )
        assert response.status_code == 200

        from pathlib import Path

        assert not Path(stored_path).exists()
        assert not Path(index_path).exists()

        messages = client.get(
            f"/documents/{document_id}/messages", headers=user["headers"]
        )
        assert messages.status_code == 404
