from typing import Any,Dict,List
import psutil
from datetime import datetime
import os
from fastapi import  HTTPException,APIRouter
from app.config import logger,sentry_sdk
import tempfile,shutil
router = APIRouter(prefix="/dashboard/system", tags=["System Monitoring"])


@router.get("processes")
def get_processes() -> List[Dict[str, Any]]:
    """
    Retrieves a list of the top resource-consuming processes currently running.

    This endpoint scans the operating system for active processes, retrieves
    their CPU and memory usage, and returns the top 15 sorted by CPU consumption.
    It handles permission errors gracefully (skipping system processes that cannot be accessed).

    Returns:
        List[Dict[str, Any]]: A list of process dictionaries. Each dictionary contains:
            - pid (int): Process ID.
            - name (str): Name of the process (truncated to 30 chars).
            - cpu (float): CPU usage percentage.
            - memory (float): Memory usage percentage.
            - status (str): Current state (e.g., 'running', 'sleeping').

    Raises:
        Returns an empty list [] if the OS call fails, but logs the error to Sentry.
    """
    try:
        processes = []
        attributes = ['pid', 'name', 'cpu_percent', 'memory_percent', 'status']

        for proc in psutil.process_iter(attributes):
            try:
                proc_info = proc.info

                processes.append({
                    "pid": proc_info.get('pid'),
                    "name": proc_info.get('name', 'Unknown')[:30],
                    "cpu": round(proc_info.get('cpu_percent', 0), 1),
                    "memory": round(proc_info.get('memory_percent', 0), 2),
                    "status": proc_info.get('status', 'unknown')  # Real status from OS
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        processes.sort(key=lambda x: x['cpu'], reverse=True)

        return processes[:15]  # Return top 15

    except Exception as e:
        logger.error(f"Failed to fetch process list: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return []

@router.post("/kill_process/{pid}")
async def kill_process(
    pid: int,
) -> Dict[str, Any]:
    """
    Terminates a specific system process by its Process ID (PID).

    This endpoint attempts to stop a process gracefully using SIGTERM.
    If the process refuses to stop after a short timeout, it will be
    forcefully killed using SIGKILL.

    Args:
        pid (int): The unique identifier (Process ID) of the process 
                   to be terminated. Must be a positive integer.

    Returns:
        Dict[str, Any]: A dictionary containing the operation details.
            Example:
            {
                "success": True,
                "message": "Process 'chrome.exe' (PID: 1234) terminated successfully",
                "pid": 1234,
                "process_name": "chrome.exe",
                "method": "terminated"  # or "force killed"
            }

    Raises:
        HTTPException(400): If the PID is invalid (<= 0).
        HTTPException(404): If the process with the given PID is not found.
        HTTPException(403): If the OS denies permission to kill the process 
                            (e.g., trying to kill a system root process).
        HTTPException(500): If an unexpected server-side error occurs.
    """
    try:
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
                # Force kill if it refuses to close
                process.kill()
                process.wait(timeout=2)
                method = "force killed"

            logger.info(f"Process '{process_name}' (PID: {pid}) was {method}")

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
            logger.warning(f"Access denied killing PID {pid}")
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Cannot kill process {pid}. Try running as administrator."
            )
        except Exception as e:
            logger.error(f"Error killing process {pid}: {e}", exc_info=True)
            sentry_sdk.capture_exception(e)
            raise HTTPException(status_code=500, detail=f"Error killing process: {str(e)}")

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid PID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Critical kill_process error: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/system/cleanup")
async def system_cleanup() -> Dict[str, Any]:
    """
    Performs destructive system maintenance to free up disk space.

    This endpoint scans the OS temporary directory and common browser
    cache locations, removing files to recover storage. It returns a
    detailed report of the operation immediately upon completion.

    Returns:
        Dict[str, Any]: A report containing:
            - status (str): "success" or "error".
            - message (str): A summary message for the UI.
            - results (List[Dict]): Breakdown of files removed per task.
            - timestamp (str): ISO execution time.

    Raises:
        HTTPException(500): If a critical unhandled error occurs during cleanup.
    """
    try:
        cleanup_results: List[Dict[str, Any]] = []
        temp_dir = tempfile.gettempdir()
        cleaned_temp = 0

        if os.path.exists(temp_dir):
            try:
                # We use listdir so we can catch individual file errors
                temp_files = os.listdir(temp_dir)
                for file_name in temp_files:
                    file_path = os.path.join(temp_dir, file_name)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            cleaned_temp += 1
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                            cleaned_temp += 1
                    except OSError:
                        pass
            except OSError as e:
                logger.warning(f"Could not list temp directory {temp_dir}: {e}")
                sentry_sdk.capture_message(f"Could not list temp directory "
                                           f"{temp_dir}: {e}",level="warning")
        cleanup_results.append({
            "task": "Clear Temp Files",
            "result": f"Cleaned {cleaned_temp} files",
            "status": "success"
        })

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
                            # Only target likely cache/log files
                            if file.endswith(('.tmp', '.cache', '.log')):
                                try:
                                    os.remove(os.path.join(root, file))
                                    cleaned_cache += 1
                                except OSError:
                                    pass
                except OSError as e:
                    logger.warning(f"Could not walk cache path {cache_path}: {e}")
                    sentry_sdk.capture_message("Could not walk cache path",level="warning")
        cleanup_results.append({
            "task": "Clear Browser Cache",
            "result": f"Cleaned {cleaned_cache} cache files",
            "status": "success"
        })

        total_removed = cleaned_temp + cleaned_cache
        logger.info(f"Cleanup completed. Removed {total_removed} files.")

        return {
            "status": "success",
            "message": f"System cleanup completed. Removed {total_removed} files.",
            "results": cleanup_results,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Critical system cleanup error: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500,
                            detail="System cleanup failed. Check server logs.")