import pytest
from unittest.mock import patch, MagicMock

# ============================================================================
# 1. SYSTEM & HEALTH TESTS
# ============================================================================

def test_health_check(client):
    """Verify the API is running."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "active"

def test_docs_exist(client):
    """Verify Swagger UI is accessible."""
    response = client.get("/docs")
    assert response.status_code == 200

# ============================================================================
# 2. PROJECT TESTS
# ============================================================================

def test_get_projects_unauthorized(client):
    """Should fail if no token is provided."""
    response = client.get("/dashboard/projects/projects")
    assert response.status_code == 403 or response.status_code == 401

def test_get_projects_success(client, auth_headers, mock_file_ops, mock_user_data):
    """Should return a list of projects for the logged-in user."""
    
    # Mock the JSON file to return one project belonging to this user
    mock_file_ops.return_value = [
        {
            "id": "proj_1",
            "user_id": mock_user_data["id"],
            "name": "Nexus Dashboard",
            "status": "in-progress",
            "progress": 80,
            "category": "dev",
            "priority": "high",
            "links": {}
        },
        {
            "id": "proj_2",
            "user_id": "other_user", # Should be filtered out
            "name": "Secret Project", 
            "status": "completed" 
        }
    ]

    response = client.get("/dashboard/projects/projects", headers=auth_headers)
    
    assert response.status_code == 200
    data = response.json()
    
    # Check structure
    assert "projects" in data
    assert "stats" in data
    
    # Ensure we only got the 1 project for this user
    assert len(data["projects"]) == 1
    assert data["projects"][0]["name"] == "Nexus Dashboard"
    
    # Check stats calculation
    assert data["stats"]["total"] == 1
    assert data["stats"]["inProgress"] == 1

# ============================================================================
# 3. COMMANDS TESTS
# ============================================================================

def test_get_commands(client, auth_headers, mock_file_ops, mock_user_data):
    """Test retrieving voice commands."""
    mock_file_ops.return_value = [
        {
            "id": "cmd_1",
            "user_id": mock_user_data["id"],
            "name": "Start Server",
            "command": "python run.py",
            "category": "dev"
        }
    ]
    
    response = client.get("/dashboard/commands/commands", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "Start Server"

# ============================================================================
# 4. GOOGLE SERVICES (MOCKED)
# ============================================================================

@patch("app.api.google_services_gmail.get_gmail_service")
def test_get_gmail_inbox(mock_get_service, client, auth_headers,mock_file_ops):
    """Test fetching emails (mocking Google API)."""
    
    # 1. Create a fake Gmail Service object
    mock_service = MagicMock()
    # Mock the chain: service.users().messages().list().execute()
    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg_1", "threadId": "th_1"}]
    }
    # Mock getting specific message details
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg_1",
        "snippet": "Hello World",
        "payload": {"headers": [{"name": "From", "value": "Mom"}]}
    }
    
    # 2. Inject the mock
    mock_get_service.return_value = mock_service

    # 3. Run Request
    response = client.get("/dashboard/gmail", headers=auth_headers)
    
    assert response.status_code == 200
    emails = response.json()
    assert len(emails) == 1
    assert emails[0]["from"] == "Mom"

@patch("app.api.google_services_calender.get_google_calendar_service")
def test_get_calendar_events(mock_get_service, client, auth_headers,mock_file_ops):
    """Test fetching calendar events."""
    
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {
        "items": [
            {
                "id": "evt_1",
                "summary": "Team Meeting",
                "start": {"dateTime": "2024-01-01T10:00:00+00:00"},
                "end": {"dateTime": "2024-01-01T11:00:00+00:00"},
                "htmlLink": "http://google.com/calendar"
            }
        ]
    }
    mock_get_service.return_value = mock_service

    response = client.get("/dashboard/calender/events", headers=auth_headers)
    
    assert response.status_code == 200
    # The endpoint returns a grouped list, so we check the structure
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["events"][0]["title"] == "Team Meeting"

# ============================================================================
# 5. TODOIST TESTS
# ============================================================================

@patch("requests.get")
def test_todoist_tasks(mock_requests_get, client, auth_headers,mock_file_ops):
    """Test fetching Todoist tasks."""
    
    # Mock the external API call to Todoist
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"id": "task_1", "content": "Buy Milk", "description": "2% fat"}
    ]
    mock_requests_get.return_value = mock_response

    response = client.get("/dashboard/todoist/tasks", headers=auth_headers)
    
    assert response.status_code == 200
    tasks = response.json()
    assert tasks[0]["content"] == "Buy Milk"

# ============================================================================
# 6. SYSTEM MONITORING
# ============================================================================

def test_system_metrics(client):
    """Test public system metrics endpoint."""
    # This might use psutil, which works locally, so usually safe to run real
    response = client.get("/dashboard/system/current")
    if response.status_code == 200:
        data = response.json()
        assert "cpu" in data
        assert "memory" in data