import os
from pathlib import Path

import numpy as np
import faiss
from dotenv import load_dotenv
from openai import OpenAI


ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

OPENAI_DEFAULT_MODEL = "text-embedding-3-small"
LOCAL_DEFAULT_MODEL = "all-MiniLM-L6-v2"

# Anti-hallucination guardrail: minimum cosine similarity (IndexFlatIP over
# L2-normalized vectors) for a retrieved chunk to be trusted as context. The
# query router drops the request to the LLM when the top result scores below
# this. Calibrated against all-MiniLM-L6-v2 on the benchmark corpora:
# unrelated queries score <=0.11, related ones >=0.16 (measured 0.16-0.6),
# so anything near or below ~0.1 is noise. This gate is a cheap first filter
# only — the LLM's grounding prompt is the real refusal authority for
# on-topic-but-unanswerable questions, which can score above unrelated ones.
# Tune per deployment via the MIN_SIMILARITY_SCORE env var.
MIN_SIMILARITY_SCORE = float(os.getenv("MIN_SIMILARITY_SCORE", "0.13"))

# Module-level cache so the SentenceTransformers model is loaded (and
# downloaded) once per process, not once per document.
_local_model_cache: dict = {}


class VectorStore:
    def __init__(self, model_name: str | None = None):
        """
        In-memory FAISS vector store for one document.

        Embeddings come from the OpenAI API when OPENAI_API_KEY is set.
        Without a key, the store automatically falls back to a local
        SentenceTransformers model so uploads and search work fully offline.

        An explicit model_name overrides the model of whichever provider is
        active (EMBEDDING_MODEL for OpenAI, LOCAL_EMBEDDING_MODEL for local).
        """

        self.provider = "openai" if os.getenv("OPENAI_API_KEY") else "local"

        if model_name is not None:
            self.model_name = model_name
        elif self.provider == "openai":
            self.model_name = os.getenv("EMBEDDING_MODEL", OPENAI_DEFAULT_MODEL)
        else:
            self.model_name = os.getenv("LOCAL_EMBEDDING_MODEL", LOCAL_DEFAULT_MODEL)

        self.client = self._get_openai_client() if self.provider == "openai" else None
        self.index = None
        self.chunks = []
        self.dimension = None

    def _get_openai_client(self):
        load_dotenv(dotenv_path=ENV_PATH, override=False)
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            return None

        return OpenAI(api_key=api_key)

    def _get_local_model(self):
        from sentence_transformers import SentenceTransformer

        model = _local_model_cache.get(self.model_name)

        if model is None:
            model = SentenceTransformer(self.model_name)
            _local_model_cache[self.model_name] = model

        return model

    def _embed_texts_local(self, texts):
        model = self._get_local_model()

        embeddings = model.encode(
            list(texts),
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return np.asarray(embeddings, dtype="float32")

    def _embed_texts(self, texts):
        if not texts:
            return np.array([], dtype="float32")

        if self.provider == "local":
            return self._embed_texts_local(texts)

        if self.client is None:
            raise ValueError(
                "OPENAI_API_KEY not found. Please add OPENAI_API_KEY in your .env file."
            )

        embeddings = []
        batch_size = 96

        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]

            response = self.client.embeddings.create(
                model=self.model_name,
                input=batch
            )

            embeddings.extend([item.embedding for item in response.data])

        return np.array(embeddings, dtype="float32")

    def embedding_dimension(self) -> int:
        """
        Output dimension of the active embedding provider.

        Used to verify a persisted FAISS index still matches the current
        provider before querying it.
        """

        if self.provider == "local":
            model = self._get_local_model()

            # sentence-transformers >= 6 renamed this method; support both.
            get_dimension = getattr(
                model, "get_embedding_dimension", None
            ) or getattr(model, "get_sentence_embedding_dimension", None)

            dimension = get_dimension() if get_dimension else None

            if dimension:
                return int(dimension)

        probe = self._embed_texts(["dimension probe"])
        return int(probe.shape[1])

    def build_index(self, chunks):
        """
        Create FAISS index from text chunks.
        """

        if not chunks:
            raise ValueError("No chunks provided for indexing.")

        self.chunks = chunks
        texts = [chunk["text"] for chunk in chunks]

        embeddings = self._embed_texts(texts)

        # Normalize embeddings for cosine similarity
        faiss.normalize_L2(embeddings)

        self.dimension = embeddings.shape[1]

        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)

        return {
            "total_chunks_indexed": len(chunks),
            "embedding_dimension": self.dimension
        }

    def search(self, query: str, top_k: int = 5):
        """
        Search for the most relevant chunks for a query.
        """

        if self.index is None:
            raise ValueError("Vector index has not been created yet.")

        query = " ".join(query.split())
        if not query:
            return []

        top_k = min(top_k, len(self.chunks))
        if top_k <= 0:
            return []

        query_embedding = self._embed_texts([query])
        faiss.normalize_L2(query_embedding)

        scores, indices = self.index.search(query_embedding, top_k)

        results = []

        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue

            chunk = self.chunks[idx]

            metadata = {
                key: value
                for key, value in chunk.items()
                if key not in ("chunk_id", "text")
            }

            results.append(
                {
                    "score": float(score),
                    "chunk_id": chunk["chunk_id"],
                    **metadata,
                    "text": chunk["text"]
                }
            )

        return results

    def save_index(self, path) -> None:
        """
        Write the FAISS index to disk so it survives restarts.
        """

        if self.index is None:
            raise ValueError("No FAISS index has been built to save.")

        faiss.write_index(self.index, str(path))

    def load_index(self, path, chunks) -> None:
        """
        Restore a FAISS index from disk and reattach its chunk metadata.
        """

        self.index = faiss.read_index(str(path))
        self.dimension = self.index.d
        self.chunks = chunks
