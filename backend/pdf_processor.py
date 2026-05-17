import fitz  # PyMuPDF
from pathlib import Path


def extract_text_from_pdf(pdf_path: str):
    """
    Extract text from a PDF page by page.

    Returns:
        list of dictionaries:
        [
            {"page": 1, "text": "..."},
            {"page": 2, "text": "..."}
        ]
    """

    pdf_file = Path(pdf_path)

    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    pages = []

    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc):
            text = page.get_text("text")

            pages.append(
                {
                    "page": page_index + 1,
                    "text": text.strip()
                }
            )

    return pages


def get_pdf_summary(pages):
    """
    Create a simple summary of extracted PDF text.
    """

    total_pages = len(pages)
    total_characters = sum(len(page["text"]) for page in pages)
    non_empty_pages = sum(1 for page in pages if page["text"].strip())

    preview_text = ""

    for page in pages:
        if page["text"].strip():
            preview_text = page["text"][:500]
            break

    return {
        "total_pages": total_pages,
        "non_empty_pages": non_empty_pages,
        "total_characters": total_characters,
        "preview_text": preview_text
    }