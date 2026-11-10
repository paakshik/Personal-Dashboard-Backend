from typing import Any, Dict, List, Optional
import re
import subprocess
import shlex
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.db_store import list_commands, get_command as db_get_command, save_command, delete_command as db_delete_command
from app.models import CommandItem, CommandInDB
from app.config import logger, sentry_sdk

router = APIRouter(prefix="/dashboard/commands", tags=["Commands"])
DANGEROUS_CHARS_PATTERN = re.compile(r'[;&|`$]')


@router.get("", response_model=List[CommandInDB])
def get_all_commands(current_user: Dict[str, Any] = Depends(get_current_user)):
    return list_commands(current_user["id"])


@router.post("", response_model=CommandInDB, status_code=201)
def create_command(cmd: CommandItem, current_user: Dict[str, Any] = Depends(get_current_user)):
    return save_command(current_user["id"], cmd.model_dump())


@router.delete("/{command_id}")
def remove_command(command_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    if not db_delete_command(current_user["id"], command_id):
        raise HTTPException(status_code=404, detail="Command not found")
    return {"status": "deleted", "id": command_id}


@router.get("/search", response_model=List[CommandInDB])
def search_commands(q: Optional[str] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    commands = list_commands(current_user["id"])
    if q:
        term = q.casefold()
        commands = [x for x in commands if term in x["name"].casefold() or term in x["command"].casefold() or term in x["description"].casefold() or any(term in tag.casefold() for tag in x["tags"])]
    return commands


@router.get("/{command_id}", response_model=CommandInDB)
def get_command(command_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    command = db_get_command(current_user["id"], command_id)
    if not command:
        raise HTTPException(status_code=404, detail="Command not found")
    return command


@router.put("/{command_id}")
def update_command(command_id: str, command_data: CommandItem, current_user: Dict[str, Any] = Depends(get_current_user)):
    if not command_data.name or len(command_data.name) > 100:
        raise HTTPException(status_code=400, detail="Name must be between 1 and 100 characters.")
    if DANGEROUS_CHARS_PATTERN.search(command_data.command):
        raise HTTPException(status_code=400, detail="Command action contains illegal characters.")
    updated = save_command(current_user["id"], command_data.model_dump(), command_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Command not found")
    return {"status": "success", "message": "Command updated successfully", "command": updated}


@router.post("/{command_id}/execute")
def execute_command(command_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    command = db_get_command(current_user["id"], command_id)
    if not command:
        raise HTTPException(status_code=404, detail="Command not found")
    value = command["command"].strip()
    allowed = ("ls", "pwd", "whoami", "date", "echo", "ps", "df", "uptime", "uname", "free", "top", "htop", "docker", "git", "npm", "python", "node", "curl", "wget", "grep", "find", "cat", "head", "tail", "wc", "du", "ping")
    try:
        argv = shlex.split(value, posix=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid command syntax") from exc
    if not argv or argv[0] not in allowed or any(token in {";", "&&", "||", "|", ">", "<", "`"} for token in argv):
        raise HTTPException(status_code=403, detail="Command is not allowed for security reasons.")
    try:
        result = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=10)
        return {"status": "success" if result.returncode == 0 else "error", "return_code": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Command timed out (limit: 10s)")
