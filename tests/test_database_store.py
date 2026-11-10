from app.database import Base, engine
from app.db_store import save_user_and_credentials, save_project, list_projects, save_chat_message, list_chat_messages, clear_chat_messages


def test_user_project_and_chat_persistence():
    Base.metadata.create_all(bind=engine)
    user_id = "integration-test-user"
    user, _ = save_user_and_credentials(
        {"id": user_id, "google_id": f"google-{user_id}", "email": f"{user_id}@example.com", "name": "Test User", "picture": ""},
        {"access_token": "test-access", "refresh_token": "test-refresh", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "test-client", "client_secret": "test-secret", "scopes": []},
    )
    assert user["id"] == user_id

    project = save_project(user_id, {"name": "Test Project", "description": "DB round trip", "progress": 35, "status": "planning", "technologies": ["Python"], "category": "web", "priority": "medium", "links": {}})
    assert any(row["id"] == project["id"] for row in list_projects(user_id))

    message = save_chat_message("user", "test question", user_id)
    assert any(row["id"] == message["id"] for row in list_chat_messages(user_id))
    assert clear_chat_messages(user_id) >= 1
