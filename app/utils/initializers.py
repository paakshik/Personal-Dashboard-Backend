"""
app/utils/initializers.py

One-time initialization helpers for sample data.

These functions are called at app startup to populate the database
with sample projects and commands if they don't already exist.
"""

from app.utils.file_ops import read_json_file, write_json_file
from app.config import PROJECTS_FILE, COMMANDS_FILE, logger, sentry_sdk
from datetime import datetime, timezone
import uuid


def init_sample_projects() -> None:
    """
    Initialize sample projects if the database is empty.

    This function is called at app startup. It checks if any projects exist.
    If not, it adds 3 sample projects so users have something to see immediately.

    Sample projects demonstrate:
    - Different statuses (planning, in-progress, completed)
    - Different priorities (low, medium, high)
    - Different categories (web, mobile, data)
    - Different progress levels (0%, 50%, 100%)
    """
    try:
        projects = read_json_file(PROJECTS_FILE)

        # Only add samples if database is empty
        if len(projects) > 0:
            logger.debug(f"Sample projects already exist ({len(projects)} total)")
            return

        sample_projects = [
            {
                "id": str(uuid.uuid4()),
                "user_id": "system",  # Mark as system-generated
                "name": "Personal Dashboard",
                "description": "A full-stack dashboard integrating Google Services, Todoist, and Gemini AI. Built with FastAPI and React.",
                "progress": 75,
                "status": "in-progress",
                "technologies": ["FastAPI", "React", "PostgreSQL", "Google APIs", "Gemini AI"],
                "category": "web",
                "priority": "high",
                "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "links": {
                    "github": "https://github.com/yourusername/personal-dashboard",
                    "database": "",
                    "live": "https://dashboard.example.com",
                    "api": "https://api.dashboard.example.com/docs"
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "user_id": "system",
                "name": "E-Commerce Platform",
                "description": "Scalable e-commerce platform with real-time inventory management and payment processing.",
                "progress": 45,
                "status": "in-progress",
                "technologies": ["Node.js", "Express", "MongoDB", "Stripe", "AWS"],
                "category": "web",
                "priority": "high",
                "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "links": {
                    "github": "https://github.com/yourusername/ecommerce",
                    "database": "https://db.example.com/schema",
                    "live": "",
                    "api": ""
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "user_id": "system",
                "name": "Data Analysis Tool",
                "description": "Python-based tool for analyzing large datasets with visualization and reporting capabilities.",
                "progress": 20,
                "status": "planning",
                "technologies": ["Python", "Pandas", "NumPy", "Matplotlib", "Jupyter"],
                "category": "data",
                "priority": "medium",
                "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "links": {
                    "github": "",
                    "database": "",
                    "live": "",
                    "api": ""
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        ]

        write_json_file(PROJECTS_FILE, sample_projects)
        logger.info(f"✅ Initialized {len(sample_projects)} sample projects")

    except Exception as e:
        logger.error(f"Error initializing sample projects: {e}")
        sentry_sdk.capture_exception(e)
        # Don't crash on sample data errors


def init_sample_commands() -> None:
    """
    Initialize sample commands if the database is empty.

    This function is called at app startup. It checks if any commands exist.
    If not, it adds useful system commands that users can reference.

    Sample commands demonstrate:
    - Different categories (git, docker, database, general)
    - Different use cases (file operations, system info, development)
    """
    try:
        commands = read_json_file(COMMANDS_FILE)

        # Only add samples if database is empty
        if len(commands) > 0:
            logger.debug(f"Sample commands already exist ({len(commands)} total)")
            return

        sample_commands = [
            {
                "id": str(uuid.uuid4()),
                "user_id": "system",
                "name": "List Directory Contents",
                "command": "ls -lah",
                "description": "List all files and directories with details (including hidden files)",
                "category": "general",
                "tags": ["files", "list", "directory"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "user_id": "system",
                "name": "Git Status",
                "command": "git status",
                "description": "Show the current git repository status and changes",
                "category": "git",
                "tags": ["git", "status", "version-control"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "user_id": "system",
                "name": "Docker Containers",
                "command": "docker ps -a",
                "description": "List all Docker containers (running and stopped)",
                "category": "docker",
                "tags": ["docker", "containers", "devops"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "user_id": "system",
                "name": "Check Disk Usage",
                "command": "df -h",
                "description": "Display disk space usage for all mounted filesystems",
                "category": "general",
                "tags": ["disk", "storage", "system"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "user_id": "system",
                "name": "View System Information",
                "command": "uname -a",
                "description": "Display detailed information about the system and kernel",
                "category": "general",
                "tags": ["system", "info", "kernel"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        ]

        write_json_file(COMMANDS_FILE, sample_commands)
        logger.info(f"✅ Initialized {len(sample_commands)} sample commands")

    except Exception as e:
        logger.error(f"Error initializing sample commands: {e}")
        sentry_sdk.capture_exception(e)
        # Don't crash on sample data errors