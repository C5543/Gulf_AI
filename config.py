import os
from dotenv import load_dotenv


# تحميل متغيرات البيئة من ملف .env
load_dotenv()


# =========================
# OpenAI
# =========================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")


# =========================
# AI Server
# =========================

AI_PUBLIC_BASE_URL = os.getenv(
    "AI_PUBLIC_BASE_URL",
    "https://sisd.gulf.edu.sa/ai-test"
)

# =========================
# Database
# =========================

DB_HOST = os.getenv(
    "DB_HOST",
    ""
)

DB_PORT = int(
    os.getenv(
        "DB_PORT",
        "3306"
    )
)

DB_NAME = os.getenv(
    "DB_NAME",
    ""
)

DB_USER = os.getenv(
    "DB_USER",
    ""
)

DB_PASSWORD = os.getenv(
    "DB_PASSWORD",
    ""
)

# =========================
# Session
# =========================

SESSION_COOKIE_NAME = os.getenv(
    "SESSION_COOKIE_NAME",
    "gulf_ai_session"
)

SESSION_COOKIE_SECURE = (
    os.getenv(
        "SESSION_COOKIE_SECURE",
        "false"
    ).lower()
    == "true"
)
# =========================
# Taqnyat
# =========================

TAQNYAT_BEARER_TOKEN = os.getenv(
    "TAQNYAT_BEARER_TOKEN"
)


# =========================
# Logging
# =========================

AI_LOG_ENABLED = (
    os.getenv("AI_LOG_ENABLED", "true").lower()
    == "true"
)

AI_LOG_FULL_PAYLOAD = (
    os.getenv(
        "AI_LOG_FULL_PAYLOAD",
        "false"
    ).lower()
    == "true"
)

AI_LOG_VIEW_KEY = os.getenv(
    "AI_LOG_VIEW_KEY"
)


# =========================
# Bevatel
# =========================

BEVATEL_API_BASE_URL = os.getenv(
    "BEVATEL_API_BASE_URL",
    "https://chat.bevatel.com"
)

BEVATEL_ACCOUNT_ID = os.getenv(
    "BEVATEL_ACCOUNT_ID"
)

BEVATEL_INBOX_ID = os.getenv(
    "BEVATEL_INBOX_ID",
    ""
)

BEVATEL_API_TOKEN = os.getenv(
    "BEVATEL_API_TOKEN"
)

BEVATEL_API_TOKEN_HEADER = os.getenv(
    "BEVATEL_API_TOKEN_HEADER",
    "api_access_token"
)

BEVATEL_WEBHOOK_SECRET = os.getenv(
    "BEVATEL_WEBHOOK_SECRET"
)


# =========================
# WhatsApp
# =========================

AI_WHATSAPP_SESSION_SECRET = os.getenv(
    "AI_WHATSAPP_SESSION_SECRET"
)


# =========================
# Test Numbers
# =========================

BEVATEL_TEST_NUMBERS = os.getenv(
    "BEVATEL_TEST_NUMBERS",
    ""
)