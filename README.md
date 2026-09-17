# Gulf AI Assistant

An AI-powered Arabic assistant designed for a university environment. The application provides conversational support, university information, student-service workflows, support-ticket escalation, and administrative logging through a FastAPI backend and a web interface.

## Key Features

* Arabic conversational assistant.
* University knowledge retrieval.
* Conversation history and session management.
* Automatic inactivity closing message.
* Student support-ticket creation.
* Student message and request handling.
* Administrative logs and analytics.
* Withdrawal request workflows.
* Nafath integration-ready services.
* MySQL database integration.
* Responsive web interface.
* WhatsApp, X, and LinkedIn links.

## Technology Stack

* Python
* FastAPI
* MySQL
* OpenAI API
* HTML
* CSS
* JavaScript
* Jinja2 Templates
* Uvicorn

## Project Structure

```text
Gulf_AI/
├── data/
│   ├── official_knowledge.json
│   └── system_prompt.txt
├── routes/
│   ├── analytics.py
│   ├── chat.py
│   ├── logs.py
│   ├── student_message.py
│   ├── support_ticket.py
│   ├── withdrawal_start.py
│   └── withdrawal_complete.py
├── services/
│   ├── action_logger.py
│   ├── chat_logging.py
│   ├── knowledge_service.py
│   ├── nafath_bridge.py
│   ├── nafath_session.py
│   ├── openai_service.py
│   ├── program_service.py
│   ├── session_middleware.py
│   ├── student_service.py
│   └── text_utils.py
├── templates/
│   ├── index.html
│   ├── logs.html
│   └── logs_login.html
├── config.py
├── database.py
├── main.py
└── requirements.txt
```

## Installation

Clone the repository:

```bash
git clone https://github.com/C5543/Gulf_AI.git
cd Gulf_AI
```

Create a virtual environment:

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

## Environment Configuration

Create a local `.env` file and add the required database and API configuration values used by `config.py`.

Do not upload the `.env` file or expose API keys, database passwords, student information, or internal service credentials.

## Running the Application

```bash
python -m uvicorn main:app --reload --port 8000
```

Open the application in your browser:

```text
http://127.0.0.1:8000
```

## Development Status

The application currently includes the main FastAPI structure, user interface, routing, logging, support-ticket workflow, knowledge services, and integration-ready service modules.

External services such as the production database, OpenAI API, Nafath, SMS, and WhatsApp require valid credentials and deployment configuration.

## Security

Sensitive information is excluded through `.gitignore`. Production credentials must always be stored in environment variables and must never be committed to GitHub.

## Author

Developed by **Cady Almutairi** as part of practical experience in AI and backend application development.
