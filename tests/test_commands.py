import pytest

def test_get_commands_unauthorized(client):
    """Test getting commands without auth"""
    response = client.get("/dashboard/commands")
    assert response.status_code == 401


def test_get_commands(authenticated_client):
    """Test getting all commands"""
    response = authenticated_client.get("/dashboard/commands")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_specific_command(authenticated_client):
    """Test getting a specific command"""
    # First, create a command
    command_data = {
        "name": "Test Command",
        "command": "echo test",
        "description": "A test command",
        "category": "general",
        "tags": ["test"]
    }
    
    create_response = authenticated_client.post(
        "/dashboard/commands",
        json=command_data
    )
    assert create_response.status_code == 200
    created_command = create_response.json()["command"]
    command_id = created_command["id"]
    
    # Now get the specific command
    response = authenticated_client.get(f"/dashboard/commands/{command_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Command"


def test_create_command_unauthorized(client):
    """Test creating command without auth"""
    command_data = {
        "name": "Test",
        "command": "echo test",
        "description": "Test",
        "category": "general",
        "tags": []
    }
    response = client.post("/dashboard/commands", json=command_data)
    assert response.status_code == 401


def test_create_command(authenticated_client):
    """Test creating a new command"""
    command_data = {
        "name": "List Files",
        "command": "ls -la",
        "description": "List all files",
        "category": "system",
        "tags": ["files", "list"]
    }
    
    response = authenticated_client.post(
        "/dashboard/commands",
        json=command_data
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["command"]["name"] == "List Files"


def test_update_command(authenticated_client):
    """Test updating a command"""
    # Create first
    command_data = {
        "name": "Old Name",
        "command": "echo old",
        "description": "Old description",
        "category": "general",
        "tags": []
    }
    
    create_response = authenticated_client.post(
        "/dashboard/commands",
        json=command_data
    )
    command_id = create_response.json()["command"]["id"]
    
    # Update
    updated_data = {
        "name": "New Name",
        "command": "echo new",
        "description": "New description",
        "category": "general",
        "tags": ["updated"]
    }
    
    response = authenticated_client.put(
        f"/dashboard/commands/{command_id}",
        json=updated_data
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["command"]["name"] == "New Name"


def test_delete_command(authenticated_client):
    """Test deleting a command"""
    # Create first
    command_data = {
        "name": "To Delete",
        "command": "echo delete",
        "description": "Will be deleted",
        "category": "general",
        "tags": []
    }
    
    create_response = authenticated_client.post(
        "/dashboard/commands",
        json=command_data
    )
    command_id = create_response.json()["command"]["id"]
    
    # Delete
    response = authenticated_client.delete(f"/dashboard/commands/{command_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    
    # Verify it's gone
    get_response = authenticated_client.get(f"/dashboard/commands/{command_id}")
    assert get_response.status_code == 404


def test_create_command_validation(authenticated_client):
    """Test command validation"""
    # Test with dangerous command
    dangerous_command = {
        "name": "Dangerous",
        "command": "rm -rf /",
        "description": "Dangerous command",
        "category": "general",
        "tags": []
    }
    
    response = authenticated_client.post(
        "/dashboard/commands",
        json=dangerous_command
    )
    
    assert response.status_code == 400
    assert "dangerous" in response.json()["detail"].lower()