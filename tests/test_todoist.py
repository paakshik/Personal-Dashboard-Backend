import pytest
from unittest.mock import patch, Mock

def test_get_todoist_unauthorized(client):
    """Test Todoist endpoint without auth"""
    response = client.get("/dashboard/todoist")
    assert response.status_code == 401

def test_get_todoist_mock(authenticated_client):
    """Test Todoist with mock"""
    with patch('main.requests.get') as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                "id": "task1",
                "content": "Test Task",
                "description": "Task description",
                "project_id": 123,
                "due": {"date": "2024-01-01"},
                "labels": ["test"],
                "priority": 1,
                "is_completed": False
            }
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        response = authenticated_client.get("/dashboard/todoist")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) == 1
        assert response.json()[0]["content"] == "Test Task"

def test_add_todoist_task(authenticated_client):
    """Test adding Todoist task"""
    with patch('main.requests.post') as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {"id": "new-task-123", "content": "New Task"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        task_data = {
            "content": "New Task",
            "description": "Task description",
            "project_id": 123,
            "labels": ["urgent"]
        }
        
        response = authenticated_client.post(
            "/dashboard/todoist/tasks",
            json=task_data
        )
        assert response.status_code == 200
        assert "id" in response.json()

def test_complete_todoist_task(authenticated_client):
    """Test completing Todoist task"""
    with patch('main.requests.post') as mock_post:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        response = authenticated_client.post("/dashboard/todoist/tasks/task1/complete")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

def test_delete_todoist_task(authenticated_client):
    """Test deleting Todoist task"""
    with patch('main.requests.delete') as mock_delete:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_delete.return_value = mock_response
        
        response = authenticated_client.delete("/dashboard/todoist/tasks/task1")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"