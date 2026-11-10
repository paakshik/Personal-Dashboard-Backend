import time

import jwt
import pytest
import requests_mock

from app.config import SECRET_KEY, ALGORITHM
from app.db_store import (
    save_user_and_credentials,
    save_todoist_credential,
    get_todoist_credential,
    delete_todoist_credential,
)
from app.utils.encryption import encrypt, decrypt
from app.api.todoist_auth import _OAUTH_STATE, _OAUTH_STATE_LOCK


def _make_auth_headers(user_id, email):
    """Create a user in the DB and return auth headers with a valid JWT."""
    save_user_and_credentials(
        {
            "id": user_id,
            "google_id": f"google-{user_id}",
            "email": email,
            "name": "Test User",
            "picture": "",
        },
        {
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "scopes": [],
        },
    )
    token = jwt.encode(
        {"sub": user_id, "exp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + __import__("datetime").timedelta(minutes=15)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}", "X-Test-User": user_id}


@pytest.fixture(autouse=True)
def clear_oauth_state():
    """Keep the module-level OAuth state store clean across tests."""
    with _OAUTH_STATE_LOCK:
        _OAUTH_STATE.clear()
    yield
    with _OAUTH_STATE_LOCK:
        _OAUTH_STATE.clear()


class TestEncryption:
    def test_encryption_roundtrip(self):
        plaintext = "super-secret-access-token-12345"
        encrypted = encrypt(plaintext)
        assert set(encrypted.keys()) == {"nonce", "ciphertext", "tag"}
        assert decrypt(encrypted) == plaintext

    def test_encryption_tamper_detected(self):
        encrypted = encrypt("plaintext-value")
        # Tamper with the ciphertext while keeping the original tag.
        tampered = dict(encrypted)
        tampered["ciphertext"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        with pytest.raises(Exception):
            decrypt(tampered)


class TestTodoistCredentialCRUD:
    def test_todoist_credential_save_and_get(self, client):
        user_id = "todoist-user-a"
        _make_auth_headers(user_id, "a@example.com")

        tokens = {
            "access_token": "access-token-a",
            "refresh_token": "refresh-token-a",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client-id-a",
            "scopes": ["task:read", "task:add"],
            "expires_at": None,
        }
        assert save_todoist_credential(user_id, tokens) is True

        cred = get_todoist_credential(user_id)
        assert cred is not None
        assert cred["access_token"] == "access-token-a"
        assert cred["refresh_token"] == "refresh-token-a"
        assert cred["scopes"] == ["task:read", "task:add"]

        # User isolation: user B cannot read user A's credential.
        assert get_todoist_credential("todoist-user-b") is None

    def test_todoist_credential_delete(self, client):
        user_id = "todoist-user-delete"
        _make_auth_headers(user_id, "delete@example.com")

        assert save_todoist_credential(user_id, {"access_token": "tok"}) is True
        assert get_todoist_credential(user_id) is not None

        assert delete_todoist_credential(user_id) is True
        assert get_todoist_credential(user_id) is None
        # Deleting again returns False (row already gone).
        assert delete_todoist_credential(user_id) is False


class TestTodoistOAuth:
    def test_todoist_oauth_login_requires_auth(self, client):
        response = client.get("/dashboard/todoist/auth/login")
        assert response.status_code == 401

    def test_todoist_oauth_login_with_auth(self, client, monkeypatch):
        monkeypatch.setattr("app.api.todoist_auth.TODOIST_CLIENT_ID", "test-client-id")
        monkeypatch.setattr("app.api.todoist_auth.TODOIST_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setattr(
            "app.api.todoist_auth.TODOIST_REDIRECT_URI",
            "http://localhost:8000/dashboard/todoist/auth/callback",
        )

        user_id = "todoist-login-user"
        headers = _make_auth_headers(user_id, "login@example.com")

        response = client.get(
            "/dashboard/todoist/auth/login", headers=headers, follow_redirects=False
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert "app.todoist.com/oauth/authorize" in location
        assert "state=" in location
        assert "code_challenge=" in location
        assert "code_challenge_method=S256" in location
        assert "scope=" in location
        assert "redirect_uri=" in location

    def test_todoist_oauth_callback_invalid_state(self, client, monkeypatch):
        monkeypatch.setattr("app.api.todoist_auth.TODOIST_CLIENT_ID", "test-client-id")
        monkeypatch.setattr("app.api.todoist_auth.TODOIST_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setattr(
            "app.api.todoist_auth.TODOIST_REDIRECT_URI",
            "http://localhost:8000/dashboard/todoist/auth/callback",
        )

        response = client.get(
            "/dashboard/todoist/auth/callback?code=auth-code&state=unknown-state"
        )
        assert response.status_code == 400

    def test_todoist_oauth_callback_expired_state(self, client, monkeypatch):
        monkeypatch.setattr("app.api.todoist_auth.TODOIST_CLIENT_ID", "test-client-id")
        monkeypatch.setattr("app.api.todoist_auth.TODOIST_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setattr(
            "app.api.todoist_auth.TODOIST_REDIRECT_URI",
            "http://localhost:8000/dashboard/todoist/auth/callback",
        )

        # Insert an expired state entry directly (created_at 700s ago, TTL is 600s).
        with _OAUTH_STATE_LOCK:
            _OAUTH_STATE["expired-state"] = {
                "user_id": "todoist-user-a",
                "code_verifier": "verifier",
                "created_at": time.time() - 700,
            }

        response = client.get(
            "/dashboard/todoist/auth/callback?code=auth-code&state=expired-state"
        )
        assert response.status_code == 400

    def test_todoist_endpoint_403_when_not_connected(self, client):
        user_id = "todoist-no-cred"
        headers = _make_auth_headers(user_id, "nocred@example.com")

        response = client.get("/dashboard/todoist", headers=headers)
        assert response.status_code == 403

    def test_todoist_endpoint_user_isolation(self, client, monkeypatch):
        # User A has a Todoist credential; user B does not.
        user_a = "todoist-user-a"
        user_b = "todoist-user-b"
        headers_a = _make_auth_headers(user_a, "a@example.com")
        headers_b = _make_auth_headers(user_b, "b@example.com")

        save_todoist_credential(
            user_a,
            {"access_token": "access-token-a", "refresh_token": "refresh-token-a"},
        )

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.todoist.com/api/v1/tasks",
                json={"results": [{"id": "1", "content": "Task A"}]},
            )

            # User A's request uses user A's credential and succeeds.
            response_a = client.get("/dashboard/todoist", headers=headers_a)
            assert response_a.status_code == 200
            tasks = response_a.json()
            assert len(tasks) == 1
            assert tasks[0]["id"] == "1"
            assert tasks[0]["content"] == "Task A"

            # User B has no credential -> 403.
            response_b = client.get("/dashboard/todoist", headers=headers_b)
            assert response_b.status_code == 403
