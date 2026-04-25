# RAG Model 2

This repository is a Python FastAPI backend for a Supabase-powered RAG chatbot using Groq.

## What is included

- FastAPI backend server
- Supabase auth validation via `Authorization: Bearer <token>`
- Supabase user-context fetcher with profiles, assessments, food activity, and consultations
- Document creation and in-memory RAG store per user
- Groq embeddings and chat completions
- CORS enabled for React frontend integration

## Run locally

1. Copy `.env.example` to `.env` and set your values.
2. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Start the server:

```powershell
python main.py --port 5000
```

4. Open your frontend and call the backend at:

- `GET http://localhost:5000/api/chatbot/context/me`
- `POST http://localhost:5000/api/chatbot/query`

## Required environment variables

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GROQ_API_KEY`

## Frontend contract

### Context endpoint

`GET /api/chatbot/context/me`

- Requires `Authorization: Bearer <token>` header
- Returns full user context from Supabase

### Query endpoint

`POST /api/chatbot/query`

Body:

```json
{
  "query": "What should this user eat for digestion?",
  "refresh": false,
  "top_k": 5,
  "score_threshold": 0.1
}
```

Response:

- `answer`
- `retrieved_docs`
- `prompt`

## Notes

- This repo uses an in-memory vector store. For production, replace it with Redis, SQLite, or Chroma.
- The Supabase auth layer validates tokens using the Supabase admin endpoint.
- The prompt construction makes the chatbot answer only from retrieved user-specific documents.
