from app.db_store import save_project, save_command


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
    paths = {route.path for route in client.app.routes if hasattr(route, "path")}
    assert "/health" in paths
    assert "/docs" in paths
