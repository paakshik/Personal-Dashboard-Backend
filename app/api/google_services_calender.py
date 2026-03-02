from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.models import EventItem
from app.config import logger,sentry_sdk
from typing import List,Dict,Any,Optional
from app.utils.google_services_calender_helper import (classify_events_by_date,
                                                       get_google_calendar_service,
                                                       fetch_upcoming_events,
                                                       format_datetime,
                                                       search_calendar_events as search_helper)


router = APIRouter(prefix="/dashboard/calender", tags=["Google Services"])

time_default = '+00:00'

@router.get("/events", response_model=List[Dict[str, Any]])
def get_calendar_events(
    service: Any = Depends(get_google_calendar_service),  # <--- Auth is handled here
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Fetches the next 30 days of events from the user's primary Google Calendar.

    Events are grouped by date for easy frontend display.
    If the API fails or credentials are missing, it returns an empty list
    to prevent the dashboard from crashing (Graceful Degradation).

    Args:
        current_user (Dict[str, Any]): The authenticated user context.
        service (Any): The authenticated Google Calendar service (injected dependency).

    Returns:
        List[Dict[str, Any]]: A sorted list of date groups containing event details.
    """
    user_id = current_user.get("id", "unknown")

    try:
        # 1. Fetch Raw Data (Using the new helper)
        raw_events = fetch_upcoming_events(service, days=30)

        # 2. Classify / Group Data
        return classify_events_by_date(raw_events)

    except Exception as e:
        logger.error(f"Error retrieving calendar events for User {user_id}: {e}")
        sentry_sdk.capture_exception(e)
        return []

@router.get("/events/search", response_model=List[Dict[str, Any]])
def search_calendar_events(
    q: Optional[str],
    max_results: int,
    service: Any = Depends(get_google_calendar_service),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Search the user's primary Google Calendar events.

    This endpoint uses Google Calendar's built‑in search (`q` parameter) to filter
    events by title, description, and location. You can also restrict the time window
    with `timeMin` and `timeMax`. The results are grouped by date for easy display.

    Args:
        q: Optional search keyword.
        max_results: Maximum number of events (1‑2500).
        service: Authenticated Calendar service (injected).
        current_user: Authenticated user (injected).

    Returns:
        List of date‑grouped events (same structure as `GET /events`).
    """
    user_id = current_user.get("id", "unknown")
    logger.info(f"User {user_id} searching calendar events with q='{q}'")

    try:
        raw_events = search_helper(
            service=service,
            q=q,
            max_results=max_results
        )
        return classify_events_by_date(raw_events)

    except Exception as e:
        logger.error(f"Calendar search failed for user {user_id}: {e}")
        sentry_sdk.capture_exception(e)
        return []

@router.post("/events", response_model=Dict[str, Any])
def add_calendar_event(
    event: EventItem,
    service: Any = Depends(get_google_calendar_service),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Adds an event to the specified Google Calendar.

    Args:
        current_user (Dict[str, Any]): The authenticated user context.
        event (EventItem): The new data (summary, description, times).
        service (Any): The authenticated Google Calendar service (injected dependency).

    Returns:
        dict: The created event data as a dictionary.

    Raises:
        HTTPException: If an error occurs during the API call or if the data is invalid.
    """
    user_id = current_user.get("id", "unknown")
    logger.info(
        f"User {user_id} is attempting to create a calendar event: '{event.summary}'")

    try:
        # 1. Parse and Format Dates (Crucial Fix for Google API 400 Error)
        start_dt = event.start_time
        if isinstance(start_dt, str):
            start_dt = format_datetime(start_dt)

        end_dt = event.end_time
        if isinstance(end_dt, str):
            end_dt = format_datetime(end_dt)

        # 2. Validation: Ensure End is after Start
        if start_dt >= end_dt:
            raise HTTPException(status_code=400,
                                detail="End time must be after start time")

        body = {
            'summary': event.summary,
            'description': event.description,
            'location': event.location,
            'start': {
                'dateTime': start_dt,
                'timeZone': 'UTC'
            },
            'end': {
                'dateTime': end_dt,
                'timeZone': 'UTC'
            },
        }

        # 4. Execute API Call
        created_event = service.events().insert(
            calendarId='primary',
            body=body
        ).execute()

        event_id = created_event.get('id')
        logger.info(f"Successfully created Google Event {event_id} for User {user_id}")

        return {
            "status": "success",
            "message": "Event added to calendar",
            "id": event_id,
            "link": created_event.get('htmlLink')
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Critical error creating event for User {user_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create event: {str(e)}"
        )



@router.put("/events/{event_id}", response_model=Dict[str, Any])
def update_calendar_event(
    event_id: str,
    event: EventItem,
    service: Any = Depends(get_google_calendar_service),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Updates an existing Google Calendar event.

    It follows a "Fetch-Modify-Save" pattern:
    1. Fetches the current event from Google to preserve fields we aren't changing.
    2. Overwrites the fields provided in the payload.
    3. Pushes the update back to Google.

    Args:
        event_id (str): The unique Google Event ID.
        event (EventItem): The new data (summary, description, times).
        service (Any): The authenticated Google Calendar service (injected dependency).
        current_user (Dict[str, Any]): The authenticated user context.

    Returns:
        Dict[str, Any]: Success status and the updated event data.

    Raises:
        HTTPException (400): If credentials are missing or data is invalid.
        HTTPException (404): If the event ID does not exist in Google Calendar.
        HTTPException (500): If the system crashes.
    """
    user_id = current_user.get("id", "unknown")
    logger.info(f"User {user_id} updating calendar event {event_id}")

    try:
        existing_event = service.events().get(
            calendarId='primary',
            eventId=event_id
        ).execute()

        existing_event.update({
            'summary': event.summary,
            'description': event.description,
            'location': event.location,
        })

        existing_event['start'] = {'dateTime': event.start_time, 'timeZone': 'UTC'}
        existing_event['end'] = {'dateTime': event.end_time, 'timeZone': 'UTC'}

        updated_event = service.events().update(
            calendarId='primary',
            eventId=event_id,
            body=existing_event
        ).execute()

        logger.info(f"Successfully updated event {event_id} for User {user_id}")

        return {
            "status": "success",
            "message": "Event updated successfully",
            "data": updated_event
        }

    except Exception as e:
        logger.error(f"Critical error updating event {event_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=500,
            detail="System was unable to update the event."
        )


@router.delete("/events/{event_id}")
def delete_calendar_event(
        event_id: str,
        service: Any = Depends(get_google_calendar_service),
        current_user: dict = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Remove an event from the user's primary Google Calendar.

    This endpoint uses a helper dependency to ensure the user is authenticated
    with Google before attempting the deletion.

    Args:
        event_id (str): The Google-provided ID of the event to be deleted.
        service (Any): Authenticated Google Calendar service instance.
        current_user (dict): The current authenticated application user.

    Returns:
        Dict[str, str]: Success status and confirmation message.

    Raises:
        HTTPException: 400 if Google is not connected, or 500 for API failures.
    """
    user_id = current_user.get("id")

    try:
        # Execute the deletion on the 'primary' calendar
        service.events().delete(
            calendarId='primary',
            eventId=event_id
        ).execute()

        # Log the success for auditing
        logger.info(f"📅 Event {event_id} successfully deleted for user {user_id}")

        return {
            "status": "success",
            "message": f"Event {event_id} has been removed from your calendar."
        }

    except Exception as e:
        # Capture the error in Sentry for debugging
        sentry_sdk.capture_exception(e)

        # Log the specific error locally
        logger.error(
            f"❌ Failed to delete calendar event {event_id} for user {user_id}: {str(e)}",
            exc_info=True
        )

        raise HTTPException(
            status_code=400,
            detail="The system encountered an error while deleting the calendar event."
        )