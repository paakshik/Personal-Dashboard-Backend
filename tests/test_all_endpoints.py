import pytest
from starlette.websockets import WebSocketDisconnect

from app.db_store import save_project, save_command


def _configure_owner_email(monkeypatch, email: str):
    """Point both the config and owner_access modules at the given owner email."""
    import app.config as cfg
    import app.owner_access as oa

    monkeypatch.setattr(cfg, "DASHBOARD_OWNER_EMAIL", email or "")
    monkeypatch.setattr(oa, "DASHBOARD_OWNER_EMAIL", email or "")


def test_system_endpoints_missing_owner_email_returns_503(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "")
    # Valid auth is required so the request reaches the owner-config check;
    # without DASHBOARD_OWNER_EMAIL the endpoint returns 503.
    assert client.get("/dashboard/system/processes", headers=auth_headers).status_code == 503
    assert client.get("/dashboard/system/ports", headers=auth_headers).status_code == 503


def test_system_endpoints_owner_access_granted_to_owner(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "tester@example.com")
    assert client.get("/dashboard/system/processes", headers=auth_headers).status_code == 200
    assert client.get("/dashboard/system/ports", headers=auth_headers).status_code == 200


def test_system_endpoints_non_owner_gets_403(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "someone-else@example.com")
    assert client.get("/dashboard/system/processes", headers=auth_headers).status_code == 403
    assert client.get("/dashboard/system/ports", headers=auth_headers).status_code == 403


def test_owner_access_is_false_when_owner_email_unset(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "")
    response = client.get("/dashboard/owner-access", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"is_owner": False}


def test_owner_access_is_false_when_email_does_not_match(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "someone-else@example.com")
    response = client.get("/dashboard/owner-access", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"is_owner": False}


def test_owner_access_is_true_when_email_matches(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "tester@example.com")
    response = client.get("/dashboard/owner-access", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"is_owner": True}


@pytest.mark.parametrize("path", [
    "/dashboard/system/current",
    "/dashboard/system/info",
    "/dashboard/system/hardware",
    "/dashboard/system/network",
])
def test_system_endpoints_503_when_unset(client, auth_headers, path, monkeypatch):
    _configure_owner_email(monkeypatch, "")
    assert client.get(path, headers=auth_headers).status_code == 503, f"{path} returned unexpected status"


@pytest.mark.parametrize("path", [
    "/dashboard/system/current",
    "/dashboard/system/info",
    "/dashboard/system/hardware",
    "/dashboard/system/network",
])
def test_system_endpoints_200_for_owner(client, auth_headers, path, monkeypatch):
    _configure_owner_email(monkeypatch, "tester@example.com")
    assert client.get(path, headers=auth_headers).status_code == 200, f"{path} did not return 200 for owner"


@pytest.mark.parametrize("path", [
    "/dashboard/system/current",
    "/dashboard/system/info",
    "/dashboard/system/hardware",
    "/dashboard/system/network",
])
def test_system_endpoints_403_for_non_owner(client, auth_headers, path, monkeypatch):
    _configure_owner_email(monkeypatch, "someone-else@example.com")
    assert client.get(path, headers=auth_headers).status_code == 403, f"{path} did not return 403 for non-owner"


def _ws_ticket(headers, user_id, email):
    """Create a short-lived single-use WebSocket ticket for an authenticated user."""
    from app.dependencies import create_ws_ticket
    return create_ws_ticket(user_id, email)


def test_vitals_websocket_accepted_for_owner(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "tester@example.com")
    ticket_id = _ws_ticket(auth_headers, "test_user_123", "tester@example.com")
    with client.websocket_connect(f"/dashboard/system/vitals/stream?ticket={ticket_id}") as ws:
        data = ws.receive_json()
        assert "timestamp" in data


def test_vitals_websocket_rejected_for_non_owner(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "someone-else@example.com")
    ticket_id = _ws_ticket(auth_headers, "test_user_123", "tester@example.com")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/dashboard/system/vitals/stream?ticket={ticket_id}") as ws:
            ws.receive_json()
    assert exc_info.value.code == 1008


def test_vitals_websocket_rejected_when_owner_email_unset(client, auth_headers, monkeypatch):
    _configure_owner_email(monkeypatch, "")
    ticket_id = _ws_ticket(auth_headers, "test_user_123", "tester@example.com")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/dashboard/system/vitals/stream?ticket={ticket_id}") as ws:
            ws.receive_json()
    assert exc_info.value.code == 1008


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_swagger_docs_available(client):
    assert client.get("/docs").status_code == 200


def test_projects_list_scoped_to_user(client, auth_headers):
    user_id = auth_headers["X-Test-User"]
    save_project(user_id, {"name": "API Test Project", "description": "isolated", "progress": 20, "status": "planning", "technologies": [], "category": "web", "priority": "medium", "links": {}})
    response = client.get("/dashboard/projects", headers=auth_headers)
    assert response.status_code == 200
    assert any(p["name"] == "API Test Project" for p in response.json()["projects"])


def test_commands_list_scoped_to_user(client, auth_headers):
    user_id = auth_headers["X-Test-User"]
    save_command(user_id, {"name": "Test entry", "command": "echo test", "description": "test", "category": "general", "tags": []})
    response = client.get("/dashboard/commands", headers=auth_headers)
    assert response.status_code == 200
    assert any(row["name"] == "Test entry" for row in response.json())


def test_protected_endpoint_requires_auth(client):
    assert client.get("/dashboard/projects").status_code in (401, 403)


def test_frontend_expected_routes_are_mounted(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    from app.websockets.system_stream import router as system_stream_router
    websocket_paths = {route.path for route in system_stream_router.routes}
    assert "/health" in paths
    assert client.get("/docs").status_code == 200
    assert "/dashboard/system/processes" in paths
    assert "/dashboard/system/ports" in paths
    assert "/dashboard/system/vitals/stream" in websocket_paths


def test_system_process_and_port_endpoints(client):
    assert client.get("/dashboard/system/processes").status_code == 200
    assert client.get("/dashboard/system/ports").status_code == 200
