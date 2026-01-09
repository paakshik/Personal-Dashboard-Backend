# tests/conftest.py - Updated version
import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock
import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from jose import jwt

# Add the parent directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, init_data_files, get_current_user
from main import USERS_FILE, TOKENS_FILE, PROJECTS_FILE, COMMANDS_FILE

# Test configuration
os.environ["SECRET_KEY"] = "test-secret-key-for-tests-only"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["TODOIST_TOKEN"] = "test-todoist-token"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["FRONTEND_URL"] = "http://localhost:5173"
os.environ["BACKEND_REDIRECT_URI"] = "http://localhost:8000/auth/google/callback"

# Use temp directory for test data
TEST_DATA_DIR = Path(tempfile.mkdtemp())

# Create a test user for all tests
TEST_USER = {
    "id": "test-user-123",
    "google_id": "google-123",
    "email": "test@example.com",
    "name": "Test User",
    "picture": "https://test.com/photo.jpg",
    "created_at": "2024-01-01T00:00:00"
}

def create_test_token():
    """Create a test JWT token"""
    expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode = {
        "sub": TEST_USER["id"],
        "email": TEST_USER["email"],
        "exp": expire
    }
    return jwt.encode(to_encode, os.environ["SECRET_KEY"], algorithm=os.environ["ALGORITHM"])

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the session"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
def setup_test_data():
    """Setup and teardown test data"""
    # Backup original paths
    from main import DATA_DIR
    original_data_dir = DATA_DIR
    
    # Override with test directory
    import main
    main.DATA_DIR = TEST_DATA_DIR
    main.USERS_FILE = TEST_DATA_DIR / "users.json"
    main.TOKENS_FILE = TEST_DATA_DIR / "tokens.json"
    main.PROJECTS_FILE = TEST_DATA_DIR / "projects.json"
    main.COMMANDS_FILE = TEST_DATA_DIR / "commands.json"
    main.CHAT_HISTORY_FILE = TEST_DATA_DIR / "chat-data.json"
    
    # Create test directory
    TEST_DATA_DIR.mkdir(exist_ok=True)
    
    # Initialize with test user
    init_data_files()
    
    # Write test user to users file
    with open(main.USERS_FILE, 'w') as f:
        json.dump([TEST_USER], f)
    
    # Write test token
    test_token = create_test_token()
    tokens_data = {
        TEST_USER["id"]: {
            "access_token": test_token,
            "refresh_token": "test-refresh-token",
            "expires_at": (datetime.utcnow() + timedelta(minutes=30)).isoformat()
        }
    }
    with open(main.TOKENS_FILE, 'w') as f:
        json.dump(tokens_data, f)
    
    yield
    
    # Restore original
    main.DATA_DIR = original_data_dir

@pytest.fixture
def client():
    """Test client fixture"""
    return TestClient(app)

@pytest.fixture
def mock_google_creds():
    """Mock Google credentials"""
    with patch('main.Credentials') as mock_creds:
        mock_instance = Mock()
        mock_instance.token = "test-access-token"
        mock_instance.expired = False
        mock_instance.refresh_token = "test-refresh-token"
        mock_instance.token_uri = "https://oauth2.googleapis.com/token"
        mock_instance.client_id = "test-client-id"
        mock_instance.client_secret = "test-client-secret"
        mock_instance.scopes = ["test-scope"]
        mock_creds.return_value = mock_instance
        yield mock_instance

@pytest.fixture
def valid_token():
    """Generate valid JWT token"""
    return create_test_token()

@pytest.fixture
def authenticated_client(client, valid_token):
    """Client with authentication header"""
    # Override the get_current_user dependency
    async def override_get_current_user():
        return TEST_USER
    
    app.dependency_overrides[get_current_user] = override_get_current_user
    
    # Set auth header
    client.headers.update({"Authorization": f"Bearer {valid_token}"})
    
    yield client
    
    # Clean up after test
    app.dependency_overrides.clear()
# tests/conftest.py - Add these fixtures

# Add these to your existing conftest.py file:

@pytest.fixture
def test_command_data():
    """Create test command data"""
    return {
        "name": "Test Command",
        "command": "echo 'test'",
        "description": "A test command",
        "category": "general",
        "tags": ["test", "debug"]
    }

@pytest.fixture
def test_project_data():
    """Create test project data"""
    return {
        "name": "Test Project",
        "description": "A test project description",
        "progress": 50,
        "status": "in-progress",
        "technologies": ["Python", "FastAPI"],
        "category": "web",
        "priority": "medium",
        "lastUpdated": "2024-01-01",
        "links": {
            "github": "https://github.com/test",
            "database": "",
            "live": "",
            "api": ""
        }
    }

@pytest.fixture
def mock_current_user():
    """Mock authenticated user"""
    return {
        "id": "test-user-123",
        "email": "test@example.com",
        "name": "Test User"
    }
# Add this fixture to your conftest.py file
@pytest.fixture
def fake_user():
    """Create a fake user for testing"""
    return {
        "id": "test-user-id-123",
        "email": "test@example.com",
        "name": "Test User",
        "google_id": "google-test-id-456"
    }
@pytest.fixture
def fake_token():
    """Create a fake JWT token for testing"""
    return "fake.jwt.token.123"
