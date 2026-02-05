from datetime import datetime, timedelta
import asyncio
from app.utils.file_ops import write_json_file, read_json_file
import psutil
import socket
import platform
import time
from app.config import logger,sentry_sdk
from typing import  Dict, Any

class SystemDataStore:
    """Shared data store with JSON file persistence"""

    def __init__(self, json_file_path="backend\dashboard_data\system_metrics.json"):
        self.current_vitals = {}
        self.last_update = None
        self.update_lock = asyncio.Lock()
        self.json_file_path = json_file_path
        self._stored_metrics = []

        self._load_existing_data()

    def _load_existing_data(self) -> None:
        """
        Loads system metrics from the JSON storage file.

        This method:
        1. Calls the shared `read_json_file` utility to read data.
        2. Ensures the loaded data is a list (the expected format).
        3. Enforces a maximum history by keeping only the 100 most recent entries.
        4. Initializes the internal `_stored_metrics` state.

        Behavior:
            - If the file is missing or contains invalid JSON, `read_json_file` returns an empty list `[]`.
            - If the loaded list has more than 100 items, only the last 100 are kept.
            - The result is stored in `self._stored_metrics` for use by other class methods.
        """
        existing_data = read_json_file(self.json_file_path)
        if isinstance(existing_data, list):
            self._stored_metrics = existing_data[-100:] if len(
                existing_data) > 100 else existing_data
        else:
            # case   not needed just for safer side
            self._stored_metrics = []

    async def get_vitals(self) -> Dict[str, Any]:
        """
        Get current system vitals with intelligent refresh control.

        This method implements a simple caching mechanism to prevent excessive
        data collection. It only updates the vitals if the current data is
        considered stale (older than 2 seconds).

        Flow:
            1. Acquire lock to ensure thread-safe updates
            2. Check if data is stale (never updated or older than 2 seconds)
            3. If stale, collect fresh data, update timestamp, and store it
            4. Return the current vitals (either cached or freshly collected)

        Returns:
            Dict[str, Any]: Current system vitals data containing metrics like
            CPU usage, memory usage, disk usage, etc.

        Note:
            The 2-second threshold balances data freshness with system resource
            consumption. Adjust based on your monitoring needs.
        """
        async with self.update_lock:
            now = datetime.now()

            if not self.last_update or (now - self.last_update).total_seconds() > 2:
                self.current_vitals = self._collect_system_vitals_data()
                self.last_update = now

                await self._store_current_vitals()

            return self.current_vitals

    async def _store_current_vitals(self) -> None:
        """
        Asynchronously store current system vitals to JSON storage.

        This method:
        1. Appends the current vitals to the in-memory history list
        2. Enforces a maximum history limit (1000 entries) by trimming old data
        3. Offloads the blocking file write operation to a thread pool to keep
           the async event loop responsive for WebSocket/API requests

        Flow:
            Memory: [old_data...] + current_vitals → Trim if >1000 → Write to disk

        Note:
            Using `asyncio.to_thread()` is crucial here because `write_json_file`
            performs blocking disk I/O. Without this, your entire async application
            would stall during file writes.

        Raises:
            Logs exceptions but doesn't re-raise them to prevent breaking the
            main vitals collection flow. Failed writes are silently ignored.
        """
        try:
            self._stored_metrics.append(self.current_vitals)

            max_data_points = 1000
            if len(self._stored_metrics) > max_data_points:
                self._stored_metrics = self._stored_metrics[-max_data_points:]

            # This ensures your WebSocket/API remains responsive while disk writes happen
            await asyncio.to_thread(write_json_file, self.json_file_path, self._stored_metrics)

        except Exception as e:
            logger.error(f"Error storing current vitals: {e}")
            sentry_sdk.capture_exception(e, extra={
                "metrics_count": len(self._stored_metrics),
                "file_path": str(self.json_file_path)
            })

    @staticmethod
    def _collect_system_vitals_data():
        """Gather system stats using psutil"""
        try:
            net_io = psutil.net_io_counters()
            disk = psutil.disk_usage('/')
            mem = psutil.virtual_memory()

            return {
                "cpu": {
                    # psutil.cpu_percent(interval=None) is correct here because
                    # we only call this function every 2 seconds.
                    "percent": psutil.cpu_percent(interval=None),
                    "cores": psutil.cpu_count(),
                    "freq": psutil.cpu_freq().current if psutil.cpu_freq() else 0
                },
                "memory": {
                    "total": mem.total,
                    "available": mem.available,
                    "percent": mem.percent,
                    "used": mem.used
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                },
                "network": {
                    "sent": net_io.bytes_sent,
                    "recv": net_io.bytes_recv,
                    "hostname": socket.gethostname(),
                    "ip": socket.gethostbyname(socket.gethostname())
                },
                "system": {
                    "platform": platform.system(),
                    "release": platform.release(),
                    "uptime": int(time.time() - psutil.boot_time())
                },
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error collecting vitals: {e}")
            sentry_sdk.capture_exception(e)
            return {}

    def get_historical_data(self, hours=24):
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            recent_data = [
                entry for entry in self._stored_metrics
                if "timestamp" in entry and
                   datetime.fromisoformat(entry["timestamp"]) >= cutoff_time
            ]
            return recent_data
        except Exception as e:
            logger.error(f"Error getting historical data: {e}")
            sentry_sdk.capture_exception(e)
            return []

# Global instance
system_data_store = SystemDataStore()