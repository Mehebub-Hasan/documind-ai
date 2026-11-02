"""
Shared Google Gemini client for DocuMind AI.

One place configures the google-generativeai SDK from GEMINI_API_KEY and
exposes the two primitives the backend needs:

- Embeddings via gemini-embedding-001 for the FAISS vector store.
  Documents are embedded with task_type "retrieval_document", user queries
  with "retrieval_query" (Google's recommended asymmetric setup). The model
  natively outputs 3072 dimensions; output_dimensionality truncates to 768
  (Matryoshka representation), matching the original indexing plan and
  keeping FAISS indexes compact.
- Text generation via gemini-flash-lite-latest for RAG answers, executive
  summaries, and the eval judges. The -latest alias always tracks the
  current GA Flash-Lite model: versioned models get retired for new API
  keys within months, and flagship Flash free tier is capped at ~20
  requests/day, while Flash-Lite carries a far larger free allowance —
  the right default for a free-tier deployment. Pin or upgrade via
  CHAT_MODEL (e.g. gemini-flash-latest) when billing is enabled.

Configuration is read from the environment on every call so tests (and
runtime env changes) take effect without re-importing the module; importing
this file never requires a key. Callers decide whether a missing key is
fatal (chat answers) or triggers a fallback (local embeddings, extractive
summary).
"""

import os
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

EMBEDDING_DEFAULT_MODEL = "models/gemini-embedding-001"
CHAT_DEFAULT_MODEL = "gemini-flash-lite-latest"

# Truncation target for embedding vectors. gemini-embedding-001 supports
# 768 / 1536 / 3072; 768 keeps indexes small and matches prior planning.
EMBEDDING_DEFAULT_DIMENSIONALITY = 768


def gemini_configured() -> bool:
    """
    Configure the SDK with GEMINI_API_KEY (environment or backend/.env).
    Returns False when no key is available. genai.configure is idempotent,
    so calling this before every request is cheap and always reflects the
    current environment.
    """

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return False

    genai.configure(api_key=api_key)

    return True


def embedding_output_dimensionality() -> int:
    """
    Dimension embeddings are truncated to (EMBEDDING_OUTPUT_DIMENSIONALITY
    env override). Must stay consistent across indexing and querying until
    all FAISS indexes are rebuilt.
    """

    raw = os.getenv("EMBEDDING_OUTPUT_DIMENSIONALITY")

    if raw:
        return int(raw)

    return EMBEDDING_DEFAULT_DIMENSIONALITY


def get_embedding(text: str, task_type: str = "retrieval_document") -> list[float]:
    """
    Embed a single text.

    task_type: "retrieval_document" for indexed chunks, "retrieval_query"
    for user queries.
    """

    if not gemini_configured():
        raise ValueError(
            "GEMINI_API_KEY not found. Please add GEMINI_API_KEY in your .env file."
        )

    result = genai.embed_content(
        model=os.getenv("EMBEDDING_MODEL", EMBEDDING_DEFAULT_MODEL),
        content=text,
        task_type=task_type,
        output_dimensionality=embedding_output_dimensionality(),
    )

    return result["embedding"]


def embed_texts(texts, task_type: str = "retrieval_document") -> list:
    """
    Embed a batch of texts, returning a list of vectors.

    The SDK batches automatically (100 texts per BatchEmbedContents
    request) and returns {"embedding": [vector, ...]} for list input.
    """

    if not gemini_configured():
        raise ValueError(
            "GEMINI_API_KEY not found. Please add GEMINI_API_KEY in your .env file."
        )

    result = genai.embed_content(
        model=os.getenv("EMBEDDING_MODEL", EMBEDDING_DEFAULT_MODEL),
        content=list(texts),
        task_type=task_type,
        output_dimensionality=embedding_output_dimensionality(),
    )

    return result["embedding"]


def get_chat_model(system_instruction: str | None = None):
    """
    GenerativeModel for gemini-flash-lite-latest, or None when no key is
    configured. Callers decide whether that is fatal (chat) or triggers a
    fallback (extractive summary).
    """

    if not gemini_configured():
        return None

    return genai.GenerativeModel(
        os.getenv("CHAT_MODEL", CHAT_DEFAULT_MODEL),
        system_instruction=system_instruction,
    )
