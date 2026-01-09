import os
import uuid
import json
import time
import psutil
import shutil
import socket
import platform
import requests
import base64
import io
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Set
import google.generativeai as genai
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request, WebSocket,   WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from jose import JWTError, jwt
import sentry_sdk
from pydantic import BaseModel
import traceback

load_dotenv()
DATA_DIR = Path(os.getenv("DATA_DIR"))
DATA_DIR.mkdir(exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
USERS_FILE = DATA_DIR / "users.json"
TOKENS_FILE = DATA_DIR / "tokens.json"
PROJECTS_FILE = DATA_DIR / "projects.json"
COMMANDS_FILE = DATA_DIR / "commands.json"
CHAT_HISTORY_FILE = DATA_DIR / "chat-data.json"
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
security = HTTPBearer()

# Helper functions for JSON file operations
def write_json_file(file_path, data):
    """Write data to JSON file with error handling"""
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"❌ Error writing to {file_path}: {e}")
        return False

def read_json_file(file_path):
    """Read JSON file, return default if file doesn't exist or is invalid"""
    if not file_path.exists():
        print(f"⚠️  File {file_path} doesn't exist")
        # Return appropriate default based on file name
        if file_path in [USERS_FILE, PROJECTS_FILE, COMMANDS_FILE]:
            return []
        elif file_path == TOKENS_FILE:
            return {}
        return None

    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            print(f"📁 Read {file_path}: {type(data)} with {len(data) if hasattr(data, '__len__') else 'N/A'} items")
            return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"❌ Error reading {file_path}: {e}")
        # Return safe defaults
        if file_path in [USERS_FILE, PROJECTS_FILE, COMMANDS_FILE]:
            return []
        elif file_path == TOKENS_FILE:
            return {}
        return None
def get_chat_history_data():
    if not CHAT_HISTORY_FILE.exists():
        return []
    try:
        return read_json_file(CHAT_HISTORY_FILE)
    except:
        return []

# --- FIND THIS FUNCTION IN main.py AND REPLACE IT ---
def save_chat_message(role: str, text: str):
    history = get_chat_history_data()

    # 👇👇👇 THE FIX IS HERE 👇👇👇
    # If history is None (corrupted file) or not a list, force it to be an empty list
    if history is None or not isinstance(history, list):
        history = []
    # 👆👆👆 END OF FIX 👆👆👆

    new_message = {
        "id": str(uuid.uuid4()),
        "role": role,
        "text": text,
        "timestamp": datetime.now().isoformat()
    }

    history.append(new_message)

    # Keep only last 100 messages
    if len(history) > 100:
        history = history[-100:]

    write_json_file(CHAT_HISTORY_FILE, history)
    return new_message
def get_commands_db():
    """Get commands from file storage"""
    return read_json_file(COMMANDS_FILE)

def get_projects_db():
    """Get projects from file storage"""
    return read_json_file(PROJECTS_FILE)

def save_commands_db(data):
    return write_json_file(COMMANDS_FILE, data)

def save_projects_db(data):
    return write_json_file(PROJECTS_FILE, data)

# Initialize data files
def init_data_files():
    files = {
        USERS_FILE: [],
        TOKENS_FILE: {},
        PROJECTS_FILE: [],
        COMMANDS_FILE: []
    }

    for file_path, default_data in files.items():
        if not file_path.exists():
            with open(file_path, 'w') as f:
                json.dump(default_data, f, indent=2)

    print("✅ Data files initialized")

init_data_files()

# Authentication dependency
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id: str = payload.get("sub")

        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        all_tokens = read_json_file(TOKENS_FILE)
        if user_id not in all_tokens:
            print(f"❌ No tokens found for user {user_id}, requiring re-login")
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

        # Check if user exists
        users = read_json_file(USERS_FILE)

        if not users or not isinstance(users, list):
            raise HTTPException(status_code=401, detail="User database error")

        user = None
        for u in users:
            if str(u.get("id")) == user_id:
                user = u
                break

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        print(f"✅ User authenticated: {user.get('email')}")
        return {
            "id": user_id,
            "email": user.get("email"),
            "name": user.get("name", "User")
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
# Google OAuth Scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]
sentry_sdk.init(
    dsn="https://2a164604df6703183b3fc1f08702997b@o4510545524752384.ingest.us.sentry.io/4510545614864384",
    # Add data like request headers and IP for users,
    # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
    send_default_pii=True,
)
# Add this class after imports
class LightweightConnectionManager:
    """Minimal WebSocket manager - only for essential connections"""
    def __init__(self):
        # Only maintain essential connections
        self.system_vitals_connections: Set[WebSocket] = set()
        self.notification_connections: Set[WebSocket] = set()

    async def connect_system_vitals(self, websocket: WebSocket):

        self.system_vitals_connections.add(websocket)
        print(f"✅ System vitals WebSocket connected. Total: {len(self.system_vitals_connections)}")

    async def connect_notifications(self, websocket: WebSocket):

        self.notification_connections.add(websocket)
        print(f"✅ Notifications WebSocket connected. Total: {len(self.notification_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove from all connection sets"""
        if websocket in self.system_vitals_connections:
            self.system_vitals_connections.remove(websocket)
            print(f"❌ System vitals WebSocket disconnected. Total: {len(self.system_vitals_connections)}")
        if websocket in self.notification_connections:
            self.notification_connections.remove(websocket)
            print(f"❌ Notifications WebSocket disconnected. Total: {len(self.notification_connections)}")

    async def broadcast_system_vitals(self, data: dict):
        """Broadcast to system vitals clients only"""
        disconnected: Set[WebSocket] = set()
        for conn in self.system_vitals_connections:
            try:
                await conn.send_json(data)
            except:
                disconnected.add(conn)

        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_notification(self, title: str, message: str, level: str = "info"):
        """Send notification to all notification clients"""
        disconnected: Set[WebSocket] = set()
        notification = {
            "type": "notification",
            "title": title,
            "message": message,
            "level": level,
            "timestamp": datetime.now().isoformat()
        }

        for conn in self.notification_connections:
            try:
                await conn.send_json(notification)
            except:
                disconnected.add(conn)
                raise

        for conn in disconnected:
            self.disconnect(conn)

# Initialize lightweight manager
ws_manager = LightweightConnectionManager()
# Add this class after the ConnectionManager
class SystemDataStore:
    """Shared data store to prevent multiple collections"""
    def __init__(self):
        self.current_vitals = {}
        self.last_update = None
        self.update_lock = asyncio.Lock()

    async def get_vitals(self):
        """Get current vitals - updates only if stale"""
        async with self.update_lock:
            now = datetime.now()
            # Update only if data is older than 2 seconds
            if (not self.last_update or
                (now - self.last_update).total_seconds() > 2):
                self.current_vitals = collect_system_vitals_data()
                self.last_update = now
            return self.current_vitals
def get_calendar_events_from_creds(user_id: str):
    """Get calendar events using user credentials"""
    try:
        creds = get_user_google_creds(user_id)
        service = build('calendar', 'v3', credentials=creds)
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        one_week_later = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat().replace('+00:00', 'Z')

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=one_week_later,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        return events

    except Exception as e:
        print(f"Calendar events error for AI: {e}")
        return None

def get_gmail_emails_from_creds(user_id: str):
    """Get recent emails using user credentials"""
    try:
        creds = get_user_google_creds(user_id)
        service = build('gmail', 'v1', credentials=creds)
        results = service.users().messages().list(userId='me', maxResults=10).execute()
        messages = results.get('messages', [])

        emails = []
        for msg in messages[:5]:  # Only first 5 for context
            txt = service.users().messages().get(userId='me', id=msg['id'], format='metadata').execute()
            headers = txt['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(No Subject)')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            emails.append(f"{subject} - {sender}")

        return emails

    except Exception as e:
        print(f"Gmail error for AI: {e}")
        return None

def get_todoist_tasks():
    """Get Todoist tasks"""
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('TODOIST_TOKEN')}",
            "Content-Type": "application/json"
        }
        response = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers)
        tasks = response.json()
        return [t["content"] for t in tasks[:10]]  # Only first 10 tasks

    except Exception as e:
        print(f"Todoist error for AI: {e}")
        return None
# Global data store
system_data = SystemDataStore()

app = FastAPI(title="System Dashboard API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# --- DATA MODELS ---
class EventItem(BaseModel):
    summary: str
    start_time: str
    end_time: str
    description: Optional[str] = ""
    location: Optional[str] = ""

class TaskItem(BaseModel):
    content: str
    description: Optional[str] = ""
    project_id: Optional[int] = None
    labels: Optional[List[str]] = []

class ProjectLink(BaseModel):
    github: Optional[str] = ""
    database: Optional[str] = ""
    live: Optional[str] = ""
    api: Optional[str] = ""

class ProjectItem(BaseModel):
    name: str
    description: str
    progress: int = 0
    status: str = "planning"
    technologies: List[str] = []
    category: str = "web"
    priority: str = "medium"
    lastUpdated: str = ""
    links: ProjectLink = ProjectLink()

class ProjectInDB(ProjectItem):
    id: str
    created_at: str
    updated_at: str

class CommandItem(BaseModel):
    name: str
    command: str
    description: Optional[str] = ""
    category: Optional[str] = "general"
    tags: Optional[List[str]] = []

class GoogleAuthData(BaseModel):
    credential: str  # Google ID token

class CommandInDB(CommandItem):
    id: str
    created_at: str
    updated_at: str
class ChatRequest(BaseModel):
    message: str
    attachment_id: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = []
# --- VALIDATION FUNCTIONS --- (ADD THIS SECTION HERE)
def validate_command_name(name: str) -> bool:
    """Validate command name"""
    if not name or len(name.strip()) == 0:
        return False
    if len(name) > 100:
        return False
    # Add any other validation rules
    return True

def validate_command_content(command: str) -> bool:
    """Validate command content"""
    if not command or len(command.strip()) == 0:
        return False
    if len(command) > 1000:
        return False
    # Security validation - prevent dangerous commands
    dangerous_patterns = [
        'rm -rf /', 'sudo rm', 'mkfs', 'dd if=',
        ':(){:|:&};:', 'chmod 777 /', '> /dev/sda',
        'wget http', 'curl -s', 'bash <('
    ]
    for pattern in dangerous_patterns:
        if pattern in command.lower():
            return False
    return True

def validate_command_tags(tags: List[str]) -> bool:
    """Validate command tags"""
    if not tags:
        return True
    if len(tags) > 10:
        return False
    for tag in tags:
        if len(tag) > 50:
            return False
    return True
# --- HELPER: GOOGLE CREDENTIALS ---
def get_user_google_creds(user_id: str):
    """Retrieve credentials for a specific user from tokens.json"""
    all_tokens = read_json_file(TOKENS_FILE)
    user_tokens = all_tokens.get(user_id)


    if not user_tokens:
        # Provide more detailed error
        print(f"❌ No Google tokens found for user {user_id}")
        raise HTTPException(
            status_code=401,
            detail="Google authentication required. Please connect your Google account first."
        )

    # Check if we have minimum required fields
    if not user_tokens.get("access_token"):
        print(f"❌ Missing access_token for user {user_id}")
        raise HTTPException(
            status_code=401,
            detail="Invalid Google token. Please re-authenticate."
        )
    creds = Credentials(
        token=user_tokens["access_token"],
        refresh_token=user_tokens.get("refresh_token"),
        token_uri=user_tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=user_tokens.get("client_id"),
        client_secret=user_tokens.get("client_secret"),
        scopes=user_tokens.get("scopes")
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            user_tokens["access_token"] = creds.token
            all_tokens[user_id] = user_tokens
            write_json_file(TOKENS_FILE, all_tokens)

        except Exception as e:
            print(f"Token Refresh failed: {e}")
            raise HTTPException(status_code=401, detail="Google session expired")



    return creds
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()

    expire = datetime.utcnow() + (
        expires_delta
        if expires_delta
        else timedelta(minutes=os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))
    )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=os.getenv("ALGORITHM"))
    return encoded_jwt

# --- ROOT ENDPOINTS ---
@app.get("/")
def read_root():
    return {"message": "System Dashboard API", "status": "running", "version": "2.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
# --- GEMINI FILE UPLOAD ENDPOINT ---
@app.post("/dashboard/gemini/upload")
def upload_to_gemini(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    try:
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="Gemini API Key missing")

        # 1. Save file locally temporarily
        temp_filename = f"temp_{uuid.uuid4()}_{file.filename}"
        temp_path = DATA_DIR / temp_filename

        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Upload to Gemini
        genai.configure(api_key=GEMINI_API_KEY)
        print(f"📤 Uploading {file.filename} to Gemini...")

        gemini_file = genai.upload_file(path=temp_path, display_name=file.filename)

        # 3. Clean up local file
        os.remove(temp_path)

        print(f"✅ File uploaded: {gemini_file.name}")
        return {"status": "success", "file_id": gemini_file.name, "filename": file.filename}

    except Exception as e:
        print(f"❌ Upload Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# --- AUTH ENDPOINTS ---
@app.get("/auth/google/login")
def login_google():
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            os.getenv("CREDENTIALS_FILE"),
            scopes=SCOPES,
            redirect_uri=os.getenv("BACKEND_REDIRECT_URI")
        )
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        return {"url": auth_url}
    except Exception as e:
        print(f"Error generating login URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/ai/stream")
async def websocket_ai_stream(websocket: WebSocket):
    await websocket.accept()
    print("✅ WebSocket /ws/ai/stream connected")

    current_user = None

    try:
        # --------------------------------------------------
        # 1. AUTHENTICATION (First Message MUST Be Token)
        # --------------------------------------------------
        auth_data = await websocket.receive_json()
        token = auth_data.get("token")

        if not token:
            await websocket.send_json({"error": "Authentication required"})
            await websocket.close()
            return

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("sub")

            if not user_id:
                await websocket.send_json({"error": "Invalid token payload"})
                await websocket.close()
                return

            users = read_json_file(USERS_FILE)
            if not users or not isinstance(users, list):
                await websocket.send_json({"error": "User database error"})
                await websocket.close()
                return

            user = next((u for u in users if str(u.get("id")) == str(user_id)), None)

            if not user:
                await websocket.send_json({"error": "User not found"})
                await websocket.close()
                return

            current_user = {
                "id": user_id,
                "email": user.get("email"),
                "name": user.get("name", "User"),
            }

            print(f"✅ AI WebSocket authenticated: {current_user['email']}")
            await websocket.send_json({"status": "authenticated"})

        except jwt.ExpiredSignatureError:
            await websocket.send_json({"error": "Token expired"})
            await websocket.close()
            return
        except JWTError as e:
            await websocket.send_json({"error": f"Invalid token: {str(e)}"})
            await websocket.close()
            return

        # --------------------------------------------------
        # 2. MAIN MESSAGE LOOP (Now Authenticated)
        # --------------------------------------------------
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                print("❌ AI WebSocket client disconnected")
                break

            user_prompt = data.get("prompt", "").strip()
            attachment_id = data.get("attachment_id")

            if not user_prompt:
                await websocket.send_json({"error": "Empty prompt"})
                continue

            # --------------------------------------------------
            # 3. CONTEXT GATHERING (UNCHANGED)
            # --------------------------------------------------
            try:
                calendar_events = get_calendar_events_from_creds(current_user["id"])
                tasks = get_todoist_tasks()
                emails = get_gmail_emails_from_creds(current_user["id"])

                context_data = f"""
Calendar Events:
{str(calendar_events)[:1000] if calendar_events else 'No upcoming events'}

Tasks:
{str(tasks)[:1000] if tasks else 'No pending tasks'}

Recent Emails:
{str(emails)[:1000] if emails else 'No recent emails'}

Attachment: {'[File attached]' if attachment_id else 'None'}
                """
            except Exception as e:
                print(f"Context gathering error: {e}")
                context_data = "Context data temporarily unavailable."

            # --------------------------------------------------
            # 4. SYSTEM INSTRUCTION (UNCHANGED)
            # --------------------------------------------------
            system_instruction = f"""
You are the 'Nexus' Dashboard AI.

Current System Time: {datetime.now().isoformat()}

--- NAVIGATION PROTOCOL ---
Available views:
dashboard, projects, commands, schedule, tasks, emails, ai

Use format:
<<NAVIGATE:view_name>>
---------------------------

User Context:
{context_data}
"""

            if not GEMINI_API_KEY:
                await websocket.send_text("Error: GEMINI_API_KEY is missing")
                await websocket.send_text("[DONE]")
                continue

            genai.configure(api_key=GEMINI_API_KEY)

            message_parts = [user_prompt]

            # --------------------------------------------------
            # 5. ATTACHMENTS (UNCHANGED)
            # --------------------------------------------------
            if attachment_id:
                try:
                    file_ref = genai.get_file(attachment_id)
                    message_parts.append(file_ref)
                    await websocket.send_text("[Processing attached file...]")
                except Exception as e:
                    await websocket.send_text(f"[Attachment error: {e}]")

            # --------------------------------------------------
            # 6. GEMINI STREAMING (UNCHANGED)
            # --------------------------------------------------
            try:
                model = genai.GenerativeModel(
                    model_name="gemini-2.5-flash",
                    system_instruction=system_instruction,
                )

                response = model.generate_content(
                    message_parts,
                    stream=True,
                    generation_config={
                        "temperature": 0.7,
                        "max_output_tokens": 2048,
                    },
                )

                full_response = ""

                for chunk in response:
                    if chunk.text:
                        await websocket.send_text(chunk.text)
                        full_response += chunk.text
                        await asyncio.sleep(0)

                # --------------------------------------------------
                # 7. SAVE CHAT HISTORY (UNCHANGED)
                # --------------------------------------------------
                try:
                    save_chat_message(
                        "user",
                        f"{user_prompt} {'[Attached File]' if attachment_id else ''}",
                    )
                    save_chat_message("model", full_response)
                except Exception as e:
                    print(f"History save error: {e}")

                await websocket.send_text("[DONE]")

            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"Gemini streaming error: {e}")
                await websocket.send_text(f"AI Error: {str(e)}")
                await websocket.send_text("[DONE]")

    except WebSocketDisconnect:
        print("Client disconnected during auth")
    except Exception as e:
        print(f"🔥 WebSocket fatal error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass

@app.get("/auth/google/callback")
def callback_google(request: Request):

    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            os.getenv("CREDENTIALS_FILE"),
            scopes=SCOPES,
            redirect_uri=os.getenv("BACKEND_REDIRECT_URI")
        )
        flow.fetch_token(code=code)
        creds = flow.credentials

        service = build("oauth2", "v2", credentials=creds)
        user_info = service.userinfo().get().execute()

        google_id = user_info["id"]
        email = user_info["email"]

        users = read_json_file(USERS_FILE)
        if not isinstance(users, list):
            users = []

        user = next((u for u in users if u.get("google_id") == google_id), None)

        # --- USER CREATE / FETCH ---
        if not user:
            user_id = str(uuid.uuid4())
            user = {
                "id": user_id,
                "google_id": google_id,
                "email": email,
                "name": user_info.get("name", "User"),
                "picture": user_info.get("picture", ""),
                "created_at": datetime.utcnow().isoformat()
            }
            users.append(user)
            write_json_file(USERS_FILE, users)
        else:
            user_id = user["id"]

        # --- GOOGLE TOKEN STORAGE (CORRECT & SAFE) ---
        all_tokens = read_json_file(TOKENS_FILE)
        if not isinstance(all_tokens, dict):
            all_tokens = {}

        existing_refresh_token = None
        if user_id in all_tokens:
            existing_refresh_token = all_tokens[user_id].get("refresh_token")

        final_refresh_token = (
            creds.refresh_token if creds.refresh_token else existing_refresh_token
        )

        all_tokens[user_id] = {
            "access_token": creds.token,
            "refresh_token": final_refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
        write_json_file(TOKENS_FILE, all_tokens)

        # --- APP JWT CREATION ---
        app_token = jwt.encode(
            {
                "sub": user_id,
                "email": email,
                "exp": datetime.utcnow()
                + timedelta(minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")))
            },
            SECRET_KEY,
            algorithm=os.getenv("ALGORITHM")
        )

        frontend_url = os.getenv("FRONTEND_URL")

        return RedirectResponse(
            url=f"{frontend_url}?token={app_token}",
            status_code=302
        )

    except Exception as e:
        print(f"❌ Callback Error: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Authentication failed: {str(e)}"}
        )

@app.get("/auth/verify")
def verify_token_endpoint(current_user: dict = Depends(get_current_user)):
    users = read_json_file(USERS_FILE)
    if isinstance(users, dict):
        users = []
    user = next((u for u in users if u.get("id") == current_user["id"]), None)
    return {"valid": True, "user": user}
@app.get("/dashboard/gemini/history")
def get_history(current_user: dict = Depends(get_current_user)):
    return get_chat_history_data()

@app.delete("/dashboard/gemini/history")
def clear_history(current_user: dict = Depends(get_current_user)):
    write_json_file(CHAT_HISTORY_FILE, [])
    return {"status": "cleared"}
# --- FILE UPLOAD ENDPOINT ---
@app.post("/dashboard/upload")
async def upload_file(file: UploadFile = File(...),current_user: dict = Depends(get_current_user)):
    try:
        all_tokens = read_json_file(TOKENS_FILE)
        user_id = current_user["id"]

        if user_id not in all_tokens:
            raise HTTPException(
                status_code=401,
                detail="Google Drive access not configured. Please re-authenticate with Google."
            )
        creds = get_user_google_creds(current_user["id"])
        service = build('drive', 'v3', credentials=creds)

        file_content = await file.read()
        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=file.content_type, resumable=True)

        uploaded_file = service.files().create(
            body={'name': file.filename},
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        # Share with anyone so the link works immediately
        service.permissions().create(
            fileId=uploaded_file.get('id'),
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        return {
            "status": "success",
            "filename": file.filename,
            "link": uploaded_file.get('webViewLink'),
            "fileId": uploaded_file.get('id')
        }

    except Exception as e:
        print(f"❌ Upload Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dashboard/email/{message_id}/read")
def mark_email_as_read(message_id: str, current_user: dict = Depends(get_current_user)):
    """Mark an email as read in Gmail"""
    try:
        creds = get_user_google_creds(current_user["id"])
        service = build('gmail', 'v1', credentials=creds)

        # Mark the email as read by removing UNREAD label
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()

        return {"status": "success", "message": "Email marked as read"}

    except Exception as e:
        print(f"❌ Mark as read error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- CALENDAR ENDPOINTS ---
@app.get("/dashboard/calendar")
def get_calendar_events(current_user: dict = Depends(get_current_user)):
    try:
        creds = get_user_google_creds(current_user["id"])
        service = build('calendar', 'v3', credentials=creds)
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        one_week_later = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat().replace('+00:00', 'Z')

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=one_week_later,
            maxResults=50,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        classified_events = {}
        for event in events:
            start_raw = event['start'].get('dateTime', event['start'].get('date'))
            end_raw = event['end'].get('dateTime', event['end'].get('date'))
            date_key = start_raw.split('T')[0] if 'T' in start_raw else start_raw
            date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%A, %B %d, %Y')
            time_display = "All Day"
            if 'T' in start_raw:
                time_display = datetime.fromisoformat(start_raw.replace('Z', '+00:00')).strftime('%H:%M')

            event_data = {
                "id": event['id'],
                "title": event.get('summary', 'No Title'),
                "description": event.get('description', ''),
                "location": event.get('location', ''),
                "time": time_display,
                "start_raw": start_raw,
                "end_raw": end_raw,
            }

            if date_key not in classified_events:
                classified_events[date_key] = {
                    "date_key": date_key,
                    "date_display": date_display,
                    "events": []
                }
            classified_events[date_key]["events"].append(event_data)

        return [classified_events[k] for k in sorted(classified_events.keys())]

    except Exception as e:
        print(f"❌ Calendar Error: {e}")
        return []

@app.post("/dashboard/calendar/events")
def add_calendar_event(event: EventItem,current_user: dict = Depends(get_current_user)):
    try:
        creds = get_user_google_creds(current_user["id"])
        service = build('calendar', 'v3', credentials=creds)
        body = {
            'summary': event.summary,
            'description': event.description,
            'location': event.location,
            'start': {'dateTime': event.start_time, 'timeZone': 'UTC'},
            'end': {'dateTime': event.end_time, 'timeZone': 'UTC'},
        }
        created_event = service.events().insert(calendarId='primary', body=body).execute()
        return {
            "status": "success",
            "id": created_event.get('id'),
            "summary": created_event.get('summary')
        }
    except Exception as e:
        print(f"❌ Calendar Add Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/dashboard/calendar/events/{event_id}")
def update_calendar_event(event_id: str,event: EventItem,current_user: dict = Depends(get_current_user)):
    try:
        creds = get_user_google_creds(current_user["id"])
        service = build('calendar', 'v3', credentials=creds)
        existing = service.events().get(calendarId='primary', eventId=event_id).execute()
        existing.update({
            'summary': event.summary,
            'description': event.description,
            'location': event.location,
        })
        existing['start']['dateTime'] = event.start_time
        existing['end']['dateTime'] = event.end_time
        service.events().update(calendarId='primary', eventId=event_id, body=existing).execute()
        return {"status": "updated"}
    except Exception as e:
        print(f"❌ Calendar Update Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/dashboard/calendar/events/{event_id}")
def delete_calendar_event(event_id: str,current_user: dict = Depends(get_current_user)):
    try:
        creds = get_user_google_creds(current_user["id"])
        service = build('calendar', 'v3', credentials=creds)
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        return {"status": "deleted"}
    except Exception as e:
        print(f"❌ Calendar Delete Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- GMAIL ENDPOINTS ---
def get_email_body(payload):
    """Extract email body from Gmail payload"""
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/html' or part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            if 'parts' in part:
                result = get_email_body(part)
                if result:
                    return result
    else:
        data = payload['body'].get('data')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return "Could not decode email."

@app.get("/dashboard/gmail")
def get_gmail(current_user: dict = Depends(get_current_user)):
    try:
        creds = get_user_google_creds(current_user["id"])
        service = build('gmail', 'v1', credentials=creds)
        results = service.users().messages().list(userId='me', maxResults=20).execute()
        messages = results.get('messages', [])

        clean_emails = []
        for msg in messages:
            txt = service.users().messages().get(userId='me', id=msg['id'], format='metadata').execute()
            headers = txt['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(No Subject)')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')

            # Clean sender name
            if '<' in sender:
                sender = sender.split('<')[0].strip().replace('"', '')

            clean_emails.append({
                "id": msg['id'],
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "snippet": txt.get('snippet', ''),
                "labels": txt.get('labelIds', []),
                "internalDate": txt.get('internalDate', 0)
            })
        return clean_emails

    except Exception as e:
        print(f"❌ Gmail Error: {e}")
        return []

@app.get("/dashboard/email/{message_id}")
def get_email_content(message_id: str,current_user: dict = Depends(get_current_user)):
    try:
        creds = get_user_google_creds(current_user["id"])
        service = build('gmail', 'v1', credentials=creds)
        message = service.users().messages().get(userId='me', id=message_id, format='full').execute()

        headers = message['payload']['headers']
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(No Subject)')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
        date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')

        return {
            "id": message_id,
            "subject": subject,
            "sender": sender,
            "date": date_str,
            "body": get_email_body(message['payload']),
            "snippet": message.get('snippet', '')
        }

    except Exception as e:
        print(f"❌ Email Content Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- TODOIST ENDPOINTS ---
@app.get("/dashboard/todoist")
def get_todoist(current_user: dict = Depends(get_current_user)):
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('TODOIST_TOKEN')}",
            "Content-Type": "application/json"
        }
        response = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers)
        response.raise_for_status()
        tasks = response.json()

        return [{
            "id": t["id"],
            "content": t["content"],
            "description": t.get("description", ""),
            "project_id": t.get("project_id"),
            "due": t.get("due"),
            "labels": t.get("labels", []),
            "priority": t.get("priority", 1),
            "is_completed": t.get("is_completed", False)
        } for t in tasks]

    except Exception as e:
        print(f"❌ Todoist Error: {e}")
        return []

@app.post("/dashboard/todoist/tasks")
def add_todoist_task(task: TaskItem):
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('TODOIST_TOKEN')}",
            "Content-Type": "application/json"
        }

        payload = {
            "content": task.content,
            "description": task.description,
            "labels": task.labels
        }

        if task.project_id:
            payload["project_id"] = task.project_id

        response = requests.post(
            "https://api.todoist.com/rest/v2/tasks",
            headers=headers,
            json=payload
        )
        response.raise_for_status()

        return response.json()

    except Exception as e:
        print(f"❌ Todoist Add Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dashboard/todoist/tasks/{task_id}")
def update_todoist_task(task_id: str, task: TaskItem):
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('TODOIST_TOKEN')}",
            "Content-Type": "application/json"
        }

        payload = {
            "content": task.content,
            "description": task.description
        }

        response = requests.post(
            f"https://api.todoist.com/rest/v2/tasks/{task_id}",
            headers=headers,
            json=payload
        )
        response.raise_for_status()

        return response.json()

    except Exception as e:
        print(f"❌ Todoist Update Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dashboard/todoist/tasks/{task_id}/complete")
def complete_todoist_task(task_id: str):
    try:
        headers = {"Authorization": f"Bearer {os.getenv('TODOIST_TOKEN')}"}
        response = requests.post(
            f"https://api.todoist.com/rest/v2/tasks/{task_id}/close",
            headers=headers
        )
        response.raise_for_status()

        return {"status": "completed", "task_id": task_id}

    except Exception as e:
        print(f"❌ Todoist Complete Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/dashboard/todoist/tasks/{task_id}")
def delete_todoist_task(task_id: str):
    try:
        headers = {"Authorization": f"Bearer {os.getenv('TODOIST_TOKEN')}"}
        response = requests.delete(
            f"https://api.todoist.com/rest/v2/tasks/{task_id}",
            headers=headers
        )
        response.raise_for_status()

        return {"status": "deleted", "task_id": task_id}

    except Exception as e:
        print(f"❌ Todoist Delete Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboard/system/websocket-status")
def get_websocket_status(current_user: dict = Depends(get_current_user)):
    """Get WebSocket connection status"""
    return {
        "system_vitals": {
            "connected_clients": len(ws_manager.system_vitals_connections),
            "endpoint": "/ws/system/vitals",
            "purpose": "Real-time system monitoring",
            "update_frequency": "2 seconds",
            "saves_polling": "Yes - replaces HTTP polling every 2 seconds"
        },
        "notifications": {
            "connected_clients": len(ws_manager.notification_connections),
            "endpoint": "/ws/notifications",
            "purpose": "Real-time event notifications",
            "update_frequency": "10-60 seconds",
            "saves_polling": "Yes - replaces HTTP polling for events"
        },
        "command_status": {
            "endpoint": "/ws/commands/status/{command_id}",
            "purpose": "Stream long-running command output",
            "saves_polling": "Yes - replaces HTTP polling for command status"
        }
    }
# --- SYSTEM MONITORING ENDPOINTS ---
def get_service_name(port: int) -> str:
    """Get service name for port"""
    common_ports = {
        80: "HTTP", 443: "HTTPS", 22: "SSH", 21: "FTP", 25: "SMTP",
        53: "DNS", 3306: "MySQL", 5432: "PostgreSQL", 27017: "MongoDB",
        6379: "Redis", 3000: "Node.js", 5000: "Python", 8080: "Proxy",
        8443: "HTTPS Alt", 9200: "Elasticsearch", 5601: "Kibana",
        8000: "FastAPI", 5173: "Vite Dev", 27015: "Steam",
        25565: "Minecraft", 27020: "Source Engine"
    }
    return common_ports.get(port, "Custom")
def collect_system_vitals_data():
    """Robust system data collector"""
    # Initialize defaults to prevent 'UnboundLocalError'
    cpu_percent = 0.0
    cpu_count = 4
    memory_percent = 0.0
    memory_used_gb = 0.0
    memory_total_gb = 8.0
    disk_percent = 0.0
    disk_free_gb = 0.0
    disk_total_gb = 256.0
    sent_mb = 0.0
    recv_mb = 0.0
    uptime_str = "0:00:00"
    process_count = 0
    system_name = "Unknown"
    release = ""

    # Battery Defaults
    battery_percent = 0
    battery_charging = False
    battery_status = "Unknown"

    try:
        # 1. CPU
        try:
            # interval=0.0 is non-blocking (better for websockets)
            cpu_percent = psutil.cpu_percent(interval=0.0) or psutil.cpu_percent(interval=None)
            cpu_count = psutil.cpu_count(logical=True)
        except: pass

        # 2. Memory
        try:
            mem = psutil.virtual_memory()
            memory_percent = mem.percent
            memory_used_gb = mem.used / (1024**3)
            memory_total_gb = mem.total / (1024**3)
        except: pass

        # 3. Disk
        try:
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_free_gb = disk.free / (1024**3)
            disk_total_gb = disk.total / (1024**3)
        except: pass

        # 4. Network
        try:
            net = psutil.net_io_counters()
            sent_mb = net.bytes_sent / (1024**2)
            recv_mb = net.bytes_recv / (1024**2)
        except: pass

        # 5. System
        try:
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            uptime_str = str(uptime).split('.')[0]
            process_count = len(psutil.pids())
        except: pass

        # 6. Platform
        try:
            system_name = platform.system()
            release = platform.release()
        except: pass

        # 7. BATTERY (The Fix)
        try:
            battery = psutil.sensors_battery()

            # Remove this print after verifying it works
            # print(f"DEBUG BATTERY: {battery}")

            if battery is not None:
                battery_percent = round(battery.percent, 1)
                battery_charging = battery.power_plugged
                battery_status = "Charging" if battery_charging else "Discharging"

                if battery_charging and battery_percent > 99:
                    battery_status = "Fully Charged"
            else:
                battery_percent = 0
                battery_charging = False
                battery_status = "No Battery"
        except Exception as e:
            print(f"Battery Error: {e}")
            battery_status = "Error"

    except Exception as e:
        print(f"Global Vitals Error: {e}")

    # Return constructed dictionary
    return {
        "cpu": {"percent": cpu_percent, "cores": cpu_count, "freq": 0.0},
        "memory": {"percent": memory_percent, "used_gb": round(memory_used_gb, 2), "total_gb": round(memory_total_gb, 2)},
        "disk": {"percent": disk_percent, "free_gb": round(disk_free_gb, 2), "total": round(disk_total_gb, 2)},
        "network": {"sent_mb": round(sent_mb, 2), "recv_mb": round(recv_mb, 2), "connections": 0},
        "system": {"uptime": uptime_str, "processes": process_count, "load": []},
        "platform": {"system": system_name, "release": release},
        "battery": {
            "percent": battery_percent,
            "charging": battery_charging,
            "status": battery_status
        },
        "timestamp": datetime.now().isoformat()
    }

@app.websocket("/ws/system/vitals")
async def websocket_system_vitals(websocket: WebSocket):
    """Real-time system monitoring - saves polling overhead"""
    try:
        # Accept connection first
        await websocket.accept()

        # Wait for authentication token (wait for JSON or text)
        try:
            # Try to receive as JSON first
            data = await websocket.receive_text()
            auth_data = json.loads(data)
            token = auth_data.get("token")

            if not token:
                await websocket.send_json({"error": "Authentication token required"})
                await websocket.close()
                return

        except json.JSONDecodeError:
            # If not JSON, maybe token was sent directly as text
            token = data
            if not token:
                await websocket.send_json({"error": "Invalid authentication data"})
                await websocket.close()
                return

        # Verify the token
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])  # Fixed algorithm
            user_id = payload.get("sub")

            if not user_id:
                await websocket.send_json({"error": "Invalid token payload"})
                await websocket.close()
                return

            # Check if user exists
            users = read_json_file(USERS_FILE)
            if not users or not isinstance(users, list):
                await websocket.send_json({"error": "User database error"})
                await websocket.close()
                return

            user = next((u for u in users if str(u.get("id")) == user_id), None)

            if not user:
                await websocket.send_json({"error": "User not found"})
                await websocket.close()
                return

            print(f"✅ WebSocket authenticated for user: {user.get('email', 'Unknown')}")

        except jwt.ExpiredSignatureError:
            await websocket.send_json({"error": "Token expired"})
            await websocket.close()
            return
        except JWTError as e:
            await websocket.send_json({"error": f"Invalid token: {str(e)}"})
            await websocket.close()
            return

        # Add to connection manager after successful authentication
        await ws_manager.connect_system_vitals(websocket)

        # Send initial data
        vitals = await system_data.get_vitals()
        await websocket.send_json({
            **vitals,
            "authenticated": True,
            "user_email": user.get("email", "User")
        })

        # Main monitoring loop
        while True:
            try:
                # Get shared data
                vitals = await system_data.get_vitals()
                await websocket.send_json(vitals)
                await asyncio.sleep(2)

                # Keep-alive ping
                await websocket.send_json({"type": "ping", "timestamp": datetime.now().isoformat()})

            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"WebSocket send error: {e}")
                break

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"❌ System vitals WebSocket error: {e}")
    finally:
        ws_manager.disconnect(websocket)
@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    """Real-time notifications - saves polling for new events"""
    await ws_manager.connect_notifications(websocket)

    # Track last check times
    last_email_check = datetime.now()
    last_calendar_check = datetime.now()

    try:
        # Send initial welcome
        await websocket.send_json({
            "type": "connected",
            "message": "Notifications WebSocket connected",
            "timestamp": datetime.now().isoformat()
        })

        # Main notification loop
        while True:
            current_time = datetime.now()

            # Check for new emails every 30 seconds (instead of client polling every 5s)
            if (current_time - last_email_check).seconds > 30:
                try:
                    # Simulate checking for new emails
                    await websocket.send_json({
                        "type": "email_check",
                        "timestamp": current_time.isoformat(),
                        "message": "Checking for new emails..."
                    })
                    last_email_check = current_time
                except Exception as e:
                    print(f"Email check error: {e}")

            # Check for calendar updates every 60 seconds
            if (current_time - last_calendar_check).seconds > 60:
                try:
                    await websocket.send_json({
                        "type": "calendar_check",
                        "timestamp": current_time.isoformat(),
                        "message": "Checking for calendar updates..."
                    })
                    last_calendar_check = current_time
                except Exception as e:
                    print(f"Calendar check error: {e}")

            # Keep-alive heartbeat
            await asyncio.sleep(10)

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        print(f"❌ Notifications WebSocket error: {e}")
        ws_manager.disconnect(websocket)


@app.get("/dashboard/system/ports")
def get_active_ports():
    """Get active network ports"""
    try:
        connections = psutil.net_connections(kind='inet')
        active_ports = []
        seen_ports = set()

        for conn in connections:
            if conn.status == 'LISTEN' and conn.laddr:
                port = conn.laddr.port

                if port in seen_ports:
                    continue

                seen_ports.add(port)

                try:
                    proc_name = "System"
                    pid = conn.pid or 0

                    if pid > 0:
                        try:
                            process = psutil.Process(pid)
                            proc_name = process.name()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            proc_name = "Unknown"

                    active_ports.append({
                        "port": port,
                        "process": proc_name,
                        "pid": pid,
                        "status": conn.status,
                        "service": get_service_name(port),
                        "address": conn.laddr.ip if hasattr(conn.laddr, 'ip') else "0.0.0.0"
                    })

                except Exception as e:
                    print(f"⚠️  Port info error: {e}")
                    continue

        # Sort by port number
        active_ports.sort(key=lambda x: x["port"])
        return active_ports[:20]  # Return top 20

    except Exception as e:
        print(f"❌ Ports error: {e}")
        return []

@app.get("/dashboard/system/processes")
def get_processes():
    """Get running processes"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                pinfo = proc.info
                processes.append({
                    "pid": pinfo.get('pid', 0),
                    "name": pinfo.get('name', 'Unknown')[:30],  # Limit name length
                    "cpu": round(pinfo.get('cpu_percent', 0), 1),
                    "memory": round(pinfo.get('memory_percent', 0), 2),
                    "status": "Running"
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # Sort by CPU usage
        processes.sort(key=lambda x: x['cpu'], reverse=True)
        return processes[:15]  # Return top 15

    except Exception as e:
        print(f"❌ Processes error: {e}")
        return []

@app.get("/dashboard/system/hardware")
def get_hardware_info():
    """Get hardware information"""
    try:
        # Temperatures
        temps = {}
        if hasattr(psutil, "sensors_temperatures"):
            sensors = psutil.sensors_temperatures()
            for name, entries in sensors.items():
                if entries and entries[0].current:
                    temps[name] = round(entries[0].current, 1)

        # Fans
        fans = {}
        if hasattr(psutil, "sensors_fans"):
            fans_data = psutil.sensors_fans()
            for name, entries in fans_data.items():
                if entries and entries[0].current:
                    fans[name] = entries[0].current

        hardware_info = {
            "temperatures": temps if temps else {"CPU": 45.0},
            "fans": fans if fans else {"System": 1200},
            "cpu_info": {
                "brand": platform.processor() or "Unknown",
                "cores": psutil.cpu_count(logical=True) or 4,
                "physical_cores": psutil.cpu_count(logical=False) or 4,
                "architecture": platform.architecture()[0]
            },
            "memory_info": {
                "total": round(psutil.virtual_memory().total / (1024**3), 2),
                "available": round(psutil.virtual_memory().available / (1024**3), 2)
            },
            "disk_info": {
                "total": round(psutil.disk_usage('/').total / (1024**3), 2),
                "free": round(psutil.disk_usage('/').free / (1024**3), 2)
            },
            "timestamp": datetime.now().isoformat()
        }

        return hardware_info

    except Exception as e:
        print(f"❌ Hardware error: {e}")
        return {
            "temperatures": {"CPU": 45.0},
            "fans": {"System": 1200},
            "cpu_info": {"brand": "Unknown", "cores": 4, "physical_cores": 4, "architecture": "64-bit"},
            "memory_info": {"total": 8.0, "available": 6.0},
            "disk_info": {"total": 256.0, "free": 128.0},
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

@app.post("/dashboard/system/kill_process/{pid}")
async def kill_process(pid: int, current_user: dict = Depends(get_current_user)):
    """Kill a process by PID"""
    try:
        # Validate PID
        if pid <= 0:
            raise HTTPException(status_code=400, detail="Invalid PID")

        # Check if process exists
        if not psutil.pid_exists(pid):
            raise HTTPException(status_code=404, detail=f"Process with PID {pid} not found")

        try:
            process = psutil.Process(pid)
            process_name = process.name()

            # Try graceful termination first
            process.terminate()

            # Wait for termination
            try:
                process.wait(timeout=3)
                method = "terminated"
            except psutil.TimeoutExpired:
                # Force kill
                process.kill()
                process.wait(timeout=2)
                method = "force killed"

            # Broadcast notification ONLY if clients are connected
            if ws_manager.notification_connections:
                await ws_manager.broadcast_notification(
                    "Process Killed",
                    f"Process '{process_name}' (PID: {pid}) was {method}",
                    "warning"
                )

            return {
                "success": True,
                "message": f"Process '{process_name}' (PID: {pid}) {method} successfully",
                "pid": pid,
                "process_name": process_name,
                "method": method
            }

        except psutil.NoSuchProcess:
            raise HTTPException(status_code=404, detail=f"Process with PID {pid} no longer exists")
        except psutil.AccessDenied:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Cannot kill process {pid}. Try running as administrator."
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error killing process: {str(e)}")

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid PID format")
    except Exception as e:
        print(f"❌ Kill process error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- SYSTEM CLEANUP ENDPOINT ---
@app.post("/dashboard/system/cleanup")
async def system_cleanup(current_user: dict = Depends(get_current_user)):
    """Perform system cleanup tasks"""
    try:
        import tempfile
        import shutil

        cleanup_results = []

        # Clean temp directory
        temp_dir = tempfile.gettempdir()
        temp_files = os.listdir(temp_dir)
        cleaned_temp = 0

        for file in temp_files:
            try:
                file_path = os.path.join(temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    cleaned_temp += 1
            except:
                pass

        cleanup_results.append({
            "task": "Clear Temp Files",
            "result": f"Cleaned {cleaned_temp} files",
            "status": "success"
        })

        # Clear browser cache (simulated)
        browser_cache_paths = [
            os.path.expanduser("~/.cache"),
            os.path.expanduser("~/AppData/Local/Temp")
        ]

        cleaned_cache = 0
        for cache_path in browser_cache_paths:
            if os.path.exists(cache_path):
                try:
                    for root, dirs, files in os.walk(cache_path):
                        for file in files:
                            if file.endswith(('.tmp', '.cache', '.log')):
                                try:
                                    os.remove(os.path.join(root, file))
                                    cleaned_cache += 1
                                except:
                                    pass
                except:
                    pass

        cleanup_results.append({
            "task": "Clear Browser Cache",
            "result": f"Cleaned {cleaned_cache} cache files",
            "status": "success"
        })

        # Broadcast notification ONLY if clients are connected
        if ws_manager.notification_connections:
            await ws_manager.broadcast_notification(
                "System Cleanup Complete",
                f"Cleaned {cleaned_temp} temp files and {cleaned_cache} cache files",
                "success"
            )

        return {
            "status": "success",
            "message": "System cleanup completed",
            "results": cleanup_results,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboard/system/network")
def get_network_info():
    try:
        net_io = psutil.net_io_counters()

        # Get network connections
        connections = len(psutil.net_connections())

        # Get network interfaces
        net_if_addrs = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()

        interfaces = []
        for interface_name, interface_addresses in net_if_addrs.items():
            stats = net_if_stats.get(interface_name)
            if stats:
                interfaces.append({
                    "name": interface_name,
                    "is_up": stats.isup,
                    "speed": stats.speed,
                    "addresses": [str(addr.address) for addr in interface_addresses if addr.family == socket.AF_INET]
                })

        # Get current network speed (bytes per second)
        net_io_old = net_io

        # Wait a bit and get new stats to calculate speed
        time.sleep(1)
        net_io_new = psutil.net_io_counters()

        download_speed = (net_io_new.bytes_recv - net_io_old.bytes_recv)  # bytes per second
        upload_speed = (net_io_new.bytes_sent - net_io_old.bytes_sent)    # bytes per second

        return {
            "download": download_speed,
            "upload": upload_speed,
            "connections": connections,
            "total_download": net_io_new.bytes_recv,
            "total_upload": net_io_new.bytes_sent,
            "interfaces": interfaces[:3],  # Return top 3 interfaces
            "active_interface": interfaces[0]["name"] if interfaces else "Unknown",
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"❌ Network info error: {e}")
        return {
            "download": 0,
            "upload": 0,
            "connections": 0,
            "total_download": 0,
            "total_upload": 0,
            "interfaces": [],
            "active_interface": "Unknown",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

# --- COMMANDS MANAGEMENT ENDPOINTS ---
@app.get("/dashboard/commands")
def get_commands(current_user: dict = Depends(get_current_user)):
    try:
        return get_commands_db()
    except Exception as e:
        print(f"❌ Get commands error: {e}")
        return []

@app.get("/commands/{command_id}")
async def get_command(command_id: str):
    try:
        commands = read_json_file(COMMANDS_FILE)
        print(f"DEBUG: Looking for command_id={command_id}")
        print(f"DEBUG: Available IDs: {[c.get('id', 'NO_ID') for c in commands]}")

        for cmd in commands:
            if cmd.get("id") == command_id:
                return cmd

        # This is where you need HTTPException
        print(f"DEBUG: Command {command_id} not found, raising 404")
        raise HTTPException(status_code=404, detail="Command not found")

    except HTTPException:
        raise
    except Exception as e:
        print(f"DEBUG: Unexpected error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error")

@app.post("/dashboard/commands")
def create_command(command: CommandItem, current_user: dict = Depends(get_current_user)):
    """Create a new command"""
    try:
        # VALIDATION CHECKS (ADD THESE LINES)
        if not validate_command_name(command.name):
            raise HTTPException(status_code=400, detail="Invalid command name. Must be 1-100 characters.")

        if not validate_command_content(command.command):
            raise HTTPException(status_code=400, detail="Invalid or potentially dangerous command.")

        if not validate_command_tags(command.tags):
            raise HTTPException(status_code=400, detail="Invalid tags. Maximum 10 tags, 50 characters each.")

        commands = get_commands_db()
        command_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        command_data = CommandInDB(
            id=command_id,
            **command.dict(),
            created_at=now,
            updated_at=now
        )

        commands.append(command_data.dict())
        save_commands_db(commands)

        # Return success message with the created command
        return {
            "status": "success",
            "message": "Command created successfully",
            "command": command_data.dict()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail="Command not found")

@app.put("/dashboard/commands/{command_id}")
def update_command(command_id: str, command: CommandItem, current_user: dict = Depends(get_current_user)):
    """Update an existing command"""
    try:
        # VALIDATION CHECKS (ADD THESE LINES)
        if not validate_command_name(command.name):
            raise HTTPException(status_code=400, detail="Invalid command name. Must be 1-100 characters.")

        if not validate_command_content(command.command):
            raise HTTPException(status_code=400, detail="Invalid or potentially dangerous command.")

        if not validate_command_tags(command.tags):
            raise HTTPException(status_code=400, detail="Invalid tags. Maximum 10 tags, 50 characters each.")

        commands = get_commands_db()
        command_index = next((i for i, c in enumerate(commands) if c.get("id") == command_id), None)

        if command_index is None:
            raise HTTPException(status_code=404, detail="Command not found")

        updated_data = {
            **commands[command_index],
            **command.dict(),
            "updated_at": datetime.now().isoformat()
        }

        commands[command_index] = updated_data
        save_commands_db(commands)

        # Return success message
        return {
            "status": "success",
            "message": "Command updated successfully",
            "command": updated_data
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Update command error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/dashboard/commands/{command_id}")
def delete_command(command_id: str, current_user: dict = Depends(get_current_user)):  # Added auth dependency
    """Delete a command"""
    try:
        commands = get_commands_db()
        command_to_delete = next((c for c in commands if c.get("id") == command_id), None)

        if not command_to_delete:
            raise HTTPException(status_code=404, detail="Command not found")

        filtered_commands = [c for c in commands if c.get("id") != command_id]
        save_commands_db(filtered_commands)

        return {
            "status": "deleted",
            "command_id": command_id,
            "command_name": command_to_delete.get("name", "Unknown")
        }

    except Exception as e:
        print(f"❌ Delete command error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dashboard/commands/execute")
def execute_command(request: dict, current_user: dict = Depends(get_current_user)):
    """Execute a command (WARNING: Be careful with this!)"""
    try:
        import subprocess

        command = request.get("command")
        if not command:
            raise HTTPException(status_code=400, detail="No command provided")

        # Security: Limit what commands can be executed
        allowed_prefixes = [
            "ls", "pwd", "whoami", "date", "echo", "ps", "df", "uptime",
            "uname", "free", "top", "htop", "netstat", "ifconfig", "ip",
            "systemctl", "service", "journalctl", "docker", "git", "npm",
            "python", "node", "curl", "wget", "grep", "find", "cat", "head",
            "tail", "wc", "du", "who", "last", "ping", "traceroute"
        ]

        # Check if command starts with any allowed prefix
        if not any(command.startswith(prefix) for prefix in allowed_prefixes):
            raise HTTPException(
                status_code=403,
                detail=f"Command not allowed. Only basic system commands are permitted. Allowed: {', '.join(allowed_prefixes[:10])}..."
            )

        # Execute command with timeout
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Command execution timed out")
    except Exception as e:
        print(f"❌ Execute command error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# --- PROJECTS DASHBOARD ENDPOINTS ---
@app.get("/dashboard/projects/search")
def search_projects(
    q: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Search and filter projects"""
    try:
        all_projects = get_projects_db()
        filtered_projects = all_projects

        # Apply search query
        if q:
            query = q.lower()
            filtered_projects = [
                p for p in filtered_projects
                if (query in p.get('name', '').lower() or
                    query in p.get('description', '').lower() or
                    any(query in tech.lower() for tech in p.get('technologies', [])))
            ]

        # Apply status filter
        if status:
            filtered_projects = [p for p in filtered_projects if p.get('status') == status]

        # Apply category filter
        if category:
            filtered_projects = [p for p in filtered_projects if p.get('category') == category]

        # Apply priority filter
        if priority:
            filtered_projects = [p for p in filtered_projects if p.get('priority') == priority]

        return {
            "projects": filtered_projects,
            "count": len(filtered_projects),
            "filters": {
                "search": q,
                "status": status,
                "category": category,
                "priority": priority
            }
        }
    except Exception as e:
        print(f"❌ Projects search error: {e}")
        return {"projects": [], "count": 0, "filters": {}}

@app.get("/dashboard/projects")
def get_projects(current_user: dict = Depends(get_current_user)):
    """Get all projects"""
    try:
        projects = get_projects_db()

        # Calculate stats
        total = len(projects)
        in_progress = len([p for p in projects if p.get('status') == 'in-progress'])
        completed = len([p for p in projects if p.get('status') == 'completed'])
        planning = len([p for p in projects if p.get('status') == 'planning'])
        avg_progress = 0

        if total > 0:
            total_progress = sum(p.get('progress', 0) for p in projects)
            avg_progress = round(total_progress / total)

        return {
            "projects": projects,
            "stats": {
                "total": total,
                "inProgress": in_progress,
                "completed": completed,
                "planning": planning,
                "avgProgress": avg_progress
            }
        }
    except Exception as e:
        print(f"❌ Projects fetch error: {e}")
        return {"projects": [], "stats": {"total": 0, "inProgress": 0, "completed": 0, "planning": 0, "avgProgress": 0}}

@app.get("/dashboard/projects/{project_id}")
def get_project(project_id: str,current_user: dict = Depends(get_current_user)):
    """Get a specific project"""
    try:
        projects = get_projects_db()
        project = next((p for p in projects if p.get("id") == project_id), None)

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project
    except Exception as e:
        raise HTTPException(status_code=404, detail="Project not found")

@app.post("/dashboard/projects")
def create_project(project: ProjectItem,current_user: dict = Depends(get_current_user)):
    """Create a new project"""
    try:
        projects = get_projects_db()
        project_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        # Set lastUpdated if not provided
        if not project.lastUpdated:
            project.lastUpdated = datetime.now().strftime("%Y-%m-%d")

        project_data = ProjectInDB(
            id=project_id,
            **project.dict(),
            created_at=now,
            updated_at=now
        )

        projects.append(project_data.dict())
        save_projects_db(projects)
        return project_data.dict()

    except Exception as e:
        print(f"❌ Create project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/dashboard/projects/{project_id}")
def update_project(project_id: str, project: ProjectItem, current_user: dict = Depends(get_current_user)):
    """Update an existing project"""
    try:
        projects = get_projects_db()
        project_index = next((i for i, p in enumerate(projects) if p.get("id") == project_id), None)

        if project_index is None:
            raise HTTPException(status_code=404, detail="Project not found")

        # Update lastUpdated
        updated_project = project.dict()
        updated_project["lastUpdated"] = datetime.now().strftime("%Y-%m-%d")

        updated_data = {
            **projects[project_index],
            **updated_project,
            "updated_at": datetime.now().isoformat()
        }

        projects[project_index] = updated_data
        save_projects_db(projects)
        return updated_data

    except Exception as e:
        print(f"❌ Update project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/dashboard/projects/{project_id}")
def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a project"""
    try:
        projects = get_projects_db()
        filtered_projects = [p for p in projects if p.get("id") != project_id]

        if len(filtered_projects) == len(projects):
            raise HTTPException(status_code=404, detail="Project not found")

        deleted_project = next(p for p in projects if p.get("id") == project_id)
        save_projects_db(filtered_projects)

        return {
            "status": "deleted",
            "project_id": project_id,
            "project_name": deleted_project.get("name", "Unknown")
        }

    except Exception as e:
        print(f"❌ Delete project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- SIMPLIFIED SYSTEM ENDPOINTS (From provided code) ---
@app.get("/dashboard/system/simple/vitals")
def get_simple_system_vitals():
    """Simplified system vitals endpoint"""
    return {
        "cpu_usage": psutil.cpu_percent(interval=1),
        "memory_usage": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage('/').percent,
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
        "platform": platform.system() + " " + platform.release()
    }

@app.get("/dashboard/system/simple/processes")
def get_simple_processes():
    """Simplified processes endpoint"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'status', 'cpu_percent', 'memory_percent']):
        try:
            processes.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(processes, key=lambda p: p['cpu_percent'], reverse=True)[:20]

@app.get("/dashboard/system/simple/ports")
def get_simple_system_ports():
    """Simplified ports endpoint"""
    connections = psutil.net_connections()
    ports = []
    for conn in connections:
        if conn.status == 'LISTEN':
            ports.append({
                "port": conn.laddr.port,
                "pid": conn.pid,
                "status": conn.status
            })
    return sorted(ports, key=lambda x: x['port'])[:20]

@app.get("/dashboard/system/simple/report")
def get_simple_system_report():
    """Simplified system report"""
    return {
        "hostname": socket.gethostname(),
        "ip_address": socket.gethostbyname(socket.gethostname()),
        "os": platform.system(),
        "release": platform.release(),
        "uptime": str(timedelta(seconds=int(time.time() - psutil.boot_time())))
    }

# --- Initialize sample data ---
def init_sample_projects():
    """Initialize with sample projects if database is empty"""
    projects = get_projects_db()
    if not projects:
        sample_projects = [
            {
                "id": "1",
                "name": "E-Commerce Platform",
                "description": "Full-stack e-commerce solution with React and Node.js",
                "progress": 75,
                "status": "in-progress",
                "technologies": ["React", "Node.js", "MongoDB", "Stripe"],
                "category": "web",
                "priority": "high",
                "lastUpdated": datetime.now().strftime("%Y-%m-%d"),
                "links": {
                    "github": "https://github.com/user/ecommerce",
                    "database": "https://mongodb.com/dashboard",
                    "live": "https://ecommerce-demo.com",
                    "api": "https://api.ecommerce.com/docs"
                },
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            },
            {
                "id": "2",
                "name": "Portfolio Website",
                "description": "Personal portfolio with project showcase",
                "progress": 100,
                "status": "completed",
                "technologies": ["React", "Tailwind CSS", "Framer Motion"],
                "category": "web",
                "priority": "medium",
                "lastUpdated": datetime.now().strftime("%Y-%m-%d"),
                "links": {
                    "github": "https://github.com/user/portfolio",
                    "live": "https://portfolio-demo.com"
                },
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
        ]

        save_projects_db(sample_projects)
        print("📊 Initialized with sample projects")

def init_sample_commands():
    """Initialize with sample commands if database is empty"""
    commands = get_commands_db()
    if not commands:
        sample_commands = [
            {
                "id": "1",
                "name": "Check Disk Space",
                "command": "df -h",
                "description": "Show disk space usage in human readable format",
                "category": "system",
                "tags": ["disk", "storage", "monitoring"],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            },
            {
                "id": "2",
                "name": "List Running Processes",
                "command": "ps aux",
                "description": "List all running processes",
                "category": "system",
                "tags": ["process", "monitoring"],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
        ]

        save_commands_db(sample_commands)
        print("💾 Initialized with sample commands")
# Add this new endpoint
# --- GEMINI CHAT ENDPOINT ---
# --- ADVANCED GEMINI ENDPOINT (Data + Internet + Images) ---
# --- UPDATE YOUR EXISTING CHAT ENDPOINT ---
@app.get("/dashboard/commands/{command_id}")
def get_command(command_id: str, current_user: dict = Depends(get_current_user)):
    """Get a specific command by ID"""
    try:
        commands = get_commands_db()

        for cmd in commands:
            if cmd.get("id") == command_id:
                return cmd

        raise HTTPException(status_code=404, detail="Command not found")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Get command error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/auth/logout")
def logout(current_user: dict = Depends(get_current_user)):
    """Invalidate user's token"""
    user_id = current_user["id"]

    all_tokens = read_json_file(TOKENS_FILE)
    if user_id in all_tokens:
        del all_tokens[user_id]
        write_json_file(TOKENS_FILE, all_tokens)

    return {"message": "Logged out successfully"}

# Initialize sample data
init_sample_projects()
init_sample_commands()

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting System Dashboard API...")
    print("📊 WebSocket Endpoints (Real-time, saves polling):")
    print("  • WS   /ws/system/vitals           - Real-time system monitoring")
    print("  • WS   /ws/notifications           - Event notifications")
    print("  • WS   /ws/commands/status/{id}    - Command execution status")
    print("\n📡 HTTP Endpoints (Keep as-is - no polling needed):")
    print("  • GET  /dashboard/projects         - Projects (changes infrequently)")
    print("  • GET  /dashboard/commands         - Commands (static data)")
    print("  • GET  /dashboard/calendar         - Calendar (user-initiated)")
    print("  • GET  /dashboard/gmail            - Email (user-initiated)")
    print("\n🌐 Server running on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)