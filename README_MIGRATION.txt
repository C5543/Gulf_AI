Gulf College AI - PHP chat.php to Python/FastAPI migration

This folder contains the converted large chat.php logic split into logical modules.

Main files:
- main.py                         FastAPI application
- database.py                     MySQL connection pool
- config.py                       Reads .env only; no secrets are hard-coded
- routes/chat.py                  Main chat flow: reset/history/message
- services/text_utils.py          Arabic normalization, intent/rule helpers
- services/chat_logging.py        Conversation/message/OpenAI logging
- services/action_logger.py       Logging for actions outside chat
- services/knowledge_service.py   ai_knowledge + official knowledge retrieval
- services/program_service.py     Programs, study plans, matching, training
- services/student_service.py     Applicant/student, finance, GPA, packages, withdrawal/refund state
- services/openai_service.py      Intent classifier + final OpenAI Responses call
- services/session_middleware.py  Server-side MySQL session storage
- data/official_knowledge.json    Official hard-coded knowledge moved out of chat.php
- data/system_prompt.txt          The original long system prompt moved out of chat.php

Before running:
1) Copy your existing .env into this folder.
2) Add MySQL settings taken from the company's existing global.php configuration:
   DB_HOST=...
   DB_PORT=3306
   DB_NAME=...
   DB_USER=...
   DB_PASSWORD=...

Do not put those values in database.py and do not commit .env to GitHub.

Install:
python -m pip install -r requirements.txt

Run locally/server test:
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

Check:
http://127.0.0.1:8000/health

Frontend change:
Replace fetch('chat.php', ...) with fetch('/chat', ...).
The JSON contract remains compatible:
- {"action":"reset"}
- {"action":"history"}
- {"message":"..."}

Withdrawal action links produced by Python now use /withdrawal/start.
SMS resend action links now use /resend-student-message once that route is included in main.py.

Important migration note:
The PHP source contained an uninitialized $sms_body in ai_build_queue_context and an unrelated $row reference at the top of ai_official_knowledge_entries. The Python conversion fixes this by reading and cleaning body_sms directly from the queue row.

Testing status:
- All Python files were syntax-compiled.
- The full source prompt and official knowledge were preserved as data files.
- The database-dependent runtime has NOT been executed against the company MySQL database in this environment because company DB credentials/network are not available here.
- Keep the PHP version in place as rollback until the Python version passes company-server testing.
