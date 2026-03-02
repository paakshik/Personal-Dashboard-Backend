from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.utils.google_services_gmail_helper import get_email_body,get_gmail_service
from typing import Any, Dict, List
from app.config import sentry_sdk,logger

router = APIRouter(prefix="/dashboard", tags=["Google Services"])

constants = {
    'constant1':'(No Subject)',
    'constant2': 'Unknown Sender'
}

@router.get("/gmail")
def get_gmail_inbox(
    service: Any = Depends(get_gmail_service),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Retrieves a summarized list of the latest 20 emails from the user's Gmail inbox.

    This endpoint uses the get_gmail_service dependency for authentication and
    initialization, then fetches and parses message metadata into a clean format.

    Args:
        service (Any): Authenticated Gmail API service (injected dependency).
        current_user (Dict[str, Any]): The authenticated app user session.

    Returns:
        List[Dict[str, Any]]: A list of processed email objects. Returns an empty
                              list if no emails are found or if an error occurs.
    """
    user_id = current_user.get("id")
    clean_emails: List[Dict[str, Any]] = []

    try:
        results = service.users().messages().list(userId='me', maxResults=20).execute()
        messages = results.get('messages', [])

        if not messages:
            logger.info(f"No messages found in inbox for user {user_id}")
            return []

        for msg in messages:
            try:
                email_meta = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='metadata'
                ).execute()

                headers = email_meta.get('payload', {}).get('headers', [])

                subject = next((h['value'] for h in headers if h['name'] ==
                                'Subject'), constants['constant1'])
                sender_raw = next((h['value'] for h in headers if h['name'] ==
                                   'From'), constants['constant2'])
                date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
                sender_clean = sender_raw.split('<')[0].strip().replace('"', '') if '<' in sender_raw else sender_raw

                clean_emails.append({
                    "id": msg['id'],
                    "subject": subject,
                    "sender": sender_clean,
                    "date": date_str,
                    "snippet": email_meta.get('snippet', ''),
                    "labels": email_meta.get('labelIds', [])
                })

            except Exception as inner_e:
                logger.warning(f"Failed to parse Gmail message {msg['id']} for user {user_id}: {inner_e}")
                sentry_sdk.capture_message(f"Failed to parse Gmail message "
                                           f"{msg['id']} for user {user_id}: "
                                           f"{inner_e}",level="warning")
                continue

        logger.info(f"📬 Successfully fetched and parsed {len(clean_emails)} emails for user {user_id}")
        return clean_emails

    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"❌ Critical Gmail Error for user {user_id}: {str(e)}", exc_info=True)
        return []

@router.get("/gmail/search")
def search_gmail(
    q: str,
    max_results: int,
    service: Any = Depends(get_gmail_service),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Search Gmail messages using Gmail's native search syntax.

    This endpoint leverages the Gmail API's `q` parameter, which supports the same
    operators as the Gmail web interface:
    - `from:someone@example.com`
    - `subject:"project update"`
    - `has:attachment`
    - `is:unread`
    - `after:2023/01/01`
    - `before:2024/01/01`

    Args:
        q (str): The search query.
        max_results (int): Maximum number of messages to return (1-100).
        service (Any): Authenticated Gmail service (injected).
        current_user (Dict[str, Any]): Authenticated user (injected).

    Returns:
        List[Dict[str, Any]]: A list of email objects with metadata (id, subject, sender, date, snippet, labels).

    Raises:
        HTTPException: 500 if the Gmail API call fails.
    """
    user_id = current_user.get("id")
    clean_emails: List[Dict[str, Any]] = []

    try:
        params:Dict[str, Any]= {
            'userId': 'me',
            'q': q,
            'maxResults': max_results
        }


        results = service.users().messages().list(**params).execute()
        messages = results.get('messages', [])

        if not messages:
            logger.info(f"No messages found for query '{q}' for user {user_id}")
            return []

        for msg in messages:
            try:
                email_meta = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='metadata'
                ).execute()

                headers = email_meta.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] ==
                                'Subject'), constants['constant1'])
                sender_raw = next((h['value'] for h in headers if h['name'] ==
                                   'From'), constants['constant2'])
                date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
                sender_clean = sender_raw.split('<')[0].strip().replace('"', '') if '<' in sender_raw else sender_raw

                clean_emails.append({
                    "id": msg['id'],
                    "subject": subject,
                    "sender": sender_clean,
                    "date": date_str,
                    "snippet": email_meta.get('snippet', ''),
                })

            except Exception as inner_e:
                logger.warning(f"Failed to parse Gmail message {msg['id']} for user {user_id}: {inner_e}")
                sentry_sdk.capture_message(f"Failed to parse Gmail message {msg['id']} during search", level="warning")
                continue

        logger.info(f"Gmail search returned {len(clean_emails)} messages for user {user_id}")
        return clean_emails

    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"Gmail search error for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Gmail search failed.")

@router.get("/gmail/{message_id}")
def get_email_content(
        message_id: str,
        service: Any = Depends(get_gmail_service),
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Retrieves the full content of a specific Gmail message, including headers and body.

    This endpoint uses the get_gmail_service dependency to fetch an authorized
    Gmail Resource. It parses the message payload to extract the Subject, Sender,
    and the processed body content.

    Args:
        message_id (str): The unique Gmail message identifier.
        service (Any): The authenticated Gmail service (injected dependency).
        current_user (Dict[str, Any]): The authenticated user session.

    Returns:
        Dict[str, Any]: A dictionary containing the formatted email details.

    Raises:
        HTTPException: 500 if the Gmail API call or body parsing fails.
    """
    user_id = current_user.get("id")

    try:
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()


        headers = message.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'),
                       '(No Subject)')
        sender = next((h['value'] for h in headers if h['name'] == 'From'),
                      'Unknown Sender')
        date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')

        email_data = {
            "id": message_id,
            "subject": subject,
            "sender": sender,
            "date": date_str,
            "body": get_email_body(message['payload']),
            "snippet": message.get('snippet', '')
        }

        return email_data

    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(
            f"❌ Email Content Error for user {user_id} on message {message_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve email content. The message may have been deleted."
        )


@router.post("/gmail/{message_id}/read")
def mark_email_as_read(
        message_id: str,
        service: Any = Depends(get_gmail_service),
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Mark a specific Gmail message as read by removing the 'UNREAD' label.

    This endpoint communicates with the Gmail API's modify method to update
    the label state of a message. It requires a valid Google OAuth token.

    Args:
        message_id (str): The unique identifier for the Gmail message.
        service (Any): The authenticated Gmail service (injected dependency).
        current_user (Dict[str, Any]): The authenticated user session.

    Returns:
        Dict[str, str]: Success status and confirmation message.

    Raises:
        HTTPException: 500 if the Gmail API call fails or message is not found.
    """
    user_id = current_user.get("id")

    try:
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()

        logger.info(f"📧 Message {message_id} marked as READ for user {user_id}")

        return {
            "status": "success",
            "message": "Email has been marked as read."
        }

    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(
            f"❌ Failed to mark email {message_id} as read for user {user_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to update email status. The message may have been moved or deleted."
        )

