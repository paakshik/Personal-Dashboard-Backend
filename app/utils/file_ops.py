import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from app.services.google_auth import get_user_google_creds
import json
from app.config import (USERS_FILE, TOKENS_FILE, PROJECTS_FILE, COMMANDS_FILE,
                        CHAT_HISTORY_FILE,  SYSTEM_METRICS_FILE,logger,sentry_sdk)
from pathlib import Path
from typing import Any, Union, List, Dict

def read_json_file(file_path: Union[str, Path]) -> Union[
    List[Any], Dict[str, Any], None]:
    """
    Read JSON file and return its content.

    Args:
        file_path: Path to JSON file (string or Path object)

    Returns:
        - List for user/project/command/chat files
        - Dict for tokens file
        - None for other files if they don't exist

    Behavior:
        - Returns empty list [] for user/project/command/chat files if file doesn't exist
        - Returns empty dict {} for tokens file if file doesn't exist
        - Returns None for other files if they don't exist
        - Returns default on JSON decode errors
    """
    """Read JSON file, return default if file doesn't exist or is invalid"""
    path_obj = Path(file_path)

    # 1. LAZY INIT: Check if file exists
    if not path_obj.exists():
        default_data = None

        # Determine default structure based on file type
        if path_obj == TOKENS_FILE:
            default_data = {}
        elif path_obj in [USERS_FILE, PROJECTS_FILE, COMMANDS_FILE, CHAT_HISTORY_FILE,
                          SYSTEM_METRICS_FILE]:
            default_data = []

        # If it's a known file type, create it physically now
        if default_data is not None:
            try:
                # Ensure the folder exists (e.g., dashboard_data/)
                path_obj.parent.mkdir(parents=True, exist_ok=True)

                # Create the actual file with empty JSON
                with open(path_obj, 'w',encoding='utf-8') as f:
                    json.dump(default_data, f)

                logger.info(f"Lazy Initialized new data file: {path_obj}")
                return default_data
            except OSError as e:
                logger.error(f"Failed to lazy create {path_obj}: {e}")
                return default_data  # Return in-memory empty data as fallback

        return None

    # 2. Normal Read
    try:
        with open(path_obj, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error reading {path_obj}: {e}")
        # Return safe defaults if file is corrupted
        if path_obj == TOKENS_FILE:
            return {}
        return []

def write_json_file(file_path, data, verbose=False) -> bool :
    """
        Write data to JSON file with error handling.

        Args:
            file_path: Path to write to (string or Path object)
            data: Data to serialize as JSON (dict, list, etc.)
            verbose: If True, print success message

        Returns:
            True if successful, False otherwise
        """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        if verbose:
            logger.info(f"Successfully wrote {type(data).__name__} to {file_path}")

        return True

    except IOError as e:
        logger.error(f"File I/O error writing to {file_path}: {e}", exc_info=True)
        sentry_sdk.capture_exception(e, extra={
            "file_path": str(file_path),
            "data_type": type(data).__name__
        })
        return False

    except (TypeError, ValueError) as e:
        logger.error(f"JSON serialization error for {file_path}: {e}", exc_info=True)
        sentry_sdk.capture_exception(e, extra={
            "file_path": str(file_path),
            "data_preview": str(data)[:200]
        })
        return False

def upload_bytes_to_drive(
    user_id: str,
    file_content: bytes,
    filename: str,
    content_type: str
) -> Dict[str, Any]:
    """
    Uploads a raw binary file to Google Drive and attempts to make it public.

    This function authenticates using the user's stored Google credentials,
    streams the file content to Drive, and sets the permission to 'anyone with link'.

    Args:
        user_id (str): The unique identifier of the user (to fetch tokens).
        file_content (bytes): The raw file data to be uploaded.
        filename (str): The display name for the file on Google Drive.
        content_type (str): The MIME type of the file (e.g., 'image/png').

    Returns:
        Dict[str, Any]: A dictionary containing the Google Drive file metadata,
                        specifically including 'id' and 'webViewLink'.

    Raises:
        Exception: If authentication fails, the network is down, or Google API rejects the request.
                   (Note: Permission errors are logged but do NOT raise an exception).
    """
    try:
        logger.info(f"Starting Drive upload for user {user_id}: '{filename}'")

        # 1. Validation Logic
        all_tokens = read_json_file(TOKENS_FILE)
        if user_id not in all_tokens:
            logger.warning(f"User {user_id} missing Google tokens.")
            sentry_sdk.capture_message(f"User {user_id} missing Google tokens")
            raise RuntimeError("Google Drive access not configured")

        # 2. Build Service
        creds = get_user_google_creds(user_id)
        service = build('drive', 'v3', credentials=creds)

        # 3. Prepare Upload
        media = MediaIoBaseUpload(
            io.BytesIO(file_content),
            mimetype=content_type,
            resumable=True
        )

        # 4. Execute Upload
        uploaded_file = service.files().create(
            body={'name': filename},
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        file_id = uploaded_file.get('id')
        logger.info(f"File uploaded successfully. ID: {file_id}")

        # 5. Set Permissions (Public Read)
        try:
            service.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
        except Exception as perm_error:
            # We log this but do NOT raise it, because the file IS uploaded.
            logger.error(f"Permissions error for {file_id}: {perm_error}")
            sentry_sdk.capture_exception(perm_error)

        return uploaded_file

    except Exception as e:
        # Capture critical failures that stop the upload
        sentry_sdk.capture_exception(e)
        logger.error(f"Upload Failure for '{filename}': {str(e)}")
        raise e