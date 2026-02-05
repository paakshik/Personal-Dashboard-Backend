import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from app.services.google_auth import get_user_google_creds
import json
from app.config import (USERS_FILE, TOKENS_FILE, PROJECTS_FILE, COMMANDS_FILE,
                        CHAT_HISTORY_FILE,  SYSTEM_METRICS_FILE,logger,sentry_sdk)
from pathlib import Path
from typing import Any, Union, List, Dict

# Add this to app/utils/file_ops.py

def init_data_files(data_dir: Path = None) -> None:
    """
    Initialize all required JSON data files if they don't exist.

    This function is called once at application startup to ensure all
    storage files exist with valid JSON structure. It creates empty
    files if they're missing.

    Args:
        data_dir (Path): Optional custom data directory. If None, uses
                        DATA_DIR from config.

    Returns:
        None

    Raises:
        PermissionError: If the data directory cannot be created due to
                        insufficient permissions.
        OSError: For other filesystem-related errors.

    Side Effects:
        Creates files in dashboard_data/ directory:
        - users.json (list of user objects)
        - tokens.json (dict of user_id -> tokens)
        - projects.json (list of project objects)
        - commands.json (list of command objects)
        - chat-data.json (list of chat messages)
        - system_metrics.json (list of system metrics)
    """
    from app.config import (
        DATA_DIR,
        USERS_FILE,
        TOKENS_FILE,
        PROJECTS_FILE,
        COMMANDS_FILE,
        CHAT_HISTORY_FILE,
        SYSTEM_METRICS_FILE,
        logger,
        sentry_sdk
    )

    try:
        # 1. Create data directory if it doesn't exist
        if not DATA_DIR.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Created data directory: {DATA_DIR}")

        # 2. Define files and their default structures
        files_to_init = {
            USERS_FILE: [],                    # List of user objects
            TOKENS_FILE: {},                   # Dict: user_id -> token object
            PROJECTS_FILE: [],                 # List of project objects
            COMMANDS_FILE: [],                 # List of command objects
            CHAT_HISTORY_FILE: {},             # Dict: user_id -> list of messages
            SYSTEM_METRICS_FILE: []            # List of metric snapshots
        }

        # 3. Create files if they don't exist
        for file_path, default_content in files_to_init.items():
            if not file_path.exists():
                write_json_file(file_path, default_content, verbose=False)
                logger.debug(f"✅ Initialized: {file_path.name}")
            else:
                logger.debug(f"✓ Already exists: {file_path.name}")

        logger.info("✅ All data files initialized successfully")

    except PermissionError as e:
        error_msg = f"Permission denied creating data directory: {e}"
        logger.critical(error_msg)
        sentry_sdk.capture_exception(e)
        raise PermissionError(error_msg) from e

    except OSError as e:
        error_msg = f"Filesystem error during data file initialization: {e}"
        logger.critical(error_msg)
        sentry_sdk.capture_exception(e)
        raise OSError(error_msg) from e

    except Exception as e:
        error_msg = f"Unexpected error initializing data files: {e}"
        logger.critical(error_msg)
        sentry_sdk.capture_exception(e)
        raise RuntimeError(error_msg) from e

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

    if not path_obj.exists():
        if path_obj in [USERS_FILE, PROJECTS_FILE, COMMANDS_FILE, CHAT_HISTORY_FILE,SYSTEM_METRICS_FILE]:
            logger.warning(f"File {path_obj} doesn't exist or is invalid")
            return []
        elif path_obj == TOKENS_FILE:
            logger.warning(f"File {path_obj} doesn't exist or is invalid")
            return {}
        return None
    try:
        with open(path_obj, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error reading {path_obj}: {e}")
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
        logger.info(f"📂 Starting Drive upload for user {user_id}: '{filename}'")

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
        logger.info(f"✅ File uploaded successfully. ID: {file_id}")

        # 5. Set Permissions (Public Read)
        try:
            service.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
        except Exception as perm_error:
            # We log this but do NOT raise it, because the file IS uploaded.
            logger.error(f"⚠️ Permissions error for {file_id}: {perm_error}")
            sentry_sdk.capture_exception(perm_error)

        return uploaded_file

    except Exception as e:
        # Capture critical failures that stop the upload
        sentry_sdk.capture_exception(e)
        logger.error(f"❌ Upload Failure for '{filename}': {str(e)}")
        raise e