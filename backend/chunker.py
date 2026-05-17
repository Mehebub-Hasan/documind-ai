import re
from typing import List, Dict


def clean_text(text: str) -> str:
    """
    Clean extracted PDF text.
    Removes extra spaces and line breaks.
    """
    if not text:
        return ""

    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200
) -> List[str]:
    """
    Split text into overlapping chunks.

    Args:
        text: Input text
        chunk_size: Maximum characters per chunk
        overlap: Number of overlapping characters between chunks

    Returns:
        List of text chunks
    """

    text = clean_text(text)

    if not text:
        return []

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start += chunk_size - overlap

    return chunks


def create_chunks_from_pages(
    pages: List[Dict],
    chunk_size: int = 1000,
    overlap: int = 200
) -> List[Dict]:
    """
    Create chunks from extracted PDF pages.

    Args:
        pages: List of page dictionaries from pdf_processor.py
        chunk_size: Maximum characters per chunk
        overlap: Overlap between chunks

    Returns:
        List of chunk dictionaries
    """

    all_chunks = []

    for page_data in pages:
        page_number = page_data["page"]
        page_text = page_data["text"]

        page_chunks = chunk_text(
            text=page_text,
            chunk_size=chunk_size,
            overlap=overlap
        )

        for chunk_index, chunk in enumerate(page_chunks, start=1):
            all_chunks.append(
                {
                    "chunk_id": f"page_{page_number}_chunk_{chunk_index}",
                    "page": page_number,
                    "text": chunk
                }
            )

    return all_chunks