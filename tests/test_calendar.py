import pytest
from unittest.mock import patch, Mock

def test_get_calendar_events_unauthorized(client):
    """Test calendar endpoint without auth"""
    response = client.get("/dashboard/calendar")
    assert response.status_code == 401

def test_get_calendar_events_mock(authenticated_client, mock_google_creds):
    """Test calendar events with mock"""
    with patch('main.build') as mock_build:
        mock_service = Mock()
        mock_events = Mock()
        mock_service.events.return_value = mock_events
        
        mock_list = Mock()
        mock_list.execute.return_value = {
            'items': [
                {
                    'id': 'event1',
                    'summary': 'Test Meeting',
                    'description': 'Test description',
                    'start': {'dateTime': '2024-01-01T10:00:00Z'},
                    'end': {'dateTime': '2024-01-01T11:00:00Z'}
                }
            ]
        }
        mock_events.list.return_value = mock_list
        
        mock_build.return_value = mock_service
        
        response = authenticated_client.get("/dashboard/calendar")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

def test_add_calendar_event(authenticated_client, mock_google_creds):
    """Test adding calendar event"""
    with patch('main.build') as mock_build:
        mock_service = Mock()
        mock_events = Mock()
        mock_service.events.return_value = mock_events
        
        mock_insert = Mock()
        mock_insert.execute.return_value = {
            'id': 'new-event-123',
            'summary': 'Test Event'
        }
        mock_events.insert.return_value = mock_insert
        
        mock_build.return_value = mock_service
        
        event_data = {
            "summary": "Test Event",
            "start_time": "2024-01-01T10:00:00Z",
            "end_time": "2024-01-01T11:00:00Z",
            "description": "Test description",
            "location": "Test location"
        }
        
        response = authenticated_client.post(
            "/dashboard/calendar/events",
            json=event_data
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert "id" in response.json()

def test_update_calendar_event(authenticated_client, mock_google_creds):
    """Test updating calendar event"""
    with patch('main.build') as mock_build:
        mock_service = Mock()
        mock_events = Mock()
        mock_service.events.return_value = mock_events
        
        # Mock get
        mock_get = Mock()
        mock_get.execute.return_value = {
            'id': 'event1',
            'summary': 'Old Event',
            'start': {'dateTime': '2024-01-01T10:00:00Z'},
            'end': {'dateTime': '2024-01-01T11:00:00Z'}
        }
        
        # Mock update
        mock_update = Mock()
        mock_update.execute.return_value = {}
        
        mock_events.get.return_value = mock_get
        mock_events.update.return_value = mock_update
        
        mock_build.return_value = mock_service
        
        event_data = {
            "summary": "Updated Event",
            "start_time": "2024-01-01T12:00:00Z",
            "end_time": "2024-01-01T13:00:00Z",
            "description": "Updated description",
            "location": "Updated location"
        }
        
        response = authenticated_client.put(
            "/dashboard/calendar/events/event1",
            json=event_data
        )
        assert response.status_code == 200
        assert response.json()["status"] == "updated"

def test_delete_calendar_event(authenticated_client, mock_google_creds):
    """Test deleting calendar event"""
    with patch('main.build') as mock_build:
        mock_service = Mock()
        mock_events = Mock()
        mock_service.events.return_value = mock_events
        
        mock_delete = Mock()
        mock_delete.execute.return_value = {}
        mock_events.delete.return_value = mock_delete
        
        mock_build.return_value = mock_service
        
        response = authenticated_client.delete("/dashboard/calendar/events/event1")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"