import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.dependencies import get_current_user
from app.utils.file_ops import read_json_file, write_json_file, COMMANDS_FILE
from app.models import CommandItem, CommandInDB
from typing import Dict,Any
from app.config import logger,sentry_sdk
import re
import subprocess
router = APIRouter(prefix="/dashboard/commands", tags=["Commands"])


DANGEROUS_CHARS_PATTERN = re.compile(r'[;&|`$]')

@router.get("/commands", response_model=List[CommandInDB])
def get_all_commands(current_user: Dict[str, Any] = Depends(get_current_user)) -> List[
    CommandInDB]:
    """
    Retrieves the list of available voice commands configuration.

    Reads from the local JSON storage to provide the frontend with the list
    of active voice triggers. Requires an authenticated user session.

    Args:
        current_user (Dict[str, Any]): The authenticated user context provided
                                       by the dependency injector.

    Returns:
        List[CommandInDB]: A list of command objects validated against the schema.

    Raises:
        HTTPException (500): If the JSON file is missing, corrupt, or unreadable.
    """
    user_id = current_user.get("id", "unknown")
    try:
        # Attempt to read the file
        commands_data = read_json_file(COMMANDS_FILE)
        user_commands = [
            cmd for cmd in commands_data
            if cmd.get("user_id") == user_id
        ]


        logger.debug(
            f"Successfully loaded {len(user_commands)} commands for User {user_id}.")
        return user_commands

    except FileNotFoundError:
        error_msg = f"Commands file not found at: {COMMANDS_FILE}"
        logger.error(error_msg)
        sentry_sdk.capture_message(error_msg, level="warning")
        return []

    except Exception as e:
        logger.error(f"Critical error loading commands: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=500,
            detail="System was unable to load command configuration."
        )

@router.post("/commands", response_model=Dict[str, Any], status_code=201)
def create_command(
        cmd: CommandItem,
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Creates a new  command configuration for the authenticated user.

    Accepts a command definition, generates a unique ID and timestamps,
    and persists it to the local JSON storage.

    Args:
        cmd (CommandItem): The payload containing the command trigger and action.
        current_user (Dict[str, Any]): The authenticated user context.

    Returns:
        Dict[str, Any]: The fully created command object including ID and timestamps.

    Raises:
        HTTPException (500): If the file write operation fails.
    """
    user_id = current_user.get("id", "unknown")
    logger.info(f"User {user_id} is attempting to add command: '{cmd.title}'")

    try:
        commands = read_json_file(COMMANDS_FILE)
        new_cmd = cmd.model_dump()
        new_cmd_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        new_cmd.update({
            "id": new_cmd_id,
            "user_id": user_id,
            "created_at": timestamp,
            "updated_at": timestamp
        })
        commands.append(new_cmd)
        write_json_file(COMMANDS_FILE, commands)
        return new_cmd
    except Exception as e:
        logger.error(f"Failed to save command '{cmd.title}' for user {user_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=500,
            detail="Could not save the new command. Please try again."
        )

@router.delete("/{command_id}", response_model=Dict[str, str])
def delete_command(
    command_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Permanently deletes a specific command configuration.

    Locates the command by ID and removes it from the JSON storage.
    If the command ID does not exist, a 404 error is returned.

    Args:
        command_id (str): The unique UUID of the command to delete.
        current_user (Dict[str, Any]): The authenticated user context.

    Returns:
        Dict[str, str]: A confirmation message upon successful deletion.

    Raises:
        HTTPException (404): If no command matches the provided ID.
        HTTPException (500): If the file write operation fails.
    """
    user_id = current_user.get("id")
    logger.info(f"User {user_id} requested deletion of command: {command_id}")

    try:
        commands = read_json_file(COMMANDS_FILE)


        command_to_delete = next(
            (c for c in commands if
             c.get("id") == command_id and c.get("user_id") == user_id),
            None
        )

        if not command_to_delete:
            logger.warning(
                f"Delete failed: Command {command_id} not found or unauthorized for User {user_id}.")
            # Return 404 to hide whether the command exists or not (Security Best Practice)
            raise HTTPException(
                status_code=404,
                detail="Command not found."
            )

        new_commands = [c for c in commands if c.get("id") != command_id]

        # 3. Save Changes
        write_json_file(COMMANDS_FILE, new_commands)

        logger.info(f"Successfully deleted command {command_id} for User {user_id}.")
        return {"status": "deleted", "id": command_id}

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Critical error deleting command {command_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=500,
            detail="System could not delete the command. Please try again."
        )


@router.get("/{command_id}", response_model=Dict[str, Any])
def get_command(
        command_id: str,
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Retrieves the details of a single command by its ID.

    Iterates through the local storage to find a matching command ID.
    Returns 404 if the ID does not exist.

    Args:
        command_id (str): The unique UUID of the command to retrieve.
        current_user (Dict[str, Any]): The authenticated user context.

    Returns:
        Dict[str, Any]: The complete command object.

    Raises:
        HTTPException (404): If the command ID is not found.
        HTTPException (500): If the file system is unreadable.
    """
    user_id = current_user.get("id")
    logger.debug(f"User {user_id} fetching details for command {command_id}")

    try:
        commands = read_json_file(COMMANDS_FILE)

        # 1. Secure Search
        # We look for a match on BOTH the Command ID and the User ID.
        command = next(
            (cmd for cmd in commands if
             cmd.get("id") == command_id and cmd.get("user_id") == user_id),
            None
        )

        if not command:
            logger.warning(
                f"Command {command_id} not found or unauthorized for User {user_id}")
            # Corrected status code from 500 to 404 for 'Not Found'
            raise HTTPException(
                status_code=404,
                detail="Command not found"
            )

        return command

    except HTTPException:
        # Pass 404s through without logging them as system errors
        raise

    except Exception as e:
        logger.error(f"Error retrieving command {command_id}: {e}")
        sentry_sdk.capture_exception(e)

        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.put("/{command_id}", response_model=Dict[str, Any])
def update_command(
        command_id: str,
        command_data: CommandItem,
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Updates an existing command configuration.

    Performs validation on the input data (name length, dangerous characters, tags),
    updates the record in the local JSON storage, and updates the timestamp.

    Args:
        command_id (str): The unique UUID of the command to update.
        command_data (CommandItem): The new data payload.
        current_user (Dict[str, Any]): The authenticated user context.

    Returns:
        Dict[str, Any]: A success message and the updated command object.

    Raises:
        HTTPException (400): If validation fails (bad name, dangerous chars, etc.).
        HTTPException (404): If the command ID does not exist.
        HTTPException (500): If the file write operation fails.
    """
    user_id = current_user.get("id")
    logger.info(f"User {user_id} attempting to update command {command_id}")

    if not command_data.title or len(command_data.title) > 100:
        raise HTTPException(
            status_code=400,
            detail="Title must be between 1 and 100 characters."
        )

    if DANGEROUS_CHARS_PATTERN.search(command_data.action):
        logger.warning(f"Security Alert: User {user_id} used illegal chars.")
        raise HTTPException(
            status_code=400,
            detail="Command action contains illegal characters."
        )

    try:
        commands = read_json_file(COMMANDS_FILE)
        command_index = next(
            (i for i, c in enumerate(commands)
             if c.get("id") == command_id and c.get("user_id") == user_id),
            None
        )

        if command_index is None:
            logger.warning(
                f"Update unauthorized or not found: {command_id} for User {user_id}")
            raise HTTPException(
                status_code=404,
                detail="Command not found"
            )

        # --- 3. Apply Update ---
        update_payload = command_data.model_dump(exclude_none=True)
        current_command = commands[command_index]

        updated_command = current_command.copy()
        updated_command.update(update_payload)

        # Ensure metadata remains consistent
        updated_command["updated_at"] = datetime.now().isoformat()
        updated_command["id"] = command_id  # Prevent ID hijacking
        updated_command["user_id"] = user_id  # Prevent ownership hijacking

        # Save
        commands[command_index] = updated_command
        write_json_file(COMMANDS_FILE, commands)

        logger.info(f"Successfully updated command {command_id} for User {user_id}")

        return {
            "status": "success",
            "message": "Command updated successfully",
            "command": updated_command
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Critical error updating command {command_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=500,
            detail="System was unable to update the command."
        )


@router.post("/execute", response_model=Dict[str, Any])
def execute_command(
    request: Dict[str, str],
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Executes a system shell command with strict prefix limitations.

    WARNING: usage of 'shell=True' implies significant security risks.
    Ensure 'allowed_prefixes' is maintained strictly.

    Args:
        request (Dict[str, str]): JSON body containing the "command" string.
        current_user (Dict[str, Any]): The authenticated user context.

    Returns:
        Dict[str, Any]: The stdout, stderr, and return code of the command.

    Raises:
        HTTPException (400): If no command is provided.
        HTTPException (403): If the command is not in the allowed allowlist.
        HTTPException (408): If the command takes longer than 10 seconds.
        HTTPException (500): If an unexpected system error occurs.
    """
    user_id = current_user.get("id", "unknown")
    command = request.get("command")

    # 1. Input Validation
    if not command:
        logger.warning(f"User {user_id} tried to execute an empty command.")
        raise HTTPException(
            status_code=400,
            detail="No command provided"
        )

    # 2. Security Check (Allowlist)
    allowed_prefixes = [
        "ls", "pwd", "whoami", "date", "echo", "ps", "df", "uptime",
        "uname", "free", "top", "htop", "netstat", "ifconfig", "ip",
        "systemctl", "service", "docker", "git", "npm",
        "python", "node", "curl", "wget", "grep", "find", "cat", "head",
        "tail", "wc", "du", "who", "last", "ping", "traceroute"
    ]


    if not any(command.startswith(prefix) for prefix in allowed_prefixes):
        logger.warning(f"Security Alert: User {user_id} attempted unauthorized command: '{command}'")
        raise HTTPException(
            status_code=500,
            detail=f"Command not allowed. Allowed prefixes: {', '.join(allowed_prefixes[:5])}..."
        )

    logger.info(f"User {user_id} executing system command: '{command}'")

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            logger.info(f"Command '{command}' failed with code {result.returncode}")

        return {
            "status": "success" if result.returncode == 0 else "error",
            "return_code": result.returncode,
            "stdout": result.stdout.strip() if result.stdout else "",
            "stderr": result.stderr.strip() if result.stderr else ""
        }

    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out for User {user_id}: '{command}'")
        raise HTTPException(
            status_code=500,
            detail="Command execution timed out (limit: 10s)"
        )

    except Exception as e:
        logger.critical(f"Critical execution error for User {user_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during command execution."
        )