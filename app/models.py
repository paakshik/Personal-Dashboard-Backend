from pydantic import BaseModel
from typing import Optional, List

# --- Google / Calendar ---
class EventItem(BaseModel):
    """Google Calendar event for dashboard display."""
    summary: str  # Event title
    start_time: str  # ISO format: "2024-01-15T10:00:00"
    end_time: str  # ISO format: "2024-01-15T11:00:00"
    description: Optional[str] = ""  # Additional event details
    location: Optional[str] = ""  # Physical or virtual location

class GoogleAuthData(BaseModel):
    """OAuth authorization data from Google callback."""
    credential: str  # Authorization code from Google

# --- Todoist ---
class TaskItem(BaseModel):
    """Task to create in Todoist."""
    content: str  # Main task text
    description: Optional[str] = ""  # Additional notes
    project_id: Optional[int] = None  # Todoist project ID
    labels: Optional[List[str]] = []  # Tags for categorization

# --- Projects ---
class ProjectLink(BaseModel):
    """URL links for project resources."""
    github: Optional[str] = ""  # Repository URL
    database: Optional[str] = ""  # Database schema/diagram URL
    live: Optional[str] = ""  # Live deployment URL
    api: Optional[str] = ""  # API documentation URL

class ProjectItem(BaseModel):
    """Project data for creation/update."""
    name: str  # Project name
    user_id: str  # User identifier for project
    description: str  # Detailed project description
    progress: int = 0  # 0-100 completion percentage
    status: str = "planning"  # planning/in_progress/completed/on_hold
    technologies: List[str] = []  # Used technologies/languages
    category: str = "web"  # web/mobile/data/devops/other
    priority: str = "medium"  # low/medium/high/critical
    lastUpdated: str = ""  # ISO timestamp of last update
    links: ProjectLink = ProjectLink()  # Related URLs

class ProjectInDB(ProjectItem):
    """Project with database metadata."""
    id: str  # Unique identifier (UUID)
    user_id:str # User identifier for project
    created_at: str  # ISO timestamp of creation
    updated_at: str  # ISO timestamp of last update

# --- Commands ---
class CommandItem(BaseModel):
    """System/terminal command with metadata."""
    name: str  # Display name
    user_id: str  # User identifier for project
    command: str  # Actual command to execute
    description: Optional[str] = ""  # What the command does
    category: Optional[str] = "general"  # general/docker/git/database/etc.
    tags: Optional[List[str]] = []  # Searchable tags

class CommandInDB(CommandItem):
    """Command with database metadata."""
    id: str  # Unique identifier (UUID)
    user_id: str  # User identifier for project
    created_at: str  # ISO timestamp of creation
    updated_at: str  # ISO timestamp of last update

class TodoistTaskResponse(BaseModel):
    id: str
    content: str
    description: str = ""  # Default empty string if missing
    project_id: Optional[str] = None
    due: Optional[dict] = None  # Keeps the Todoist 'due' object structure
    labels: List[str] = []
    priority: int = 1
    is_completed: bool = False
