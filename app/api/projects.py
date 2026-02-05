import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException ,Query
from typing import Dict, Any, List ,Optional
from app.dependencies import get_current_user
from app.utils.file_ops import (read_json_file, write_json_file, PROJECTS_FILE,
                                logger,  sentry_sdk)
from app.models import ProjectItem, ProjectInDB


router = APIRouter(prefix="/dashboard/projects", tags=["Projects"])


@router.get("/projects", response_model=ProjectInDB)
def get_dashboard_projects(current_user: dict = Depends(get_current_user)) -> Dict[
    str, Any]:
    """
    Fetch all projects and aggregate dashboard statistics.

    This endpoint reads the raw project data, validates it against the
    ProjectInDB schema, and calculates progress and status metrics for
    the frontend dashboard widgets.

    Args:
        current_user (dict): The authenticated user session.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - projects: List of validated ProjectInDB objects as dictionaries.
            - stats: A dictionary containing total, inProgress, completed,
              planning, and avgProgress keys.
    """
    user_id = current_user.get("id")

    try:
        # 1. Fetch Raw Data
        raw_projects = read_json_file(PROJECTS_FILE)

        # 2. FILTER & Validation
        # Only process projects where user_id matches the logged-in user
        projects_validated = [
            ProjectInDB(**p).model_dump()
            for p in raw_projects
            if p.get('user_id') == user_id
        ]

        # 3. Calculate Aggregate Statistics (Now specific to the user)
        total = len(projects_validated)

        in_progress = sum(
            1 for p in projects_validated if p.get('status') == 'in-progress')
        completed = sum(1 for p in projects_validated if p.get('status') == 'completed')
        planning = sum(1 for p in projects_validated if p.get('status') == 'planning')

        avg_progress = 0
        if total > 0:
            total_progress = sum(p.get('progress', 0) for p in projects_validated)
            avg_progress = round(total_progress / total)

        logger.info(f"Successfully fetched {total} projects for user {user_id}")

        return {
            "projects": projects_validated,
            "stats": {
                "total": total,
                "inProgress": in_progress,
                "completed": completed,
                "planning": planning,
                "avgProgress": avg_progress
            }
        }

    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"❌ Projects fetch error for user {user_id}: {str(e)}",
                     exc_info=True)
        return {
            "projects": [],
            "stats": {
                "total": 0, "inProgress": 0, "completed": 0, "planning": 0,
                "avgProgress": 0
            }
        }

@router.post("/projects",response_model=ProjectItem)
def create_project(
        project: ProjectItem,
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Create a new project and add it to the JSON database.

    This function accepts a ProjectItem, enriches it with system metadata
    (UUID, ISO timestamps), validates it using the ProjectInDB schema,
    and appends it to the storage file.

    Args:
        project (ProjectItem): The project details payload.
        current_user (dict): The authenticated user session.

    Returns:
        Dict[str, Any]: The fully created project object including ID.

    Raises:
        HTTPException: Returns 500 if file I/O fails or validation errors occur.
    """
    try:
        # 1. Extract trusted User ID
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=401,
                                detail="User identity not found in token.")

        # 2. Load existing data
        projects = read_json_file(PROJECTS_FILE)

        # 3. Prepare System Metadata
        project_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()

        # Set default lastUpdated if missing (Business Logic)
        if not project.lastUpdated:
            project.lastUpdated = datetime.now().strftime("%Y-%m-%d")

        # 4. Construct the Database Model
        # This is where the 'Ownership' is established
        new_project_model = ProjectInDB(
            id=project_id,
            user_id=user_id,  # <--- THE CRITICAL SECURITY TAG
            created_at=now_iso,
            updated_at=now_iso,
            **project.model_dump()
        )

        # 5. Persistence
        new_project_dict = new_project_model.model_dump()
        projects.append(new_project_dict)
        write_json_file(PROJECTS_FILE, projects)

        logger.info(
            f"🚀 Project created: {project.name} (ID: {project_id}) by user {user_id}")

        return new_project_dict

    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"❌ Create project error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error while creating project."
        )

@router.put("/{project_id}")
def update_project(
        project_id: str,
        project: ProjectItem,
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Update an existing project by ID.

    This function locates a project, merges the new user input with existing
    system metadata (preserving ID and creation date), updates the modification
    timestamps, and persists the changes.

    Args:
        project_id (str): The unique UUID of the project to update.
        project (ProjectItem): The new data payload from the user.
        current_user (dict): The authenticated user session.

    Returns:
        Dict[str, Any]: The fully updated project record.

    Raises:
        HTTPException: 404 if project not found, or 500 for server errors.
    """
    user_id = current_user.get("id")

    try:
        # 1. Load Data
        projects = read_json_file(PROJECTS_FILE)

        # 2. Ownership & Existence Check
        # We find the index only if BOTH the project ID and the owner ID match
        project_index = next(
            (i for i, p in enumerate(projects)
             if p.get("id") == project_id and p.get("user_id") == user_id),
            None
        )

        if project_index is None:
            logger.warning(
                f"Unauthorized/Missing update attempt: Project {project_id} by User {user_id}")
            # Use 404 to avoid leaking whether the project exists for someone else
            raise HTTPException(status_code=404, detail="Project not found ")

        # 3. Prepare the Update Data
        existing_record = projects[project_index]
        user_changes = project.model_dump()

        # Business Logic: Auto-update lastUpdated
        user_changes["lastUpdated"] = datetime.now().strftime("%Y-%m-%d")

        # 4. Merge Data Carefully
        # I unpack: Existing -> User Changes -> System Metadata -> Ownership Lock
        merged_data = {
            **existing_record,
            **user_changes,
            "updated_at": datetime.now().isoformat(),
            "id": project_id,
            "user_id": user_id
        }

        # 5. Validate against Schema
        final_project_model = ProjectInDB(**merged_data)
        final_project_dict = final_project_model.model_dump()

        # 6. Save and Return
        projects[project_index] = final_project_dict
        write_json_file(PROJECTS_FILE, projects)

        logger.info(f"Project {project_id} updated successfully by user {user_id}")

        return final_project_dict

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"❌ Update project error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during update."
        )

@router.delete("{project_id}")
def delete_project(
    project_id: str,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Permanently delete a project by ID.

    This function locates the project to ensure it exists, removes it from
    the list, and persists the changes to the JSON database.

    Args:
        project_id (str): The unique UUID of the project to remove.
        current_user (dict): The authenticated user session.

    Returns:
        Dict[str, str]: A confirmation dictionary containing the deleted
        project's ID and name.

    Raises:
        HTTPException: 404 if the project is not found, or 500 for server errors.
    """
    user_id = current_user.get("id")

    try:
        # 1. Load Data
        projects: List[Dict[str, Any]] = read_json_file(PROJECTS_FILE)

        project_to_delete = next(
            (p for p in projects if
             p.get("id") == project_id and p.get("user_id") == user_id),
            None
        )

        if not project_to_delete:
            # We log the user_id to help identify potential malicious behavior
            logger.warning(
                f"Delete failed: Project {project_id} not found or unauthorized for User {user_id}.")
            raise HTTPException(status_code=404, detail="Project not found")

        # 3. Filter out the project
        # Even though we found it, we use the ID filter to create the new list
        remaining_projects = [p for p in projects if p.get("id") != project_id]

        # 4. Save Changes
        write_json_file(PROJECTS_FILE, remaining_projects)

        logger.info(f"🗑️ Project {project_id} deleted by user {user_id}")

        # 5. Return Rich Confirmation
        return {
            "status": "deleted",
            "project_id": project_id,
            "project_name": project_to_delete.get("name", "Unknown")
        }

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"❌ Delete project error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500,
                            detail="Internal server error during deletion.")

@router.get("/search")
def search_projects(
        q: Optional[str] = Query(None,
                                 description="Search term for name, description, or tech"),
        status: Optional[str] = Query(None, description="Filter by project status"),
        category: Optional[str] = Query(None, description="Filter by project category"),
        priority: Optional[str] = Query(None, description="Filter by priority level"),
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Search and filter projects based on multiple criteria.

    This endpoint retrieves all projects and applies optional filters for
    text search (name/description/technologies), status, category, and priority.

    Args:
        q (Optional[str]): Text query to search within project details.
        status (Optional[str]): Exact match for project status (e.g., 'active').
        category (Optional[str]): Exact match for project category.
        priority (Optional[str]): Exact match for priority level.
        current_user (dict): The authenticated user session.

    Returns:
        Dict[str, Any]: A dictionary containing the list of filtered projects,
        the total count, and a summary of applied filters.

    Raises:
        HTTPException: 500 if the search operation fails.
    """
    user_id = current_user.get("id")

    try:
        # 1. Load Data
        all_projects: List[Dict[str, Any]] = read_json_file(PROJECTS_FILE)

        # 2. MANDATORY OWNERSHIP FILTER
        # This is the security layer: discard anything not owned by this user
        # BEFORE applying search or categorical filters.
        user_projects = [
            p for p in all_projects
            if p.get("user_id") == user_id
        ]

        # 3. Apply Search Query (on user's own data only)
        filtered_projects = user_projects
        if q:
            query = q.lower()
            filtered_projects = [
                p for p in filtered_projects
                if (query in p.get("name", "").lower() or
                    query in p.get("description", "").lower() or
                    any(query in str(tech).lower() for tech in
                        p.get("technologies", [])))
            ]

        # 4. Apply Categorical Filters
        if status:
            filtered_projects = [p for p in filtered_projects if
                                 p.get("status") == status]

        if category:
            filtered_projects = [p for p in filtered_projects if
                                 p.get("category") == category]

        if priority:
            filtered_projects = [p for p in filtered_projects if
                                 p.get("priority") == priority]

        # 5. Log and Return
        if not filtered_projects and (q or status or category):
            logger.info(f"User {user_id}: Search yielded 0 results for query: '{q}'")

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
        sentry_sdk.capture_exception(e)
        # Fixed: using .get("id") instead of "name" for more reliable logging
        logger.error(f"❌ Projects search error for user {user_id}: {str(e)}",
                     exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed due to server error")


@router.get("/{project_id}")
def get_project(
        project_id: str,
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Retrieve details for a specific project.

    This endpoint searches the database for a project matching the provided ID.

    Args:
        project_id (str): The unique identifier of the project (UUID).
        current_user (dict): The authenticated user session.

    Returns:
        Dict[str, Any]: The project dictionary object.

    Raises:
        HTTPException: 404 if the project is not found.
        HTTPException: 500 if the database cannot be read.
    """
    user_id = current_user.get("id")

    try:
        # 1. Load Data
        projects: List[Dict[str, Any]] = read_json_file(PROJECTS_FILE)

        # 2. Secured Search Logic
        # We search for a match where BOTH the project ID and the owner ID match.
        project = next(
            (p for p in projects if
             p["id"] == project_id and p.get("user_id") == user_id),
            None
        )

        # 3. Handle "Not Found" or "Unauthorized"
        # We return a 404 for both cases so we don't leak information about
        # whether a project ID belonging to someone else actually exists.
        if not project:
            logger.warning(
                f"Unauthorized or non-existent access attempt: User {user_id} -> Project {project_id}"
            )
            raise HTTPException(status_code=404, detail="Project not found")

        # 4. Success
        return project

    except HTTPException:
        raise

    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"❌ Error retrieving project {project_id}: {str(e)}",
                     exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching project"
        )