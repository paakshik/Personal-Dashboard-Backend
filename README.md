# Personal Dashboard backend
The backend provides authenticated APIs for a personal productivity dashboard, including projects, commands, Google services, AI chat, and system metrics.
It is a Python FastAPI service intended to run locally or as the backend service for the React frontend.

> Status: PostgreSQL persistence and optional Redis caching are being introduced. Automated tests and remote Render connectivity must be confirmed in the deployment environment.

## Features
- FastAPI REST endpoints with Google OAuth sign-in and JWT-protected user APIs.
- SQLAlchemy persistence for users, Google credentials, projects, commands, AI chat, and system metric history.
- Optional Redis cache for read-heavy per-user collections; PostgreSQL remains authoritative.
- Google Calendar, Gmail, Drive, Todoist, and Gemini integrations when their credentials are configured.
- Health endpoint at `/health` and API documentation at `/docs`.

## Tech Stack
- Python 3.11 (Docker base image; confirm local Python with `python --version`).
- FastAPI, Uvicorn, SQLAlchemy 2, PostgreSQL, and psycopg2.
- Redis is optional and enabled with `REDIS_URL`.
- pytest is used for backend tests.

## Getting Started
### Prerequisites
- Python 3.11.
- PostgreSQL 14 or later (the exact Render engine version is not set in this repository).
- Optional Redis instance for caching.
- Google OAuth credentials for sign-in and Google APIs; optional Gemini and Todoist keys for those integrations.

### Install and configure
From `backend/`:

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env` with the values below. Keep real credentials local or in Render environment settings; do not commit them.

| Variable | Required | Example / purpose |
|---|---:|---|
| `DATABASE_URL` | Yes in production | `postgresql://USER:[REDACTED]@HOST:5432/DATABASE`; local fallback is `sqlite:///./dashboard-dev.db` |
| `SECRET_KEY` | Yes | Replace with a long random signing secret |
| `ALGORITHM` | No | `HS256` |
| `GOOGLE_CLIENT_ID` | For Google login | Placeholder from Google Cloud OAuth client |
| `GOOGLE_CLIENT_SECRET` | For Google login | Placeholder from Google Cloud OAuth client; secret only |
| `GOOGLE_REDIRECT_URI` | For Google login | `http://localhost:8000/dashboard/auth/google/callback` locally |
| `FRONTEND_URL` | No | `http://localhost:5173` |
| `REDIS_URL` | No | Redis connection URL; unset means PostgreSQL-only reads |
| `ALLOWED_ORIGINS` | No | Comma-separated frontend origins for CORS |
| `GEMINI_API_KEY` | For AI | Gemini API key |
| `TODOIST_TOKEN` | For Todoist | Todoist API token |
| `SENTRY_DSN` | No | Sentry project DSN |
| `DB_POOL_SIZE` | No | `5` pooled connections per process |
| `DB_MAX_OVERFLOW` | No | `5` temporary connections per process |
| `DB_POOL_TIMEOUT` | No | `5` seconds to wait for a connection |

### Database and run
Tables are created automatically during application startup. No seed data is required. For a fresh local PostgreSQL instance, create a database and set `DATABASE_URL` to its connection string, then run:

```bash
python run.py --host 127.0.0.1 --port 8000
```

Alternatively, from the repository root, run the backend container using the existing Dockerfile. **[PLACEHOLDER: Add the exact Render service start command and deployment URL after configuring the Render service.]**

## Usage
- Check service readiness: `GET http://localhost:8000/health`.
- Open Swagger UI: `http://localhost:8000/docs`.
- OAuth start: `GET /dashboard/auth/google/login`.
- Projects: `/dashboard/projects`.
- Commands: `/dashboard/commands`.
- AI history/upload: `/dashboard/gemini/history` and `/dashboard/gemini/upload`.
- AI streaming WebSocket: `/dashboard/gemini/stream?token=<JWT>`.
- Calendar events: `/dashboard/calendar/events`.
- Todoist tasks: `/dashboard/todoist`.

## API Documentation
Interactive documentation is served by FastAPI at `/docs`; ReDoc is at `/redoc`.
**[PLACEHOLDER: Add a published OpenAPI/Postman link if one is maintained.]**

## Design Decisions
- User-owned data is separated into normalized relational tables; projects and commands reference their owner by foreign key.
- JSON/JSONB-like columns are limited to variable-shaped fields such as project links, technology lists, command tags, Google scopes, and metric payloads.
- Timestamps use timezone-aware database columns. User emails and Google identities are unique; user-owned rows cascade on user removal.
- SQLAlchemy uses bounded pooling with health checks and finite wait time. Configure `DB_POOL_SIZE × worker count + DB_MAX_OVERFLOW × worker count` below the database connection limit.
- Redis is a disposable cache, not the source of truth. Cache reads must fall back to PostgreSQL if Redis is missing or unavailable, and writes invalidate cached user collections.
- `create_all` supports first-run table creation, not production schema evolution. **[PLACEHOLDER: Add versioned Alembic migration workflow before changing deployed schemas.]**
- **[PLACEHOLDER: Create a least-privilege Render database role and document grants once the production database is provisioned.]**
- **[PLACEHOLDER: Configure and test Render backups/point-in-time recovery; the application cannot configure provider backups itself.]**

## Testing
Run backend tests from `backend/`:

```bash
pytest
```

**[PLACEHOLDER: Add PostgreSQL integration-test service and record the measured coverage after the test suite is run against PostgreSQL.]**

## Deployment
Target platform: Render Web Service with a Render PostgreSQL database. Set `DATABASE_URL`, signing key, frontend URL, Google OAuth values, and optional integration credentials in the service environment. Keep the database private and connect using Render's private/internal address when the web service is in the same region.

**Deployment status: [PLACEHOLDER: Not verified from this repository; enter the live backend URL and deploy status.]**

## Troubleshooting
- `Missing required environment variable: SECRET_KEY`: set `SECRET_KEY` in `.env` or the Render environment.
- OAuth redirect mismatch: ensure the Google OAuth allowed callback exactly matches `GOOGLE_REDIRECT_URI`.
- Database connection failure: verify the URL, host access, credentials, SSL requirements, and that the database is running.
- `503 Database is busy`: lower web worker count, inspect pool limits, or increase database capacity; do not remove the finite pool timeout.
- Redis connection errors: check `REDIS_URL`; caching should fall back to PostgreSQL while Redis is unavailable.
- Google/Gemini/Todoist integration errors: provide the corresponding credentials; those third-party services are not replaced by the database.

## License
**[PLACEHOLDER: Add the project license and copyright holder.]**
