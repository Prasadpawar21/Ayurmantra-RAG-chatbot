import asyncio
import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import ALLOWED_ORIGINS, APP_ENV, APP_NAME
from src.auth import get_current_user, SupabaseUser
from src.context_service import fetch_user_context
from src.rag_service import answer_query, refresh_user_vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title=APP_NAME, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    refresh: bool = False
    top_k: int = Field(default=5, ge=1)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class ChatQueryResponse(BaseModel):
    answer: str
    retrieved_docs: list[dict]
    prompt: str
    user_id: str


@app.get("/")
async def root() -> Any:
    return {"service": APP_NAME, "status": "ok", "environment": APP_ENV}


@app.get("/health")
async def healthcheck() -> Any:
    return {"status": "ok"}


@app.get("/api/chatbot/context/me")
async def get_chatbot_context(user: SupabaseUser = Depends(get_current_user)) -> Any:
    try:
        context = await asyncio.to_thread(fetch_user_context, user.id)
        response = {"success": True, "user_id": user.id, "data": context}
        logger.info("GET /api/chatbot/context/me response: %s", response)
        return response
    except Exception as exc:
        logger.exception("Error while fetching chatbot context for user %s", user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.post("/api/chatbot/query", response_model=ChatQueryResponse)
async def query_chatbot(
    request: Request,
    payload: ChatQueryRequest,
    user: SupabaseUser = Depends(get_current_user),
) -> Any:
    logger.info(
        "POST /api/chatbot/query request: user_id=%s query=%s top_k=%s score_threshold=%s refresh=%s",
        user.id,
        payload.query,
        payload.top_k,
        payload.score_threshold,
        payload.refresh,
    )

    if not payload.query.strip():
        logger.warning("Empty query received for user %s", user.id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="query must not be empty")

    if payload.refresh:
        try:
            context = await asyncio.to_thread(fetch_user_context, user.id)
            await asyncio.to_thread(refresh_user_vector_store, user.id, context)
            logger.info("Refreshed vector store for user %s", user.id)
        except Exception as exc:
            logger.exception("Error refreshing vector store for user %s", user.id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    try:
        result = await asyncio.to_thread(
            answer_query,
            user.id,
            payload.query,
            payload.top_k,
            payload.score_threshold,
        )
        logger.info("POST /api/chatbot/query response: %s", result)
    except Exception as exc:
        logger.exception("Error while answering query for user %s", user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return {"user_id": user.id, **result}
