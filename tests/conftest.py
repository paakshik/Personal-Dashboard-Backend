import pytest
import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch, DEFAULT

# 1. SETUP PATH & ENV VARS
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["SECRET_KEY"] = "test_secret_key"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["DATA_DIR"] = "test_data"

from app.main import app
from jose import jwt
from datetime import datetime, timedelta, timezone
from app.config import SECRET_KEY as APP_SECRET_KEY


# --- FIXTURES ---

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_user_data():
    return {
        "id": "test_user_123",
        "email": "tester@example.com",
        "name": "Test User",
        "picture": "http://example.com/pic.jpg"
    }


@pytest.fixture
def auth_headers(mock_user_data):
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode = {
        "sub": mock_user_data["id"],
        "email": mock_user_data["email"],
        "name": mock_user_data["name"],
        "exp": expire
    }
    token = jwt.encode(to_encode, APP_SECRET_KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_file_ops(mock_user_data):
    """
    SMART MOCK - Patch read_json_file in dependencies.py

    This handles:
    1. User authentication (users.json)
    2. Session validation (tokens.json)
    3. Projects/Commands/etc (test-specific)

    Key principle: Patch WHERE it's imported, not where it's defined
    """
    with patch("app.dependencies.read_json_file") as mock_read:

        def smart_side_effect(arg):
            path_str = str(arg)

            # 1. User authentication check
            if "users.json" in path_str:
                return [mock_user_data]

            # 2. SESSION CHECK (Critical for auth to pass)
            if "tokens.json" in path_str:
                return {
                    mock_user_data["id"]: {
                        "access_token": "test_google_token",
                        "refresh_token": "test_refresh_token",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "client_id": "test_client_id",
                        "client_secret": "test_client_secret",
                        "scopes": []
                    }
                }

            # 3. Check if test set specific return value
            if mock_read.return_value is not DEFAULT:
                return mock_read.return_value

            # 4. Default: Let test decide
            return DEFAULT

        mock_read.side_effect = smart_side_effect
        yield mock_read