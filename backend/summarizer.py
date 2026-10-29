"""
Grounded executive summaries shown when a document is first opened.

The summary is generated once per document — at upload time when possible,
otherwise lazily on first open — and persisted on the Document row as JSON:

    {"overview": str, "takeaways": [{"text": str, "source": str}], "method": str}

Two generation methods, in order of preference:

1. "llm"        DeepSeek summarizes evenly spaced excerpts of the document.
                Every takeaway citation is validated against the excerpt
                labels actually provided; takeaways with invented sources
                are discarded.
2. "extractive" Deterministic fallback when no API key is configured or the
                LLM call fails: verbatim leading sentences plus evenly spaced
                excerpts, each citing its own page/block label. Never fails
                and needs no network, so uploads stay fully offline-capable.
"""

import json
import re
from typing import Dict, List, Optional

from chatbot import build_context_from_chunks, format_chunk_source, get_deepseek_client

MAX_SUMMARY_CHUNKS = 8
MAX_TAKEAWAYS = 3
OVERVIEW_MAX_CHARS = 340
TAKEAWAY_MAX_CHARS = 220

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

SUMMARY_SYSTEM_PROMPT = """You are DocuMind AI, a document summarization assistant.

Summarize the provided document excerpts into a grounded executive summary.

Output STRICT JSON only, with this exact shape:
{"overview": "<string>", "takeaways": [{"text": "<string>", "source": "<string>"}]}

Rules:
1. Use only the provided excerpts. Do not use outside knowledge.
2. "overview": 2-3 sentences describing what the document is and covers.
3. "takeaways": exactly 3 items, the most important points of the document.
4. Each takeaway's "source" must be the exact bracket label of an excerpt the
   takeaway came from, e.g. "Page 2" or "Blocks 3-4". Never invent sources.
5. No markdown, no extra keys, no text outside the JSON object.
"""


def select_summary_chunks(chunks: List[Dict], max_chunks: int = MAX_SUMMARY_CHUNKS) -> List[Dict]:
    """
    Pick chunks evenly spaced across the document (always including the first
    and last) so the summary covers the whole document, not just its opening.
    """

    if len(chunks) <= max_chunks:
        return list(chunks)

    span = (len(chunks) - 1) / (max_chunks - 1)
    indices = {round(i * span) for i in range(max_chunks)}

    return [chunks[i] for i in sorted(indices)]


def _first_sentences(text: str, max_chars: int, max_sentences: int = 2) -> str:
    text = " ".join(text.split())
    if not text:
        return ""

    sentences = _SENTENCE_SPLIT.split(text)
    result = ""

    for sentence in sentences[:max_sentences]:
        if not sentence:
            continue
        if result and len(result) + 1 + len(sentence) > max_chars:
            break
        result = f"{result} {sentence}".strip()

        if len(result) >= max_chars:
            break

    if not result:
        result = text[:max_chars]

    if len(result) > max_chars:
        cut = result[:max_chars].rsplit(" ", 1)[0]
        result = cut or result[:max_chars]

    return result


def build_extractive_summary(chunks: List[Dict]) -> Dict:
    """
    Deterministic, fully offline summary from verbatim document text.
    """

    non_empty = [chunk for chunk in chunks if chunk.get("text", "").strip()]
    leading = non_empty[0] if non_empty else chunks[0]

    overview = _first_sentences(leading["text"], OVERVIEW_MAX_CHARS)

    selected = select_summary_chunks(non_empty, MAX_TAKEAWAYS)

    takeaways = []
    for chunk in selected:
        text = _first_sentences(chunk["text"], TAKEAWAY_MAX_CHARS, max_sentences=1)
        if not text:
            continue
        takeaways.append(
            {
                "text": text,
                "source": format_chunk_source(chunk),
            }
        )

    return {
        "overview": overview,
        "takeaways": takeaways,
        "method": "extractive",
    }


def _parse_llm_summary(raw: str, valid_sources: set) -> Optional[Dict]:
    """
    Parse and validate the LLM's JSON output. Returns None when the output is
    unusable; takeaways citing a source that was not provided are dropped.
    """

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
    except ValueError:
        return None

    if not isinstance(parsed, dict):
        return None

    overview = parsed.get("overview")
    if not isinstance(overview, str) or not overview.strip():
        return None

    raw_takeaways = parsed.get("takeaways")
    if not isinstance(raw_takeaways, list):
        return None

    takeaways = []
    for item in raw_takeaways:
        if not isinstance(item, dict):
            continue

        text = item.get("text")
        source = item.get("source")

        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(source, str) or source.strip() not in valid_sources:
            # Ungrounded citation: drop the takeaway rather than keep a
            # fabricated source label.
            continue

        takeaways.append(
            {
                "text": " ".join(text.split()),
                "source": source.strip(),
            }
        )

        if len(takeaways) == MAX_TAKEAWAYS:
            break

    if not takeaways:
        return None

    return {
        "overview": " ".join(overview.split()),
        "takeaways": takeaways,
        "method": "llm",
    }


def generate_llm_summary(chunks: List[Dict]) -> Optional[Dict]:
    """
    Generate a summary with DeepSeek. Returns None (never raises) when no
    client is available, the call fails, or the output fails validation.
    """

    client = get_deepseek_client()
    if client is None:
        return None

    selected = select_summary_chunks(chunks)
    context = build_context_from_chunks(selected)
    valid_sources = {format_chunk_source(chunk) for chunk in selected}

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Document excerpts (source-tagged):\n"
                        f"{context}\n\n"
                        "Executive summary JSON:"
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=500,
            timeout=30,
        )
        raw = response.choices[0].message.content
    except Exception:
        return None

    return _parse_llm_summary(raw, valid_sources)


def generate_document_summary(chunks: List[Dict]) -> Dict:
    """
    Generate the persisted executive summary for a document. Tries the LLM
    path first and always falls back to the deterministic extractive summary,
    so this only raises when the document has no chunks at all.
    """

    if not chunks:
        raise ValueError("Cannot summarize a document with no chunks.")

    llm_summary = generate_llm_summary(chunks)

    return llm_summary if llm_summary is not None else build_extractive_summary(chunks)
