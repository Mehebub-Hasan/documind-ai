import numpy as np
import faiss
from sentence_transformers import SentenceTransformer


class VectorStore:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        In-memory FAISS vector store for one PDF document.
        """
        self.model = SentenceTransformer(model_name)
        self.index = None
        self.chunks = []
        self.dimension = None

    def build_index(self, chunks):
        """
        Create FAISS index from text chunks.
        """

        if not chunks:
            raise ValueError("No chunks provided for indexing.")

        self.chunks = chunks
        texts = [chunk["text"] for chunk in chunks]

        embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False
        )

        embeddings = embeddings.astype("float32")

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

        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            show_progress_bar=False
        )

        query_embedding = query_embedding.astype("float32")
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