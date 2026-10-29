import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

logger = logging.getLogger("documind.guardrail")


def get_deepseek_client():
    """
    Create DeepSeek client using OpenAI-compatible API.
    """

    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        return None

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com"
    )

    return client


def format_chunk_source(item: Dict) -> str:
    """
    Human-readable source label for a retrieved chunk.

    PDF chunks carry a page number. DOCX chunks carry a document block
    range, because Word files have no fixed pages.
    """

    page = item.get("page")
    if page is not None:
        return f"Page {page}"

    block_start = item.get("block_start")
    block_end = item.get("block_end")

    if block_start is not None and block_end is not None:
        if block_start == block_end:
            return f"Block {block_start}"
        return f"Blocks {block_start}-{block_end}"

    return "Unknown source"


def build_context_from_chunks(chunks: List[Dict]) -> str:
    """
    Convert retrieved chunks into a readable context block for the LLM.
    """

    context_parts = []

    for item in chunks:
        source = format_chunk_source(item)
        text = item.get("text", "")

        context_parts.append(
            f"[{source}]\n{text}"
        )

    return "\n\n---\n\n".join(context_parts)


# ---------------------------------------------------------------------------
# Anti-hallucination guardrail: post-generation attribution verification.
# ---------------------------------------------------------------------------

_PAGE_TAG_RE = re.compile(
    r"\[(Pages?\s+\d+(?:\s*(?:,|-|–)\s*\d+)*)\]", re.IGNORECASE
)
_BLOCK_TAG_RE = re.compile(r"\[(Blocks?\s+\d+(?:\s*-\s*\d+)?)\]", re.IGNORECASE)
_QUOTE_RE = re.compile(r"\"([^\"]{15,})\"")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was",
    "were", "has", "have", "had", "not", "but", "its", "their", "they",
    "you", "your", "our", "can", "will", "would", "could", "should",
    "into", "onto", "per", "via", "also", "only", "than", "then", "when",
    "what", "which", "who", "how", "why", "where", "all", "any", "each",
    "both", "more", "most", "some", "such",
    # Meta-discourse words the LLM uses to talk about the answer itself
    # (refusals, hedges) — they never appear in document text.
    "though", "however", "does", "did", "been", "being", "there", "about",
}

# A sentence carrying a citation must share at least this fraction of its
# content tokens with the retrieved context, or its citations are stripped.
# Calibrated at 0.40: honest refusal sentences ("the context does not
# specify...") run ~0.45-0.6, fabricated claims score near 0.
MIN_SENTENCE_COVERAGE = 0.4


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def _content_tokens(text: str) -> set:
    return {
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) >= 3 and token not in _STOP_WORDS
    }


def _token_covered(token: str, context_tokens: set) -> bool:
    """
    Exact match or shared morphological stem (simple >=5-char common prefix),
    so "migration" covers "migrate" and "zebras" covers "zebra" without a
    full stemming dependency.
    """

    if token in context_tokens:
        return True

    prefix = token[:5]

    if len(prefix) < 5:
        return False

    return any(
        ctx.startswith(prefix) or token.startswith(ctx[:5])
        for ctx in context_tokens
    )


def _valid_page_numbers(chunks: List[Dict]) -> set:
    return {
        chunk["page"] for chunk in chunks if chunk.get("page") is not None
    }


def _valid_block_ranges(chunks: List[Dict]) -> List[Tuple[int, int]]:
    ranges = []

    for chunk in chunks:
        start = chunk.get("block_start")
        end = chunk.get("block_end", start)
        if start is not None:
            ranges.append((int(start), int(end if end is not None else start)))

    return ranges


def _range_is_covered(start: int, end: int, ranges: List[Tuple[int, int]]) -> bool:
    """
    True when every block/page number in [start, end] falls inside the union
    of the retrieved ranges — i.e. the citation never points at context that
    was not provided.
    """

    if start > end:
        start, end = end, start

    return all(
        any(lo <= value <= hi for lo, hi in ranges)
        for value in range(start, end + 1)
    )


def _expand_tag_numbers(inner: str) -> List[int]:
    """
    "Page 3" -> [3]; "Pages 3, 4" -> [3, 4]; "Pages 3-5" -> [3, 4, 5].
    """

    numbers = [int(value) for value in re.findall(r"\d+", inner)]

    if "-" in inner or "–" in inner:
        return list(range(numbers[0], numbers[-1] + 1))

    return numbers


def _strip_citation_tags(text: str) -> str:
    stripped = _PAGE_TAG_RE.sub("", _BLOCK_TAG_RE.sub("", text))
    return _tidy_punctuation(stripped).strip()


def _tidy_punctuation(text: str) -> str:
    # Removing an inline tag can leave "drives ." — pull punctuation back.
    return re.sub(r"\s+([.,;:!?)\]])", r"\1", text)


def verify_attributions(answer_text: str, retrieved_chunks: List[Dict]) -> dict:
    """
    Post-generation guardrail: check that the LLM's citations and quoted
    material are genuinely grounded in the retrieved context.

    Three checks:
    1. Citation tags ([Page N] / [Blocks X-Y]) must reference pages/blocks
       that were actually retrieved. Hallucinated references are stripped.
    2. Explicit "quotes" (>= 15 chars) must appear verbatim (case- and
       whitespace-insensitive) in the retrieved text; otherwise the quotes
       are removed and the span flagged.
    3. Sentence-level coverage: a sentence bearing a citation must share at
       least MIN_SENTENCE_COVERAGE of its content tokens with the context,
       otherwise its citation tags are stripped as unverified.

    Returns a report dict:
    {
        "cleaned_answer":    answer after stripping ungrounded citations,
        "grounded":          True when nothing had to be removed,
        "removed_citations": [stripped tag strings],
        "unverified_quotes": [quote inner texts that were not found],
        "flagged_sentences": [sentences whose citations were stripped],
    }
    """

    answer = answer_text or ""
    report = {
        "cleaned_answer": answer,
        "grounded": True,
        "removed_citations": [],
        "unverified_quotes": [],
        "flagged_sentences": [],
    }

    if not answer.strip() or not retrieved_chunks:
        return report

    valid_pages = _valid_page_numbers(retrieved_chunks)
    valid_ranges = _valid_block_ranges(retrieved_chunks)
    context_normalized = _normalize(
        " ".join(chunk.get("text", "") for chunk in retrieved_chunks)
    )
    context_tokens: set = set()
    for chunk in retrieved_chunks:
        context_tokens |= _content_tokens(chunk.get("text", ""))

    # --- 1. Citation references must point at retrieved context. ----------
    def _check_page_tag(match: re.Match) -> str:
        numbers = _expand_tag_numbers(match.group(1))
        if all(number in valid_pages for number in numbers):
            return match.group(0)

        report["removed_citations"].append(match.group(0))
        logger.warning(
            "[RAG Guardrail] Removed invalid citation %s — page(s) not in "
            "retrieved context.",
            match.group(0),
        )
        return ""

    def _check_block_tag(match: re.Match) -> str:
        numbers = re.findall(r"\d+", match.group(1))
        start = int(numbers[0])
        end = int(numbers[-1])

        if valid_ranges and _range_is_covered(start, end, valid_ranges):
            return match.group(0)

        report["removed_citations"].append(match.group(0))
        logger.warning(
            "[RAG Guardrail] Removed invalid citation %s — block range not "
            "in retrieved context.",
            match.group(0),
        )
        return ""

    answer = _PAGE_TAG_RE.sub(_check_page_tag, answer)
    answer = _BLOCK_TAG_RE.sub(_check_block_tag, answer)
    answer = _tidy_punctuation(answer)

    # --- 2. Explicit quotes must exist verbatim in the context. -----------
    def _check_quote(match: re.Match) -> str:
        quote = match.group(1)

        # The LLM often includes sentence punctuation inside the quotes
        # ("during the restructuring.") even though the context has it
        # mid-sentence — match with trailing punctuation stripped too.
        candidate = _normalize(quote).rstrip(" .,;:!?")

        if candidate in context_normalized:
            return match.group(0)

        report["unverified_quotes"].append(quote)
        logger.warning(
            "[RAG Guardrail] Unverified quote removed: %.80s…",
            quote,
        )
        # Keep the text, drop the quotation marks: the claim survives
        # unquoted rather than presenting a fabricated quote as verbatim.
        return quote

    answer = _QUOTE_RE.sub(_check_quote, answer)

    # --- 3. Cited sentences must be represented in the context. -----------
    # Capturing split keeps the whitespace/newline separators so markdown
    # bullet formatting survives the round-trip.
    parts = re.split(r"((?<=[.!?])\s+)", answer)
    touched = False

    for index in range(0, len(parts), 2):
        sentence = parts[index]
        has_tag = bool(
            _PAGE_TAG_RE.search(sentence) or _BLOCK_TAG_RE.search(sentence)
        )
        tokens = _content_tokens(sentence)

        if has_tag and tokens:
            covered = sum(
                1 for token in tokens if _token_covered(token, context_tokens)
            )
            coverage = covered / len(tokens)

            if coverage < MIN_SENTENCE_COVERAGE:
                stripped = _strip_citation_tags(sentence)
                if stripped != sentence:
                    report["flagged_sentences"].append(sentence.strip())
                    logger.warning(
                        "[RAG Guardrail] Sentence coverage %.2f below "
                        "threshold; citations stripped: %.80s",
                        coverage,
                        sentence,
                    )
                    parts[index] = stripped
                    touched = True

    if touched:
        answer = "".join(parts)

    report["cleaned_answer"] = answer
    report["grounded"] = not (
        report["removed_citations"]
        or report["unverified_quotes"]
        or report["flagged_sentences"]
    )

    return report


NOT_FOUND_ANSWER = (
    "The document does not contain enough information to answer this question."
)

# Returned by the query router when retrieval relevance is below the
# FAISS similarity gate (the LLM is never called in that case).
BELOW_THRESHOLD_ANSWER = "I cannot find this information in the provided document."

_STANDARD_REFUSALS = (NOT_FOUND_ANSWER, BELOW_THRESHOLD_ANSWER)


def is_refusal_answer(answer: str) -> bool:
    """
    True when the answer begins with one of the standard refusal sentences.
    The LLM is instructed to answer unrelated questions with the exact
    NOT_FOUND sentence but often elaborates after it, so this is a
    prefix check rather than an exact-match one.
    """

    normalized = " ".join((answer or "").split())

    return any(normalized.startswith(refusal) for refusal in _STANDARD_REFUSALS)

SYSTEM_PROMPT = """
You are DocuMind AI, a helpful document question-answering assistant.

You must answer the user's question using only the provided document context.

Grounding rules (strict):
1. Use only the provided context. Never extrapolate, never fill gaps with
   plausible-sounding details, and never use outside knowledge. If a detail
   is not stated in the context, it does not exist for you.
2. Cite inline for every factual claim, immediately after the claim, using
   the exact source tags from the provided context: [Page N] for PDF pages
   or [Blocks X-Y] for Word document blocks. Only use tags that were
   provided — inventing a page or block reference is forbidden.
3. If the question is about the document's overall scope — what it covers,
   what it is about, or what it does not cover — summarize the primary
   topics explicitly discussed in the provided context, then clarify that
   topics outside these areas are not addressed in the document.
4. If the question asks about specific facts, entities, or details that are
   completely unrelated to the document's subject matter, respond with
   exactly:
   "The document does not contain enough information to answer this question."
5. If the question is on-topic but the context lacks the specific detail
   asked for, say so plainly in your own words, mention what the context
   does say about the topic (with citations), and do not reply with
   the sentence from rule 4.
6. Do not make up information.
7. Keep answers clear, concise, and useful for normal users.
8. If asked for a summary or main idea, provide 3-6 sentences.
9. If asked for key points, provide 3-7 bullet points.
10. If asked for a conclusion, provide 1-3 sentences.
11. If asked for a definition or explanation, give a brief definition and a
    short clarification using the context.

Negative demonstrations — study these refusals and behave the same way:

Demonstration 1 (unmentioned attribute):
Context: [Page 4] "The EN pin accepts an input voltage of 3.3 V."
Question: "What is the clock frequency of the IC?"
WRONG (fabrication): "The IC runs at a clock frequency of 100 MHz [Page 4]."
CORRECT (refusal): "The document does not mention the chip's clock
frequency. It only specifies that the enable pin accepts 3.3 V [Page 4]."

Demonstration 2 (invented policy and citation):
Context: [Blocks 2-3] "The device is covered by a 24-month limited
warranty."
Question: "What is the refund policy?"
WRONG: "Refunds are processed within 30 days of purchase [Blocks 5-6]."
CORRECT (refusal): "The document does not describe a refund policy. It only
states that the device carries a 24-month limited warranty [Blocks 2-3]."
"""


def answer_question_with_deepseek(
    question: str,
    retrieved_chunks: List[Dict]
) -> str:
    """
    Generate an answer using DeepSeek based only on retrieved document chunks.
    """

    client = get_deepseek_client()

    if client is None:
        raise ValueError(
            "DeepSeek API key not found. Please add DEEPSEEK_API_KEY in your .env file."
        )

    context = build_context_from_chunks(retrieved_chunks)

    user_prompt = f"""
Document context (source-tagged):
{context}

User Question:
{question}

Answer:
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        temperature=0.1,
        max_tokens=700
    )

    return response.choices[0].message.content