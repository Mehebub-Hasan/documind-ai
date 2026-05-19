import os
from pathlib import Path

import numpy as np
import faiss
from dotenv import load_dotenv
from openai import OpenAI


ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)


class VectorStore:
    def __init__(self, model_name: str | None = None):
        """
        In-memory FAISS vector store for one PDF document.
        """
        self.model_name = model_name or os.getenv(
            "EMBEDDING_MODEL",
            "text-embedding-3-small"
        )
        self.client = self._get_openai_client()
        self.index = None
        self.chunks = []
        self.dimension = None

    def _get_openai_client(self):
        load_dotenv(dotenv_path=ENV_PATH, override=False)
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            return None

        return OpenAI(api_key=api_key)

    def _embed_texts(self, texts):
        if not texts:
            return np.array([], dtype="float32")

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

            results.append(
                {
                    "score": float(score),
                    "chunk_id": chunk["chunk_id"],
                    "page": chunk["page"],
                    "text": chunk["text"]
                }
            )

        return results