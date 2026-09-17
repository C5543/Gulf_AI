from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime
from pathlib import Path

import sqlite3
import uuid


router = APIRouter(
    tags=["Support Tickets"]
)


# =========================================================
# Local SQLite Database
# Demo only - later will be replaced with university MySQL
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE = DATA_DIR / "support_tickets.db"


# =========================================================
# Create Tickets Table
# =========================================================

def create_table():

    connection = sqlite3.connect(DATABASE)
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT UNIQUE NOT NULL,
            title TEXT,
            message TEXT NOT NULL,
            user_name TEXT,
            student_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # لو الجدول قديم وما فيه title نضيفه
    cursor.execute(
        "PRAGMA table_info(tickets)"
    )

    columns = [
        row[1]
        for row in cursor.fetchall()
    ]

    if "title" not in columns:

        cursor.execute(
            """
            ALTER TABLE tickets
            ADD COLUMN title TEXT
            """
        )

    connection.commit()
    connection.close()


create_table()


# =========================================================
# Request Model
# =========================================================

class SupportRequest(BaseModel):

    title: str
    message: str

    user_name: str | None = None
    student_id: str | None = None


# =========================================================
# Create Ticket
# =========================================================

@router.post("/create-ticket")
def create_ticket(
    data: SupportRequest
):

    ticket_id = (
        "TKT-"
        + uuid.uuid4().hex[:8].upper()
    )

    created_at = datetime.now().isoformat()

    connection = sqlite3.connect(DATABASE)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO tickets (
            ticket_id,
            title,
            message,
            user_name,
            student_id,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            data.title,
            data.message,
            data.user_name,
            data.student_id,
            "open",
            created_at
        )
    )

    connection.commit()
    connection.close()

    return {
        "success": True,

        "reply": (
            "تم رفع طلبك للدعم الفني "
            f"برقم {ticket_id}."
        ),

        "ticket": {
            "ticket_id": ticket_id,
            "title": data.title,
            "message": data.message,
            "user_name": data.user_name,
            "student_id": data.student_id,
            "status": "open",
            "created_at": created_at
        }
    }


# =========================================================
# Get Tickets
# =========================================================

@router.get("/tickets")
def get_tickets():

    connection = sqlite3.connect(DATABASE)

    connection.row_factory = (
        sqlite3.Row
    )

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *
        FROM tickets
        ORDER BY id DESC
        """
    )

    rows = cursor.fetchall()

    connection.close()

    tickets = [
        dict(row)
        for row in rows
    ]

    return {
        "success": True,
        "count": len(tickets),
        "tickets": tickets
    }