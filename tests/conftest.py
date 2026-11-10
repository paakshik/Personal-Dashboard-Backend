import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "local-test-secret-key")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dashboard.sqlite")
os.environ.setdefault("DATA_DIR", str(ROOT / "test_data"))
os.environ.setdefault("GOOGLE_CLIENT_ID", "")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:8000/dashboard/auth/google/callback")
os.environ.setdefault("GEMINI_API_KEY", "")
# Owner email used to gate /dashboard/system/* endpoints and /dashboard/owner-access.
# Set so owner-gated endpoints are exerciseable in the test suite by default.
# Individual tests monkeypatch app.config/app.owner_access DASHBOARD_OWNER_EMAIL
# to exercise the unset / non-owner / owner branches.
os.environ.setdefault("DASHBOARD_OWNER_EMAIL", "tester@example.com")

import pytest
from unittest.mock import patch
from app.database import Base, engine
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def create_test_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_user_data():
    return {"id": "test_user_123", "email": "tester@example.com", "name": "Test User", "picture": ""}


@pytest.fixture
def mock_file_ops():
    with patch("app.utils.file_ops.read_json_file") as mocked:
        mocked.return_value = []
        yield mocked


@pytest.fixture
def auth_headers(mock_user_data):
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.config import SECRET_KEY, ALGORITHM
    from app.db_store import save_user_and_credentials
    save_user_and_credentials({**mock_user_data, "google_id": "google-test-user"}, {"access_token": "test-access", "refresh_token": "test-refresh", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "test-client", "client_secret": "test-secret", "scopes": []})
    token = jwt.encode({"sub": mock_user_data["id"], "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}, SECRET_KEY, algorithm=ALGORITHM)
    return {"Authorization": f"Bearer {token}", "X-Test-User": mock_user_data["id"]}
