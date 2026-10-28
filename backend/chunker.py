import re
from typing import List, Dict


def clean_text(text: str) -> str:
    """
    Clean extracted PDF text.
    Removes extra spaces and line breaks.
    """

    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\s*\n\s*", "", text)
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


def create_chunks_from_units(
    units: List[Dict],
    chunk_size: int = 1000,
    overlap: int = 200
) -> List[Dict]:
    """
    Split generic source units (PDF pages, docx block sections) into
    overlapping chunks.

    Args:
        units: List of unit dictionaries, each with:
            - "text": the unit's text
            - "label": identifier used in chunk ids (e.g. "page_3")
            - "meta": metadata copied onto every chunk from that unit
        chunk_size: Maximum characters per chunk
        overlap: Overlap between chunks

    Returns:
        List of chunk dictionaries with the unit's metadata attached
    """

    all_chunks = []

    for unit in units:
        unit_chunks = chunk_text(
            text=unit["text"],
            chunk_size=chunk_size,
            overlap=overlap
        )

        for chunk_index, chunk in enumerate(unit_chunks, start=1):
            all_chunks.append(
                {
                    "chunk_id": f"{unit['label']}_chunk_{chunk_index}",
                    **unit["meta"],
                    "text": chunk
                }
            )

    return all_chunks


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
        List of chunk dictionaries with "page" metadata
    """

    units = [
        {
            "text": page["text"],
            "label": f"page_{page['page']}",
            "meta": {"page": page["page"]}
        }
        for page in pages
    ]

    return create_chunks_from_units(
        units=units,
        chunk_size=chunk_size,
        overlap=overlap
    )
