
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from app.services.google_auth import get_user_google_creds
from app.dependencies import get_current_user
from fastapi import Depends, HTTPException, status
from app.config import logger,sentry_sdk
from typing import Any,List,Dict

time_default = '+00:00'

def get_google_calendar_service(
    current_user: dict = Depends(get_current_user)
) -> Any:
    """
    Dependency helper to initialize an authenticated Google Calendar service.

    Args:
        current_user: The authenticated user from the session.

    Returns:
        A Google Calendar API service instance.
    """
    user_id = current_user.get("id")

    # 1. Verify Identity & Credentials
    creds = get_user_google_creds(user_id)

    if not creds:
        # Automatic 400 error if account is not linked
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected. Please link your account."
        )

    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"Failed to build Google Calendar service for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect to Google Calendar service."
        )


def fetch_upcoming_events(service: Any, days: int = 30) -> List[Dict[str, Any]]:
    """
    Fetches raw event data from the user's primary Google Calendar using the provided service.

    This function is decoupled from authentication and focuses strictly on the
    API communication and data retrieval.

    Args:
        service (Any): The authenticated Google Calendar API service instance.
        days (int): The number of days in the future to fetch events for (default: 30).

    Returns:
        List[Dict[str, Any]]: A list of raw event items from Google.

    Raises:
        Exception: Re-raises API exceptions after logging to Sentry and local logs.
    """
    try:
        now = datetime.now(timezone.utc).isoformat().replace(time_default, 'Z')
        end_time = (datetime.now(timezone.utc) + timedelta(
            days=days)).isoformat().replace(time_default, 'Z')

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=end_time,
            maxResults=50,  # Increased limit for better visibility
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        logger.info(
            f"Successfully fetched {len(events)} raw events from Google Calendar.")

        return events

    except Exception as e:
        logger.error(f"Google API Error during fetch: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        raise e

def classify_events_by_date(raw_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transforms raw Google Calendar event items into a grouped, UI-friendly format.

    This function iterates through raw API responses, extracts date/time information,
    and buckets events into dictionaries keyed by their calendar date.

    Args:
        raw_events (List[Dict[str, Any]]): A list of 'item' dictionaries from the
                                           Google Calendar events.list response.

    Returns:
        List[Dict[str, Any]]: A list of date groups, sorted chronologically.
                              Example: [{"date_display": "Monday...", "events": [...]}]
    """
    classified_events = {}

    for event in raw_events:
        try:
            start_raw = event['start'].get('dateTime', event['start'].get('date'))

            # Handle 'T' split safely
            date_key = start_raw.split('T')[0] if 'T' in start_raw else start_raw

            # Format Time
            time_display = "All Day"
            if 'dateTime' in event['start']:
                try:
                    dt = datetime.fromisoformat(start_raw)
                    time_display = dt.strftime('%H:%M')
                except (ValueError, TypeError) as e:
                    logger.warning(f"Time parsing failed for event {event.get('id')}: {e}")
                    time_display = "Time Error"

            event_data = {
                "id": event['id'],
                "title": event.get('summary', 'No Title'),
                "description": event.get('description', ''),
                "location": event.get('location', ''),
                "time": time_display,
                "start_raw": start_raw,
                "link": event.get('htmlLink', '')
            }

            if date_key not in classified_events:
                try:
                    date_obj = datetime.strptime(date_key, '%Y-%m-%d')
                    date_pretty = date_obj.strftime('%A, %B %d, %Y')
                except ValueError:
                    date_pretty = date_key

                classified_events[date_key] = {
                    "date_key": date_key,
                    "date_display": date_pretty,
                    "events": []
                }

            classified_events[date_key]["events"].append(event_data)
        except Exception as e:
            logger.error(f"Failed to classify individual event: {str(e)}")
            sentry_sdk.capture_exception(e)
            continue
    return [classified_events[k] for k in sorted(classified_events.keys())]


def format_datetime(datetime_str: str) -> str:
    """
    Formats the datetime string to ISO format for Google Calendar.

    Args:
        datetime_str (str): The datetime string to format (e.g., "2024-01-01T12:00:00Z").

    Returns:
        str: The formatted datetime string in ISO format (e.g., "2024-01-01T12:00:00").
    """
    # Handle "Z" and make sure the "T" separator is present
    if datetime_str.endswith("Z"):
        datetime_str = datetime_str[:-1]  # Remove "Z"
    if "T" not in datetime_str:
        datetime_str = datetime_str.replace(" ", "T")  # Replace space with "T"
    try:
        # Parse the datetime string and format it to remove the timezone info
        return datetime.fromisoformat(datetime_str).isoformat()
    except ValueError:
        # Handle potential parsing errors
        raise ValueError(f"Invalid datetime format: {datetime_str}")