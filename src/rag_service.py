import logging
import math
from typing import Any, Dict, List, Optional

import groq
from sentence_transformers import SentenceTransformer

from src.config import (
    EMBEDDING_MODEL_NAME,
    GROQ_API_KEY,
    GROQ_CHAT_MODEL,
    CHATBOT_TOP_K,
)
from src.context_service import build_documents, fetch_user_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

vector_store: Dict[str, List[Dict[str, Any]]] = {}
_embedding_model: Optional[SentenceTransformer] = None
_groq_client: Optional[groq.Client] = None


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _get_groq_client() -> groq.Client:
    global _groq_client
    if _groq_client is None:
        _groq_client = groq.Client(api_key=GROQ_API_KEY)
    return _groq_client


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_texts(documents: List[Dict[str, Any]]) -> List[str]:
    return [str(doc.get("text", "")) for doc in documents if doc.get("text")]


def _embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    model = _get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=False, show_progress_bar=False)
    return [[float(value) for value in vector] for vector in embeddings]


def refresh_user_vector_store(user_id: str, context: Optional[Dict[str, Any]] = None) -> int:
    logger.info("Refreshing vector store for user %s", user_id)
    if context is None:
        context = fetch_user_context(user_id)

    documents = build_documents(context)
    texts = _extract_texts(documents)
    embeddings = _embed_texts(texts)
    store: List[Dict[str, Any]] = []
    for document, embedding in zip(documents, embeddings):
        store.append({"document": document, "embedding": embedding})

    vector_store[user_id] = store
    logger.info("Stored %d vectors for user %s", len(store), user_id)
    return len(store)


def _get_user_store(user_id: str) -> List[Dict[str, Any]]:
    if user_id not in vector_store or not vector_store[user_id]:
        refresh_user_vector_store(user_id)
    return vector_store[user_id]


def retrieve_user_documents(
    user_id: str,
    query: str,
    top_k: int = CHATBOT_TOP_K,
    score_threshold: float = 0.0,
) -> List[Dict[str, Any]]:
    logger.info("Retrieving documents for user %s query=%s top_k=%s score_threshold=%s", user_id, query, top_k, score_threshold)
    store = _get_user_store(user_id)
    if not store:
        logger.warning("No vector store available for user %s", user_id)
        return []

    query_embeddings = _embed_texts([query])
    if not query_embeddings:
        logger.warning("Embedding generation failed for query: %s", query)
        return []

    query_embedding = query_embeddings[0]
    scored: List[Dict[str, Any]] = []
    for item in store:
        similarity = _cosine_similarity(item["embedding"], query_embedding)
        if similarity >= score_threshold:
            scored.append({"document": item["document"], "score": similarity})

    scored.sort(key=lambda item: item["score"], reverse=True)
    docs = [
        {
            **item["document"],
            "score": item["score"],
        }
        for item in scored[:top_k]
    ]
    logger.info("Retrieved %d documents for user %s", len(docs), user_id)
    return docs


# def _build_system_prompt() -> str:
#     return (
#         "You are an Ayurvedic health assistant. "
#         "Use only the provided documents to answer the user question. "
#         "Do not invent or hallucinate any private health details. "
#         "If the answer is not present in the documents, say you cannot answer from the available user data."
#     )

def _build_system_prompt():
    return """
        You are a health assistant.

        Rules:
        - Answer ONLY using provided documents
        - If food-related → analyze all food logs and summaries
        - If appointment-related → consider ALL appointments, not just one
        - Always aggregate information when needed
        - Never say "no document" unless absolutely no data exists

        Be specific and data-driven.
        """


def _build_context_summary(context: Dict[str, Any]) -> str:
    profile = context.get("profile", {})
    latest_assessment = context.get("assessment", {}).get("latest", {})
    food_summary = context.get("food", {}).get("summary", {})
    consultations = context.get("consultations", [])

    lines = [
        "Profile summary:",
        str(profile),
        "",
        "Latest assessment:",
        str(latest_assessment),
        "",
        "Food summary:",
        str(food_summary),
        "",
        "Upcoming consultations:",
        str(len(consultations)),
    ]
    return "\n".join(lines)


def _build_prompt(user_id: str, query: str, context: Dict[str, Any], retrieved_docs: List[Dict[str, Any]]) -> str:
    retrieved_text = "\n\n".join(
        [
            f"Document {idx + 1}:\n"
            f"Type: {doc['metadata'].get('doc_type')}\n"
            f"Source: {doc['metadata'].get('source_table')}\n"
            f"Source ID: {doc['metadata'].get('source_id')}\n"
            f"Score: {doc.get('score', 0.0):.4f}\n"
            f"Content:\n{doc['text']}"
            for idx, doc in enumerate(retrieved_docs)
        ]
    )
    return (
        f"User ID: {user_id}\n"
        f"Question: {query}\n\n"
        "Structured user context summary:\n"
        f"{_build_context_summary(context)}\n\n"
        "Retrieved documents:\n"
        f"{retrieved_text}\n\n"
        "Answer only from the documents above. If the answer cannot be derived from the documents, say that the information is not available."
    )


def _extract_response_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, dict):
        if "output_text" in response:
            return response["output_text"]
        choices = response.get("choices")
        if choices and isinstance(choices, list):
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    return message.get("content", "")
                return first.get("text", "")
    if hasattr(response, "output_text"):
        return getattr(response, "output_text")
    if hasattr(response, "choices"):
        choices = getattr(response, "choices")
        if choices:
            first = choices[0]
            message = getattr(first, "message", None)
            if message is not None:
                return getattr(message, "content", str(message))
    return str(response)


def _create_chat_response(prompt: str) -> str:
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=GROQ_CHAT_MODEL,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_completion_tokens=500,
    )
    return _extract_response_text(response)


def answer_query(
    user_id: str,
    query: str,
    top_k: int = CHATBOT_TOP_K,
    score_threshold: float = 0.0,
) -> Dict[str, Any]:
    context = fetch_user_context(user_id)
    if user_id not in vector_store or not vector_store[user_id]:
        refresh_user_vector_store(user_id, context)

    retrieved_docs = retrieve_user_documents(
        user_id=user_id,
        query=query,
        top_k=top_k,
        score_threshold=score_threshold,
    )

    prompt = _build_prompt(user_id, query, context, retrieved_docs)

    if not retrieved_docs:
        fallback = (
            "I could not find enough user-specific data to answer that question based on the available documents."
        )
        logger.info("No documents retrieved for user %s; returning fallback response", user_id)
        return {
            "answer": fallback,
            "retrieved_docs": [],
            "prompt": prompt,
        }

    answer = _create_chat_response(prompt)
    logger.info("Generated answer for user %s: %s", user_id, answer)

    return {
        "answer": answer,
        "retrieved_docs": retrieved_docs,
        "prompt": prompt,
    }
