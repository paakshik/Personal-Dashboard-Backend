import pytest
from unittest.mock import patch, Mock

def test_get_gmail_unauthorized(client):
    """Test Gmail endpoint without auth"""
    response = client.get("/dashboard/gmail")
    assert response.status_code == 401

def test_get_gmail_mock(authenticated_client, mock_google_creds):
    """Test Gmail with mock"""
    with patch('main.build') as mock_build:
        mock_service = Mock()
        mock_messages = Mock()
        mock_users = Mock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages
        
        # Mock list
        mock_list = Mock()
        mock_list.execute.return_value = {
            'messages': [
                {'id': 'msg1'},
                {'id': 'msg2'}
            ]
        }
        
        # Mock get
        mock_get = Mock()
        mock_get.execute.return_value = {
            'payload': {
                'headers': [
                    {'name': 'Subject', 'value': 'Test Subject'},
                    {'name': 'From', 'value': 'sender@test.com'},
                    {'name': 'Date', 'value': 'Mon, 1 Jan 2024 10:00:00'}
                ],
                'parts': []
            },
            'snippet': 'Test snippet',
            'labelIds': []
        }
        
        mock_messages.list.return_value = mock_list
        mock_messages.get.return_value = mock_get
        
        mock_build.return_value = mock_service
        
        response = authenticated_client.get("/dashboard/gmail")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) == 2

def test_get_email_content(authenticated_client, mock_google_creds):
    """Test getting email content"""
    with patch('main.build') as mock_build:
        mock_service = Mock()
        mock_messages = Mock()
        mock_users = Mock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages
        
        mock_get = Mock()
        mock_get.execute.return_value = {
            'id': 'msg1',
            'payload': {
                'headers': [
                    {'name': 'Subject', 'value': 'Test Email'},
                    {'name': 'From', 'value': 'test@example.com'},
                    {'name': 'Date', 'value': 'Mon, 1 Jan 2024'}
                ],
                'body': {'data': 'dGVzdCBjb250ZW50'},  # base64 for "test content"
                'parts': []
            },
            'snippet': 'Test snippet'
        }
        
        mock_messages.get.return_value = mock_get
        mock_build.return_value = mock_service
        
        response = authenticated_client.get("/dashboard/email/msg1")
        assert response.status_code == 200
        assert response.json()["subject"] == "Test Email"
        assert "body" in response.json()

def test_mark_email_as_read(authenticated_client, mock_google_creds):
    """Test marking email as read"""
    with patch('main.build') as mock_build:
        mock_service = Mock()
        mock_messages = Mock()
        mock_users = Mock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages
        
        mock_modify = Mock()
        mock_modify.execute.return_value = {}
        mock_messages.modify.return_value = mock_modify
        
        mock_build.return_value = mock_service
        
        response = authenticated_client.post("/dashboard/email/msg1/read")
        assert response.status_code == 200
        assert response.json()["status"] == "success"