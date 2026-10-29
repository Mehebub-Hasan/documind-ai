import json
import os
from pathlib import Path
from threading import Lock

from sqlalchemy.orm import Session

from models import Document, DocumentChunk
from vector_store import VectorStore

BACKEND_DIR = Path(__file__).resolve().parent

INDEX_STORAGE_DIR = Path(
    os.getenv("INDEX_STORAGE_DIR", str(BACKEND_DIR / "storage" / "indexes"))
)
INDEX_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Hot cache of vector stores for documents queried in this process.
_store_cache: dict[str, VectorStore] = {}
_cache_lock = Lock()


def index_path_for(document_id: str) -> Path:
    return INDEX_STORAGE_DIR / f"{document_id}.faiss"


def _chunk_metadata(chunk: dict) -> dict:
    return {
        key: value for key, value in chunk.items() if key not in ("chunk_id", "text")
    }


def chunks_from_rows(rows) -> list:
    """
    Rebuild chunk dictionaries (chunk_id + metadata + text) from DB rows.
    """

    return [
        {
            "chunk_id": row.chunk_id,
            **json.loads(row.metadata_json or "{}"),
            "text": row.text,
        }
        for row in rows
    ]


def persist_new_document(
    db: Session,
    *,
    document_id: str,
    user_id: str,
    filename: str,
    stored_path: str,
    source_type: str,
    summary: dict,
    chunks: list,
    vector_store: VectorStore,
    executive_summary: dict | None = None,
) -> Path:
    """
    Save document metadata and chunks to the database and write the FAISS
    index to INDEX_STORAGE_DIR. Returns the index file path.
    """

    index_path = index_path_for(document_id)
    vector_store.save_index(index_path)

    db.add(
        Document(
            id=document_id,
            user_id=user_id,
            filename=filename,
            stored_path=stored_path,
            source_type=source_type,
            summary_json=json.dumps(summary),
            summary=(
                json.dumps(executive_summary) if executive_summary is not None else None
            ),
            chunk_count=len(chunks),
            index_path=str(index_path),
        )
    )

    db.add_all(
        [
            DocumentChunk(
                document_id=document_id,
                chunk_index=index,
                chunk_id=chunk["chunk_id"],
                text=chunk["text"],
                metadata_json=json.dumps(_chunk_metadata(chunk)),
            )
            for index, chunk in enumerate(chunks)
        ]
    )

    db.commit()

    with _cache_lock:
        _store_cache[document_id] = vector_store

    return index_path


def get_vector_store(db: Session, document: Document) -> VectorStore:
    """
    Return the FAISS vector store for a document.

    Serves hot documents from the in-memory cache; otherwise loads the index
    from disk. If the index file is missing (e.g. the container restarted and
    wiped the disk), the index is rebuilt from the stored DocumentChunk rows
    and saved back to disk.
    """

    with _cache_lock:
        cached = _store_cache.get(document.id)
        if cached is not None:
            return cached

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    chunks = chunks_from_rows(rows)

    vector_store = VectorStore()
    index_path = index_path_for(document.id)

    if index_path.exists():
        vector_store.load_index(index_path, chunks)

    # Rebuild when no index file exists yet, or when the one on disk was
    # built with a different embedding provider/model (for example the
    # OpenAI key was removed and we now fall back to the local model), so
    # query embeddings always match the index dimension.
    if (
        vector_store.index is None
        or vector_store.dimension != vector_store.embedding_dimension()
    ):
        vector_store.build_index(chunks)
        vector_store.save_index(index_path)
        document.index_path = str(index_path)
        db.commit()

    with _cache_lock:
        _store_cache[document.id] = vector_store

    return vector_store


def clear_cache(document_id: str | None = None) -> None:
    """
    Drop cached vector stores (all of them, or one document). Tests use this
    to simulate a server restart.
    """

    with _cache_lock:
        if document_id is None:
            _store_cache.clear()
        else:
            _store_cache.pop(document_id, None)


def delete_document_files(document: Document) -> None:
    """
    Remove the uploaded file and the FAISS index file from disk, and drop
    the document from the in-memory cache.
    """

    for raw_path in (document.stored_path, document.index_path):
        if not raw_path:
            continue

        path = Path(raw_path)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    clear_cache(document.id)
