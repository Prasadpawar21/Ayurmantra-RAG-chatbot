import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional

import groq

from src.config import CHATBOT_TOP_K, GROQ_API_KEY, GROQ_CHAT_MODEL
from src.context_service import build_documents, fetch_user_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

vector_store: Dict[str, List[Dict[str, Any]]] = {}
_groq_client: Optional[groq.Client] = None


def _get_groq_client() -> groq.Client:
    global _groq_client
    if _groq_client is None:
        _groq_client = groq.Client(api_key=GROQ_API_KEY)
    return _groq_client


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _build_index_entry(document: Dict[str, Any]) -> Dict[str, Any]:
    text = str(document.get("text", ""))
    tokens = _tokenize(text)
    return {
        "document": document,
        "token_counts": Counter(tokens),
        "token_set": set(tokens),
        "length": len(tokens),
    }


def _score_document(query_tokens: List[str], query_counts: Counter[str], item: Dict[str, Any]) -> float:
    if not query_tokens or not item["token_set"]:
        return 0.0

    overlap = sum(min(query_counts[token], item["token_counts"].get(token, 0)) for token in query_counts)
    coverage = overlap / max(len(query_tokens), 1)
    density = overlap / max(item["length"], 1)
    phrase_bonus = 0.15 if " ".join(query_tokens) in str(item["document"].get("text", "")).lower() else 0.0
    return round((coverage * 0.8) + (density * 0.2) + phrase_bonus, 6)


def refresh_user_vector_store(user_id: str, context: Optional[Dict[str, Any]] = None) -> int:
    logger.info("Refreshing retrieval store for user %s", user_id)
    if context is None:
        context = fetch_user_context(user_id)

    documents = build_documents(context)
    store = [_build_index_entry(document) for document in documents if document.get("text")]
    vector_store[user_id] = store
    logger.info("Stored %d retrieval documents for user %s", len(store), user_id)
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
    logger.info(
        "Retrieving documents for user %s query=%s top_k=%s score_threshold=%s",
        user_id,
        query,
        top_k,
        score_threshold,
    )
    store = _get_user_store(user_id)
    if not store:
        logger.warning("No vector store available for user %s", user_id)
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        logger.warning("Could not tokenize query: %s", query)
        return []

    query_counts = Counter(query_tokens)
    scored: List[Dict[str, Any]] = []
    for item in store:
        similarity = _score_document(query_tokens, query_counts, item)
        if similarity >= score_threshold:
            scored.append({"document": item["document"], "score": similarity})

    scored.sort(key=lambda item: item["score"], reverse=True)
    docs = [{**item["document"], "score": item["score"]} for item in scored[:top_k]]
    logger.info("Retrieved %d documents for user %s", len(docs), user_id)
    return docs


def _build_system_prompt() -> str:
    return (
        "You are a health assistant.\n\n"
        "Rules:\n"
        "- Answer only using the provided documents.\n"
        "- For food-related questions, analyze all relevant food logs and summaries.\n"
        "- For appointment-related questions, consider all relevant consultations.\n"
        "- Aggregate information when needed.\n"
        '- If the answer is not supported by the documents, say "the information is not available."\n\n'
        "Be specific and data-driven."
    )


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
        fallback = "I could not find enough user-specific data to answer that question based on the available documents."
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
