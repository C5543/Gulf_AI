from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from fastapi.responses import FileResponse
from routes.analytics import router as analytics_router
from routes.chat import router as chat_router
from routes.logs import router as logs_router
from routes.student_message import router as student_message_router
from routes.withdrawal_start import router as withdrawal_start_router
from routes.withdrawal_complete import router as withdrawal_complete_router
from routes.support_ticket import router as support_ticket_router
from services.session_middleware import DatabaseSessionMiddleware


# =========================================================
# FastAPI Application
# =========================================================

app = FastAPI(
    title="Gulf College AI Assistant",
    version="1.0.0"
)


# =========================================================
# CORS
# حالياً مناسب للاختبار المحلي
# لاحقاً نضيف رابط السيرفر
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1",
        "http://localhost",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# MySQL Server-Side Sessions
# =========================================================

app.add_middleware(
    DatabaseSessionMiddleware,
    max_age=60 * 60 * 12
)


# =========================================================
# Routes
# =========================================================

app.include_router(chat_router)

app.include_router(logs_router)

app.include_router(student_message_router)

app.include_router(withdrawal_start_router)

app.include_router(withdrawal_complete_router)

app.include_router(support_ticket_router)

app.include_router(analytics_router)

# =========================================================
# Health Check
# =========================================================

@app.get("/health")
def health():
    return {
        "success": True,
        "service": "Gulf College AI Assistant",
        "status": "running",
        "version": "1.0.0"
    }

@app.get("/closing-message")
def get_closing_message():
    return {
        "success": True,
        "reply": "سعدنا بخدمتك في كلية الخليج. نتمنى لك يومًا سعيدًا.",
        "social_links": {
            "whatsapp": "https://api.whatsapp.com/send/?phone=%2B966920028505&type=phone_number&app_absent=0",
            "x": "https://x.com/gulfcolleges?s=11&t=QwiyXFXbeA9VVKwWbrIsOA",
            "linkedin": "https://www.linkedin.com/company/%D9%83%D9%84%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D8%AE%D9%84%D9%8A%D8%AC-gulfcolleges/"
        }
    }

# =========================================================
# Root
# =========================================================

@app.get("/")
def root():
    html_file = (
        Path(__file__).resolve().parent
        / "templates"
        / "index.html"
    )

    return FileResponse(html_file)