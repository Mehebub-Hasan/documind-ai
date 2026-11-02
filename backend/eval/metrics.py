"""
LLM-as-a-Judge metrics for the RAG Triad.

All three judges use deepseek-chat in JSON mode (response_format
json_object) and return a score in [0.0, 1.0] plus reasoning:

1. Context Relevance  — do the retrieved chunks contain the information
   needed to answer the query, without excessive noise?
2. Groundedness       — is every atomic claim in the generated answer
   directly supported by the retrieved chunks? (Hallucination detection.)
3. Answer Relevance   — does the answer directly and completely address the
   query? A clear refusal is the correct answer for an unanswerable query.

Judge calls raise JudgeError on failure (missing key, API error, unparseable
output) so the runner can record the failure per case instead of silently
scoring 0.0.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chatbot import format_chunk_source, get_deepseek_client

JUDGE_MODEL = "deepseek-chat"

CHUNK_TEXT_LIMIT = 1500
ANSWER_TEXT_LIMIT = 2500

_VALID_JSON_KEY = re.compile(r"^[\w\-\s]+$")


class JudgeError(RuntimeError):
    """Raised when a judge call cannot be completed or its output is unusable."""


def _parse_judge_json(raw: str) -> Dict:
    cleaned = (raw or "").strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
    except ValueError as exc:
        raise JudgeError(f"Judge returned unparseable JSON: {raw[:200]}") from exc

    if not isinstance(parsed, dict):
        raise JudgeError(f"Judge JSON is not an object: {raw[:200]}")

    return parsed


def _clamp_score(value) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, min(1.0, score))


def _judge(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> Dict:
    client = get_deepseek_client()

    if client is None:
        raise JudgeError("DEEPSEEK_API_KEY is not configured; judge unavailable.")

    try:
        response = client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise JudgeError(f"Judge API call failed: {exc}") from exc

    return _parse_judge_json(response.choices[0].message.content)


def _format_chunks(retrieved_chunks: List[Dict]) -> str:
    parts = []

    for chunk in retrieved_chunks:
        label = format_chunk_source(chunk)
        text = (chunk.get("text") or "")[:CHUNK_TEXT_LIMIT]
        parts.append(f"[{label}]\n{text}")

    return "\n\n---\n\n".join(parts)


def _reasoning(parsed: Dict) -> str:
    value = parsed.get("reasoning")
    return value if isinstance(value, str) else ""


def score_context_relevance(user_query: str, retrieved_chunks: List[Dict]) -> Dict:
    """
    Judge whether the retrieved chunks contain the information needed to
    answer the query, without excessive irrelevant material.
    """

    system_prompt = """You are a strict evaluation judge for a RAG (retrieval-augmented
generation) system. You grade retrieval quality only — never answer quality.

Rate how well the retrieved chunks support answering the user's query:
does the context contain the key information, and how much of it is noise?

Respond ONLY with a JSON object:
{"score": <float 0.0-1.0>, "reasoning": "<2-3 sentences>"}

Score anchors:
1.0 = the context clearly contains the information needed; little noise.
0.7 = the key information is present but diluted by irrelevant chunks.
0.4 = only tangentially related material; the answer is likely missing.
0.0 = the context is irrelevant to the query."""

    user_prompt = f"""User query:
{user_query}

Retrieved chunks:
{_format_chunks(retrieved_chunks)}

Context relevance JSON:"""

    parsed = _judge(system_prompt, user_prompt)

    return {
        "score": _clamp_score(parsed.get("score")),
        "reasoning": _reasoning(parsed),
    }


def score_groundedness(retrieved_chunks: List[Dict], generated_answer: str) -> Dict:
    """
    Judge whether every atomic claim in the generated answer is directly
    supported by the retrieved chunks. Reports the hallucinated claims.
    """

    system_prompt = """You are a strict evaluation judge detecting hallucinations in a
RAG system's answer.

Break the generated answer into individual atomic claims (one fact each).
A claim is SUPPORTED only if the retrieved context explicitly states it —
not merely plausible or inferable. Paraphrasing is fine; invention is not.
A refusal (e.g. "I cannot find this information in the provided document."
or a sentence explaining the context does not contain the detail) makes no
factual claims, so it is fully grounded.

score = (supported claims) / (total claims). A pure refusal scores 1.0.

Respond ONLY with a JSON object:
{"score": <float 0.0-1.0>, "hallucinated_claims": ["<unsupported claim>", ...],
 "reasoning": "<2-3 sentences>"}"""

    user_prompt = f"""Retrieved context:
{_format_chunks(retrieved_chunks)}

Generated answer:
{(generated_answer or "")[:ANSWER_TEXT_LIMIT]}

Groundedness JSON:"""

    parsed = _judge(system_prompt, user_prompt)

    claims = parsed.get("hallucinated_claims")
    if not isinstance(claims, list):
        claims = []

    return {
        "score": _clamp_score(parsed.get("score")),
        "hallucinated_claims": [
            claim for claim in claims if isinstance(claim, str) and claim.strip()
        ],
        "reasoning": _reasoning(parsed),
    }


def score_answer_relevance(
    user_query: str,
    generated_answer: str,
    expected_refusal: bool = False,
) -> Dict:
    """
    Judge whether the answer directly and completely addresses the query.
    When expected_refusal is set, a clear, well-grounded refusal is the
    correct answer and scores highly.
    """

    system_prompt = """You are a strict evaluation judge for a RAG system's final answer.

Grade how directly and completely the answer addresses the user's query:
does it answer what was asked, without evasion, hedging, or irrelevant
chatter? If the query cannot be answered from any document, a clear refusal
that explains what IS known is the correct answer.

Respond ONLY with a JSON object:
{"score": <float 0.0-1.0>, "reasoning": "<2-3 sentences>"}

Score anchors:
1.0 = directly and completely answers the query (or is a clear, appropriate
      refusal for an unanswerable query).
0.7 = addresses the core of the query but is incomplete or slightly off.
0.4 = partially related; important parts of the query are unaddressed.
0.0 = evasive, irrelevant, or refuses an answerable query without reason."""

    refusal_note = (
        "\n\nNote: this question is intentionally unanswerable from the "
        "source document. A clear refusal is the expected, correct behavior."
        if expected_refusal
        else ""
    )

    user_prompt = f"""User query:
{user_query}
{refusal_note}
Generated answer:
{(generated_answer or "")[:ANSWER_TEXT_LIMIT]}

Answer relevance JSON:"""

    parsed = _judge(system_prompt, user_prompt)

    return {
        "score": _clamp_score(parsed.get("score")),
        "reasoning": _reasoning(parsed),
    }
