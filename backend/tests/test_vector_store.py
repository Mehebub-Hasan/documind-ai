import numpy as np
import pytest

import document_store
from conftest import ORIGINAL_EMBED_TEXTS
from database import SessionLocal
from models import Document as DocumentModel
from vector_store import VectorStore


@pytest.fixture
def real_embed_texts(monkeypatch):
    """
    Undo the class-wide _embed_texts stub for tests that exercise the real
    provider dispatch (with a fake local model).
    """

    monkeypatch.setattr(VectorStore, "_embed_texts", ORIGINAL_EMBED_TEXTS)


class FakeLocalModel:
    """
    Stand-in for a SentenceTransformer model so tests never download or run
    the real one.
    """

    def __init__(self, dimension=8):
        self.dimension = dimension

    def encode(self, texts, convert_to_numpy=True, show_progress_bar=False):
        vectors = []

        for text in texts:
            vector = [0.0] * self.dimension
            vector[hash(text) % self.dimension] = 1.0
            vectors.append(vector)

        return np.array(vectors, dtype="float32")

    def get_sentence_embedding_dimension(self):
        return self.dimension


CHUNKS = [
    {"chunk_id": "page_1_chunk_1", "page": 1, "text": "alpha content"},
    {"chunk_id": "page_2_chunk_1", "page": 2, "text": "beta content"},
]


class TestProviderSelection:

    def test_falls_back_to_local_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LOCAL_EMBEDDING_MODEL", raising=False)

        store = VectorStore()

        assert store.provider == "local"
        assert store.model_name == "all-MiniLM-L6-v2"
        assert store.client is None

    def test_local_model_name_from_env(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("LOCAL_EMBEDDING_MODEL", "some-other-model")

        store = VectorStore()

        assert store.provider == "local"
        assert store.model_name == "some-other-model"

    def test_uses_openai_when_api_key_present(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

        store = VectorStore()

        assert store.provider == "openai"
        assert store.model_name == "text-embedding-3-small"
        assert store.client is not None

    def test_openai_model_name_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")

        store = VectorStore()

        assert store.provider == "openai"
        assert store.model_name == "text-embedding-3-large"


class TestLocalEmbeddings:

    def test_local_embed_texts_returns_float32_matrix(self, monkeypatch, real_embed_texts):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            VectorStore, "_get_local_model", lambda self: FakeLocalModel(6)
        )

        store = VectorStore()
        embeddings = store._embed_texts(["alpha", "beta"])

        assert embeddings.shape == (2, 6)
        assert embeddings.dtype == np.float32

    def test_openai_provider_without_client_raises(self, monkeypatch, real_embed_texts):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        store = VectorStore()
        store.provider = "openai"
        store.client = None

        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            store._embed_texts(["alpha"])

    def test_build_and_search_with_local_provider(self, monkeypatch, tmp_path, real_embed_texts):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            VectorStore, "_get_local_model", lambda self: FakeLocalModel(6)
        )

        store = VectorStore()
        index_summary = store.build_index(CHUNKS)

        assert index_summary["embedding_dimension"] == 6
        assert store.dimension == 6

        results = store.search("alpha content", top_k=1)

        assert len(results) == 1
        assert results[0]["chunk_id"] == "page_1_chunk_1"
        assert {"score", "chunk_id", "page", "text"} == set(results[0].keys())

    def test_save_and_load_index_roundtrip(self, monkeypatch, tmp_path, real_embed_texts):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            VectorStore, "_get_local_model", lambda self: FakeLocalModel(6)
        )

        store = VectorStore()
        store.build_index(CHUNKS)

        index_path = tmp_path / "doc.faiss"
        store.save_index(index_path)
        assert index_path.exists()

        restored = VectorStore()
        restored.load_index(index_path, CHUNKS)

        assert restored.dimension == 6
        assert len(restored.chunks) == 2
        assert restored.search("beta content", top_k=1)[0]["page"] == 2


class TestProviderSwitchRecovery:

    def test_stale_index_is_rebuilt_on_dimension_mismatch(
        self, client, pdf_bytes, monkeypatch
    ):
        """
        Upload with the default stub (8-dim). Then simulate switching to a
        different embedding provider (probe reports 4-dim): loading the old
        index must trigger a rebuild instead of a FAISS dimension crash.
        """

        from conftest import make_user
        from test_api import PDF_CONTENT_TYPE, upload

        user = make_user(client)
        document_id = upload(
            client,
            "/upload-pdf",
            "stale.pdf",
            pdf_bytes,
            PDF_CONTENT_TYPE,
            user["headers"],
        ).json()["document_id"]

        index_path = document_store.index_path_for(document_id)
        assert index_path.exists()

        document_store.clear_cache()
        monkeypatch.setattr(VectorStore, "embedding_dimension", lambda self: 4)

        db = SessionLocal()
        try:
            document = (
                db.query(DocumentModel)
                .filter(DocumentModel.id == document_id)
                .one()
            )
            store = document_store.get_vector_store(db, document)
        finally:
            db.close()

        # Rebuilt with the (still stubbed) embedder: coherent and queryable.
        assert store.index is not None
        assert store.dimension == 8
        assert index_path.exists()
        assert store.search("apple", top_k=1)
