import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete
from app.database import session_scope
from app.db_models import User, GoogleCredential, Project, Command, ChatMessage, SystemMetric
from app.cache import get_json, set_json, delete_pattern

CACHE_TTL = 60


def user_dict(row):
    return {"id": row.id, "google_id": row.google_id, "email": row.email, "name": row.name, "picture": row.picture, "created_at": row.created_at.isoformat()}


def credential_dict(row):
    return {"access_token": row.access_token, "refresh_token": row.refresh_token, "token_uri": row.token_uri, "client_id": row.client_id, "client_secret": row.client_secret, "scopes": row.scopes or []}


def save_user_and_credentials(user_data, credentials):
    with session_scope() as db:
        user = db.scalar(select(User).where(User.google_id == user_data["google_id"]))
        if user is None:
            user = User(**user_data)
            db.add(user)
            db.flush()
        user.name = user_data.get("name", user.name)
        user.email = user_data.get("email", user.email)
        user.picture = user_data.get("picture", user.picture or "")
        cred = db.get(GoogleCredential, user.id)
        if cred is None:
            cred = GoogleCredential(user_id=user.id, access_token=credentials["access_token"], token_uri=credentials["token_uri"])
            db.add(cred)
        old_refresh = cred.refresh_token
        for key, value in credentials.items():
            if key == "refresh_token" and not value:
                continue
            setattr(cred, key, value)
        if not cred.refresh_token:
            cred.refresh_token = old_refresh
        cred.session_active = True
        db.flush()
        result = user_dict(user), credential_dict(cred)
    delete_pattern(f"user:{result[0]['id']}:*")
    return result


def find_user_by_google_id(google_id):
    with session_scope() as db:
        row = db.scalar(select(User).where(User.google_id == google_id))
        return user_dict(row) if row else None


def find_user(user_id):
    key = f"user:{user_id}:profile"
    cached = get_json(key)
    if cached is not None:
        return cached
    with session_scope() as db:
        row = db.get(User, str(user_id))
        result = user_dict(row) if row else None
    if result:
        set_json(key, result, CACHE_TTL)
    return result


def get_credential(user_id):
    with session_scope() as db:
        row = db.get(GoogleCredential, str(user_id))
        return credential_dict(row) if row else None


def save_credential(user_id, data):
    with session_scope() as db:
        row = db.get(GoogleCredential, str(user_id))
        if not row:
            return False
        for key, value in data.items():
            setattr(row, key, value)
    delete_pattern(f"user:{user_id}:*")
    return True


def is_session_active(user_id):
    with session_scope() as db:
        row = db.get(GoogleCredential, str(user_id))
        return bool(row and row.session_active)


def revoke_session(user_id):
    with session_scope() as db:
        row = db.get(GoogleCredential, str(user_id))
        if row:
            row.session_active = False
    delete_pattern(f"user:{user_id}:*")


def _project_dict(row):
    return {"id": row.id, "user_id": row.user_id, "name": row.name, "description": row.description, "progress": row.progress, "status": row.status, "technologies": row.technologies or [], "category": row.category, "priority": row.priority, "links": row.links or {}, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def list_projects(user_id):
    key = f"user:{user_id}:projects"
    cached = get_json(key)
    if cached is not None:
        return cached
    with session_scope() as db:
        result = [_project_dict(x) for x in db.scalars(select(Project).where(Project.user_id == str(user_id)).order_by(Project.created_at.desc()).limit(500))]
    set_json(key, result, CACHE_TTL)
    return result


def get_project(user_id, project_id):
    with session_scope() as db:
        row = db.scalar(select(Project).where(Project.id == str(project_id), Project.user_id == str(user_id)))
        return _project_dict(row) if row else None


def save_project(user_id, payload, project_id=None):
    with session_scope() as db:
        row = db.get(Project, project_id) if project_id else None
        if row and row.user_id != str(user_id):
            return None
        if row is None:
            row = Project(id=str(project_id or uuid.uuid4()), user_id=str(user_id), **payload)
            db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
        db.flush()
        result = _project_dict(row)
    delete_pattern(f"user:{user_id}:projects")
    return result


def delete_project(user_id, project_id):
    with session_scope() as db:
        row = db.scalar(select(Project).where(Project.id == str(project_id), Project.user_id == str(user_id)))
        if not row:
            return None
        result = _project_dict(row)
        db.delete(row)
    delete_pattern(f"user:{user_id}:projects")
    return result


def _command_dict(row):
    return {"id": row.id, "user_id": row.user_id, "name": row.name, "command": row.command, "description": row.description, "category": row.category, "tags": row.tags or [], "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def list_commands(user_id):
    key = f"user:{user_id}:commands"
    cached = get_json(key)
    if cached is not None:
        return cached
    with session_scope() as db:
        result = [_command_dict(x) for x in db.scalars(select(Command).where(Command.user_id == str(user_id)).order_by(Command.created_at.desc()).limit(500))]
    set_json(key, result, CACHE_TTL)
    return result


def get_command(user_id, command_id):
    with session_scope() as db:
        row = db.scalar(select(Command).where(Command.id == str(command_id), Command.user_id == str(user_id)))
        return _command_dict(row) if row else None


def save_command(user_id, payload, command_id=None):
    with session_scope() as db:
        row = db.get(Command, command_id) if command_id else None
        if row and row.user_id != str(user_id):
            return None
        if row is None:
            row = Command(id=str(command_id or uuid.uuid4()), user_id=str(user_id), **payload)
            db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
        db.flush()
        result = _command_dict(row)
    delete_pattern(f"user:{user_id}:commands")
    return result


def delete_command(user_id, command_id):
    with session_scope() as db:
        row = db.scalar(select(Command).where(Command.id == str(command_id), Command.user_id == str(user_id)))
        if not row:
            return False
        db.delete(row)
    delete_pattern(f"user:{user_id}:commands")
    return True


def save_chat_message(role, text, user_id, attachment_id=None):
    data = {"id": str(uuid.uuid4()), "role": role, "text": text, "timestamp": datetime.now(timezone.utc).isoformat()}
    if attachment_id and role == "user":
        data["attachment_id"] = attachment_id
    with session_scope() as db:
        db.add(ChatMessage(id=data["id"], user_id=str(user_id), role=role, text=text, attachment_id=data.get("attachment_id")))
        old_ids = select(ChatMessage.id).where(ChatMessage.user_id == str(user_id)).order_by(ChatMessage.timestamp.desc()).offset(100)
        db.execute(delete(ChatMessage).where(ChatMessage.user_id == str(user_id), ChatMessage.id.in_(old_ids)))
    delete_pattern(f"user:{user_id}:chat")
    return data


def list_chat_messages(user_id):
    key = f"user:{user_id}:chat"
    cached = get_json(key)
    if cached is not None:
        return cached
    with session_scope() as db:
        rows = db.scalars(select(ChatMessage).where(ChatMessage.user_id == str(user_id)).order_by(ChatMessage.timestamp.asc()).limit(100))
        result = [{"id": row.id, "role": row.role, "text": row.text, "timestamp": row.timestamp.isoformat(), **({"attachment_id": row.attachment_id} if row.attachment_id else {})} for row in rows]
    set_json(key, result, CACHE_TTL)
    return result


def clear_chat_messages(user_id):
    with session_scope() as db:
        result = db.execute(delete(ChatMessage).where(ChatMessage.user_id == str(user_id)))
        count = result.rowcount or 0
    delete_pattern(f"user:{user_id}:chat")
    return count


def save_system_metric(payload):
    with session_scope() as db:
        db.add(SystemMetric(timestamp=datetime.fromisoformat(payload["timestamp"]), payload=payload))
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        db.execute(delete(SystemMetric).where(SystemMetric.timestamp < cutoff))


def list_system_metrics(hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with session_scope() as db:
        rows = db.scalars(select(SystemMetric).where(SystemMetric.timestamp >= cutoff).order_by(SystemMetric.timestamp.asc()).limit(5000))
        return [row.payload for row in rows]
