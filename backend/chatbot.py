import os
from typing import List, Dict

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


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


NOT_FOUND_ANSWER = (
    "The document does not contain enough information to answer this question."
)

SYSTEM_PROMPT = """
You are DocuMind AI, a helpful document question-answering assistant.

You must answer the user's question using only the provided document context.

Rules:
1. Use only the provided context. Do not use outside knowledge.
2. If the question is about the document's overall scope — what it covers,
   what it is about, or what it does not cover — summarize the primary
   topics explicitly discussed in the provided context, then clarify that
   topics outside these areas are not addressed in the document.
3. Respond with exactly
   "The document does not contain enough information to answer this question."
   only when the question asks about specific facts, entities, or details
   that are completely unrelated to the document's subject matter.
4. If the question is on-topic but the context lacks the specific detail
   asked for, say so plainly in your own words and mention what the context
   does say about the topic, if anything. Do not use the sentence from
   rule 3 in this case.
5. Do not make up information.
6. Mention the provided source references when possible: "Source pages: X, Y"
   for PDF documents or "Source blocks: X-Y" for Word documents.
7. Keep answers clear, concise, and useful for normal users.
8. If asked for a summary or main idea, provide 3-6 sentences.
9. If asked for key points, provide 3-7 bullet points.
10. If asked for a conclusion, provide 1-3 sentences.
11. If asked for a definition or explanation, give a brief definition and a
    short clarification using the context.
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