import io
from pathlib import Path
from typing import Any, Dict, Union
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from app.config import DATA_DIR, logger, sentry_sdk
from app.services.google_auth import get_user_google_creds
from app.db_store import get_credential

# Compatibility path constants retained for older tests/tools that pass these paths.
USERS_FILE = DATA_DIR / "users.json"
TOKENS_FILE = DATA_DIR / "tokens.json"
PROJECTS_FILE = DATA_DIR / "projects.json"
COMMANDS_FILE = DATA_DIR / "commands.json"
CHAT_HISTORY_FILE = DATA_DIR / "chat-data.json"
SYSTEM_METRICS_FILE = DATA_DIR / "system_metrics.json"


def read_json_file(file_path: Union[str, Path]):
    """Read legacy-shaped records from PostgreSQL for remaining compatibility callers."""
    from app.database import session_scope
    from app.db_models import User, GoogleCredential, Project, Command, ChatMessage
    from sqlalchemy import select
    name = Path(file_path).name
    with session_scope() as db:
        if name == "users.json":
            rows = db.scalars(select(User))
            return [{"id": x.id, "google_id": x.google_id, "email": x.email, "name": x.name, "picture": x.picture, "created_at": x.created_at.isoformat()} for x in rows]
        if name == "tokens.json":
            rows = db.scalars(select(GoogleCredential).where(GoogleCredential.session_active.is_(True)))
            return {x.user_id: {"access_token": x.access_token, "refresh_token": x.refresh_token, "token_uri": x.token_uri, "client_id": x.client_id, "client_secret": x.client_secret, "scopes": x.scopes or []} for x in rows}
        if name == "projects.json":
            rows = db.scalars(select(Project))
            return [{"id": x.id, "user_id": x.user_id, "name": x.name, "description": x.description, "progress": x.progress, "status": x.status, "technologies": x.technologies or [], "category": x.category, "priority": x.priority, "links": x.links or {}, "created_at": x.created_at.isoformat(), "updated_at": x.updated_at.isoformat()} for x in rows]
        if name == "commands.json":
            rows = db.scalars(select(Command))
            return [{"id": x.id, "user_id": x.user_id, "name": x.name, "command": x.command, "description": x.description, "category": x.category, "tags": x.tags or [], "created_at": x.created_at.isoformat(), "updated_at": x.updated_at.isoformat()} for x in rows]
        if name == "chat-data.json":
            rows = db.scalars(select(ChatMessage).order_by(ChatMessage.timestamp))
            result = {}
            for row in rows:
                item = {"id": row.id, "role": row.role, "text": row.text, "timestamp": row.timestamp.isoformat()}
                if row.attachment_id:
                    item["attachment_id"] = row.attachment_id
                result.setdefault(row.user_id, []).append(item)
            return result
    return []


def write_json_file(file_path, data, verbose=False) -> bool:
    """Writes compatibility data through ORM operations rather than filesystem JSON."""
    logger.warning("write_json_file is deprecated; persist via app.db_store directly (%s)", Path(file_path).name)
    return False


def upload_bytes_to_drive(user_id: str, file_content: bytes, filename: str, content_type: str) -> Dict[str, Any]:
    try:
        if not get_credential(user_id):
            raise RuntimeError("Google Drive access not configured")
        service = build("drive", "v3", credentials=get_user_google_creds(user_id))
        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=content_type or "application/octet-stream", resumable=True)
        uploaded = service.files().create(body={"name": filename}, media_body=media, fields="id,webViewLink").execute()
        try:
            service.permissions().create(fileId=uploaded["id"], body={"type": "anyone", "role": "reader"}).execute()
        except Exception as exc:
            logger.warning("Drive file uploaded but permission update failed: %s", exc)
            sentry_sdk.capture_exception(exc)
        return uploaded
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Drive upload failed for %s: %s", filename, exc)
        raise
