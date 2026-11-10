from datetime import datetime, timedelta, timezone
import asyncio
import psutil
import socket
import platform
import time
from typing import Dict, Any
from app.config import logger, sentry_sdk
from app.db_store import save_system_metric, list_system_metrics


class SystemDataStore:
    """Collects and persists host metrics to PostgreSQL."""
    def __init__(self):
        self.current_vitals = {}
        self.last_update = None
        self.update_lock = asyncio.Lock()

    async def get_vitals(self) -> Dict[str, Any]:
        async with self.update_lock:
            now = datetime.now(timezone.utc)
            if not self.last_update or (now - self.last_update).total_seconds() > 2:
                self.current_vitals = self._collect_system_vitals_data()
                self.last_update = now
                try:
                    await asyncio.to_thread(save_system_metric, self.current_vitals)
                except Exception as exc:
                    logger.error("Could not persist system metrics: %s", exc)
                    sentry_sdk.capture_exception(exc)
            return self.current_vitals

    @staticmethod
    def _collect_system_vitals_data():
        try:
            net_io = psutil.net_io_counters()
            disk = psutil.disk_usage("/")
            mem = psutil.virtual_memory()
            return {
                "cpu": {"percent": psutil.cpu_percent(interval=None), "cores": psutil.cpu_count(), "freq": psutil.cpu_freq().current if psutil.cpu_freq() else 0},
                "memory": {"total": mem.total, "available": mem.available, "percent": mem.percent, "used": mem.used},
                "disk": {"total": disk.total, "used": disk.used, "free": disk.free, "percent": disk.percent},
                "network": {"sent": net_io.bytes_sent, "recv": net_io.bytes_recv, "hostname": socket.gethostname(), "ip": socket.gethostbyname(socket.gethostname())},
                "system": {"platform": platform.system(), "release": platform.release(), "uptime": int(time.time() - psutil.boot_time())},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Error collecting vitals: %s", exc)
            sentry_sdk.capture_exception(exc)
            return {"timestamp": datetime.now(timezone.utc).isoformat()}

    def get_historical_data(self, hours=24):
        try:
            return list_system_metrics(hours)
        except Exception as exc:
            logger.error("Error loading metric history: %s", exc)
            sentry_sdk.capture_exception(exc)
            return []


system_data_store = SystemDataStore()
