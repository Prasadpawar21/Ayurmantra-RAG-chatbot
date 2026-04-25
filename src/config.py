import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "llama-3.1-8b-instant")
CHATBOT_TOP_K = int(os.getenv("CHATBOT_TOP_K", "5"))
CHATBOT_CONTEXT_FOOD_LOOKBACK_DAYS = int(os.getenv("CHATBOT_CONTEXT_FOOD_LOOKBACK_DAYS", "30"))

SUPABASE_PROFILE_TABLE = os.getenv("SUPABASE_PROFILE_TABLE", "profiles")
SUPABASE_CONSULTATION_TABLE = os.getenv("SUPABASE_CONSULTATION_TABLE", "consultation_appointments")
SUPABASE_FOODS_TABLE = os.getenv("SUPABASE_FOODS_TABLE", "foods")
SUPABASE_QUESTION_TABLE = os.getenv("SUPABASE_QUESTION_TABLE", "questions")
SUPABASE_OPTION_TABLE = os.getenv("SUPABASE_OPTION_TABLE", "options")
SUPABASE_QUIZ_SESSION_TABLE = os.getenv("SUPABASE_QUIZ_SESSION_TABLE", "quiz_sessions")
SUPABASE_RESPONSE_TABLE = os.getenv("SUPABASE_RESPONSE_TABLE", "responses")
SUPABASE_RESULT_TABLE = os.getenv("SUPABASE_RESULT_TABLE", "results")
SUPABASE_USER_ACTIVITY_TABLE = os.getenv("SUPABASE_USER_ACTIVITY_TABLE", "user_activity")
SUPABASE_USER_ACTIVITY_CREATED_AT_COLUMN = os.getenv("SUPABASE_USER_ACTIVITY_CREATED_AT_COLUMN", "consumed_at")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL must be set in the environment")

if not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY must be set in the environment")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY must be set in the environment")
