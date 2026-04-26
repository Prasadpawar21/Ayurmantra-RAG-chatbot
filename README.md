# RAG Model 2

`RAG Model 2` is a FastAPI backend for a user-specific health chatbot. It pulls authenticated user data from Supabase, builds in-memory RAG documents from profile and activity records, retrieves relevant context with a lightweight lexical retriever, and answers queries with Groq.

## Stack

- Python 3.11
- FastAPI + Uvicorn
- Supabase REST + auth validation
- lightweight in-process lexical retrieval
- Groq chat completions for final answers

## Features

- Validates Supabase bearer tokens on every protected request
- Fetches user context from multiple Supabase tables
- Builds user-specific documents for profile, assessments, food logs, consultations, and artifacts
- Stores a lightweight retrieval index in memory per user for fast repeated queries
- Supports context refresh on demand
- Includes `/` and `/health` endpoints for platform health checks
- Includes a `render.yaml` blueprint for deployment

## Project structure

```text
.
|-- main.py
|-- requirements.txt
|-- render.yaml
|-- src/
|   |-- api.py
|   |-- auth.py
|   |-- config.py
|   |-- context_service.py
|   `-- rag_service.py
`-- .env.example
```

## Environment variables

Required:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GROQ_API_KEY`

Optional:

- `APP_NAME`
- `APP_ENV`
- `ALLOWED_ORIGINS`
- `GROQ_CHAT_MODEL`
- `CHATBOT_TOP_K`
- `CHATBOT_CONTEXT_FOOD_LOOKBACK_DAYS`
- `SUPABASE_PROFILE_TABLE`
- `SUPABASE_CONSULTATION_TABLE`
- `SUPABASE_FOODS_TABLE`
- `SUPABASE_QUESTION_TABLE`
- `SUPABASE_OPTION_TABLE`
- `SUPABASE_QUIZ_SESSION_TABLE`
- `SUPABASE_RESPONSE_TABLE`
- `SUPABASE_RESULT_TABLE`
- `SUPABASE_USER_ACTIVITY_TABLE`
- `SUPABASE_USER_ACTIVITY_CREATED_AT_COLUMN`

Start from [.env.example](/e:/Dev/Projects/RAG_Model_2/.env.example).

## Local development

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in your real credentials.
4. Run the API:

```bash
python main.py
```

The server listens on `http://localhost:5000` by default.

## API endpoints

### `GET /`

Basic service metadata.

### `GET /health`

Deployment health check endpoint.

### `GET /api/chatbot/context/me`

Returns the authenticated user's normalized context.

Headers:

```http
Authorization: Bearer <supabase_access_token>
```

### `POST /api/chatbot/query`

Answers a question using the authenticated user's RAG context.

Request body:

```json
{
  "query": "What food patterns show up in this user's recent activity?",
  "refresh": false,
  "top_k": 5,
  "score_threshold": 0.0
}
```

Response fields:

- `answer`
- `retrieved_docs`
- `prompt`
- `user_id`

## Deployment

### Render

This repo includes [render.yaml](/e:/Dev/Projects/RAG_Model_2/render.yaml), so Render can create the web service with:

- Build command: `pip install --upgrade pip && pip install -r requirements.txt`
- Start command: `uvicorn src.api:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`

You still need to set the secret env vars in Render:

- `ALLOWED_ORIGINS`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GROQ_API_KEY`

## Production notes

- The vector store is in memory only. It resets on every deploy, restart, or instance replacement.
- Retrieval is lexical instead of embedding-based, which keeps memory usage low enough for smaller Render instances.
- This service depends on external APIs from both Supabase and Groq, so production reliability is partly downstream.
- The service role key is highly privileged. Keep it only in server-side environment variables.

## Recommended next upgrade

For stronger production readiness, move retrieval storage out of process into Redis, Postgres with pgvector, or another persistent vector store if you want semantic search later.
