import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import sentry_sdk
import google.genai as genai

load_dotenv()


def setup_logging(log_dir_name: str = "logs") -> logging.Logger:
    log_dir = Path(__file__).resolve().parent.parent / log_dir_name
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
    return logging.getLogger("Personal Dashboard")


logger = setup_logging()


def require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def optional_env(key: str, default=None):
    return os.getenv(key, default)


SECRET_KEY = require_env("SECRET_KEY")
ALGORITHM = optional_env("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(optional_env("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
FRONTEND_URL = optional_env("FRONTEND_URL", "https://personal-dashboard-frontend-chi.vercel.app")
AUTHLIB_INSECURE_TRANSPORT = optional_env("AUTHLIB_INSECURE_TRANSPORT", "0")
CREDENTIALS_FILE = optional_env("CREDENTIALS_FILE", "credentials.json")
BACKEND_REDIRECT_URI = optional_env("BACKEND_REDIRECT_URI")
GOOGLE_CLIENT_ID = optional_env("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = optional_env("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = optional_env("GOOGLE_REDIRECT_URI", "")
REDIS_URL = optional_env("REDIS_URL")
ALLOWED_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if o.strip()
]
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

GEMINI_API_KEY = optional_env("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
DATA_DIR = Path(os.getenv("DATA_DIR", "dashboard_data"))
DATA_DIR.mkdir(exist_ok=True, parents=True)

# Todoist OAuth 2.0 authorization-code flow (per-user connection, replaces shared TODOIST_TOKEN)
TODOIST_CLIENT_ID = optional_env("TODOIST_CLIENT_ID", "")
TODOIST_CLIENT_SECRET = optional_env("TODOIST_CLIENT_SECRET", "")
TODOIST_REDIRECT_URI = optional_env("TODOIST_REDIRECT_URI", "")
TODOIST_AUTH_URL = optional_env("TODOIST_AUTH_URL", "https://app.todoist.com/oauth/authorize")
TODOIST_TOKEN_URL = optional_env("TODOIST_TOKEN_URL", "https://api.todoist.com/oauth/access_token")
TODOIST_SCOPES = optional_env("TODOIST_SCOPES", "task:read task:add task:update task:delete")
TODOIST_STATE_TTL_SECONDS = int(optional_env("TODOIST_STATE_TTL_SECONDS", 600))
DASHBOARD_OWNER_EMAIL = optional_env("DASHBOARD_OWNER_EMAIL", "").strip()
SENTRY_DSN = optional_env("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, environment=optional_env("ENVIRONMENT", "production"), traces_sample_rate=0.1, send_default_pii=False)
