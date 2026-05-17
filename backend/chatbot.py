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


def build_context_from_chunks(chunks: List[Dict]) -> str:
    """
    Convert retrieved chunks into a readable context block for the LLM.
    """

    context_parts = []

    for item in chunks:
        page = item.get("page", "Unknown")
        text = item.get("text", "")

        context_parts.append(
            f"[Page {page}]\n{text}"
        )

    return "\n\n---\n\n".join(context_parts)


def answer_question_with_deepseek(
    question: str,
    retrieved_chunks: List[Dict]
) -> str:
    """
    Generate an answer using DeepSeek based only on retrieved PDF chunks.
    """

    client = get_deepseek_client()

    if client is None:
        raise ValueError(
            "DeepSeek API key not found. Please add DEEPSEEK_API_KEY in your .env file."
        )

    context = build_context_from_chunks(retrieved_chunks)

    system_prompt = """
You are a helpful PDF question-answering assistant.

You must answer the user's question using only the provided PDF context.

Rules:
1. Use only the provided context.
2. If the answer is not available in the context, say:
   "The PDF does not contain enough information to answer this question."
3. Do not make up information.
4. Mention source page numbers when possible.
5. Keep the answer clear and concise.
"""

    user_prompt = f"""
PDF Context:
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
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        temperature=0.2,
        max_tokens=700
    )

    return response.choices[0].message.content