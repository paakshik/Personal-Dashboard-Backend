from app.services.system_data_store import system_data_store
from typing import Any,Dict,List
import time
import psutil
from datetime import datetime,  timedelta
import socket
import platform
from fastapi import  APIRouter
from app.config import logger,sentry_sdk


router = APIRouter(prefix="/dashboard/system", tags=["System Monitoring"])

# GLOBAL STATE (Simple Cache)
_last_net_stats = {
    "time": 0.0,
    "bytes_recv": 0,
    "bytes_sent": 0
}

@router.get("/current")
async def get_current_metrics() -> Dict[str, Any]:
    """
    Retrieves the latest snapshot of system vital metrics.

    Fetches real-time data regarding CPU usage, memory consumption,
    disk space, and other key system performance indicators from the
    central data store.

    Returns:
        Dict[str, Any]: A dictionary containing key-value pairs of system metrics.
    """
    return await system_data_store.get_vitals()


@router.get("info")
def get_system_info() -> Dict[str, str]:
    """
    Retrieves static system metadata and identity information.

    This endpoint returns constant details about the host server, such as the
    operating system version, hostname, and current uptime. It is designed
    to be called once upon application load to identify the server in the UI.

    Returns:
        Dict[str, str]: A dictionary containing:
            - hostname (str): The network name of the machine.
            - ip_address (str): The internal IP address.
            - os (str): The operating system name (e.g., 'Windows', 'Linux').
            - release (str): The OS version release.
            - uptime (str): Human-readable duration since last boot.

    Raises:
        Returns a fallback dictionary with "Unknown" values if system calls fail,
        while logging the specific error to Sentry.
    """
    try:
        # UPTIME EXPLAINER:
        # Short uptime (< 10 mins) = WARNING: Server might be crashing and restarting constantly.
        # Long uptime (> 100 days) = WARNING: Server might be slow due to memory leaks. Needs a reboot.
        boot_time = psutil.boot_time()
        uptime_seconds = int(time.time() - boot_time)
        return {
            "hostname": socket.gethostname(),
            "ip_address": socket.gethostbyname(socket.gethostname()),
            "os": platform.system(),
            "release": platform.release(),
            "uptime": str(timedelta(seconds=uptime_seconds))  # e.g., "2 days, 4:20:00"
        }

    except Exception as e:
        logger.error(f"Failed to fetch system info: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return {
            "hostname": "Unknown Host",
            "ip_address": "0.0.0.0",
            "os": "Unknown OS",
            "release": "N/A",
            "uptime": "Unknown"
        }


@router.get("ports")
def get_active_ports() -> List[Dict[str, Any]]:
    """
    Retrieves a list of active network ports currently listening for connections.

    This endpoint scans network sockets to identify services running on the host.
    It resolves the Process ID (PID) to a human-readable process name and
    attempts to identify the service associated with the port (e.g., 80 -> http).

    Returns:
        List[Dict[str, Any]]: A list of dictionaries, each containing:
            - port (int): The port number (e.g., 8080).
            - process (str): Name of the process owning the port (e.g., 'python.exe').
            - pid (int): Process ID.
            - service (str): Standard service name (e.g., 'http', 'ssh').
            - status (str): Connection status (should be 'LISTEN').
            - address (str): The IP address bound to the socket.

    Raises:
        Returns an empty list [] if the OS network call fails, logging the error to Sentry.
    """
    try:
        connections = psutil.net_connections(kind='inet')
        active_ports = []
        seen_ports = set()

        for conn in connections:
            # We only want listening ports (servers), not outgoing connections
            if conn.status == 'LISTEN' and conn.laddr:
                port = conn.laddr.port

                # 1. Deduplication: psutil often lists the same port for IPv4 and IPv6
                if port in seen_ports:
                    continue
                seen_ports.add(port)

                try:
                    proc_name = "System/Unknown"
                    pid = conn.pid or 0

                    # 2. Resolve PID -> Process Name
                    if pid > 0:
                        try:
                            # catch AccessDenied for system processes
                            process = psutil.Process(pid)
                            proc_name = process.name()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                            # 3. Resolve Port -> Service Name (Using built-in socket lib)
                    try:
                        service_name = socket.getservbyport(port)
                    except OSError:
                        service_name = "unknown"

                    active_ports.append({
                        "port": port,
                        "process": proc_name,
                        "pid": pid,
                        "status": conn.status,
                        "service": service_name,
                        "address": conn.laddr.ip if hasattr(conn.laddr,
                                                            'ip') else "0.0.0.0"
                    })

                except Exception as e:
                    logger.warning(f"Skipping port {port}: {e}")
                    sentry_sdk.capture_message(f"Skipping port {port}: {e}",level='warning')
                    continue

        active_ports.sort(key=lambda x: x["port"],reverse=True)
        return active_ports[:20]

    except Exception as e:
        logger.error(f"Failed to fetch network ports: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return []


@router.get("hardware")
def get_hardware_info() -> Dict[str, Any]:
    """
    Get hardware specifications and health sensors (Temperature/Fans).

    Fetches real-time sensor data if available on the host OS.
    Note: Temperature and Fan sensors are OS-dependent. On Windows/WSL,
    these often return empty because the OS hides this data.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - temperatures (Dict): Sensor names and values (Celsius).
            - fans (Dict): Fan names and RPM.
            - cpu_info (Dict): Core counts and architecture.
            - memory_info (Dict): RAM usage in GB.
            - disk_info (Dict): Storage usage in GB.
    """
    try:
        temps: Dict[str, float] = {}
        if hasattr(psutil, "sensors_temperatures"):
            try:
                sensors = psutil.sensors_temperatures()
                for name, entries in sensors.items():
                    if entries and getattr(entries[0], 'current', None) is not None:
                        temps[name] = round(entries[0].current, 1)
            except Exception as e:
                logger.warning(f"Could not read temperatures: {e}")

        fans: Dict[str, int] = {}
        if hasattr(psutil, "sensors_fans"):
            try:
                fans_data = psutil.sensors_fans()
                for name, entries in fans_data.items():
                    if entries and getattr(entries[0], 'current', None) is not None:
                        fans[name] = entries[0].current
            except Exception as e:
                logger.warning(f"Could not read fan speeds: {e}")

        # 3. CPU Specs
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)

        return {
            "temperatures": temps,
            "fans": fans,
            "cpu_info": {
                "brand": platform.processor() or "Unknown CPU",
                "cores_logical": cpu_count_logical or 1,
                "cores_physical": cpu_count_physical or 1,
                "architecture": platform.machine()  # e.g., 'AMD64'
            },
            "memory_info": {
                # Convert Bytes -> GB
                "total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
                "available_gb": round(psutil.virtual_memory().available / (1024 ** 3),
                                      2)
            },
            "disk_info": {
                # Convert Bytes -> GB
                "total_gb": round(psutil.disk_usage('/').total / (1024 ** 3), 2),
                "free_gb": round(psutil.disk_usage('/').free / (1024 ** 3), 2)
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Hardware info failed: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return {
            "error": "Failed to retrieve hardware info",
            "temperatures": {},
            "fans": {},
            "cpu_info": {"brand": "Unknown", "cores": 0},
            "memory_info": {"total_gb": 0, "available_gb": 0},
            "disk_info": {"total_gb": 0, "free_gb": 0},
            "timestamp": datetime.now().isoformat()
        }


@router.get("network")
def get_network_info() -> Dict[str, Any]:
    """
    Retrieves real-time network interface statistics and throughput.

    Calculates upload/download speed based on the delta between the current
    request and the previous request, avoiding blocking 'sleep' calls.

    Returns:
        Dict[str, Any]: Network stats including:
            - download/upload: Current speed in bytes/sec.
            - total_download/total_upload: Total bytes since boot.
            - connections: Count of active socket connections.
            - interfaces: List of active network adapters and IPs.
    """
    global _last_net_stats

    try:
        net_io = psutil.net_io_counters()
        now = time.time()

        # 2. Calculate Speed (Delta / Time Elapsed)
        # If this is the first call, speed is 0
        time_diff = now - _last_net_stats["time"]

        if _last_net_stats["time"] > 0 and time_diff > 0:
            download_speed = (net_io.bytes_recv - _last_net_stats[
                "bytes_recv"]) / time_diff
            upload_speed = (net_io.bytes_sent - _last_net_stats[
                "bytes_sent"]) / time_diff
        else:
            download_speed = 0.0
            upload_speed = 0.0

        # 3. Update Global State for next time
        _last_net_stats["time"] = now
        _last_net_stats["bytes_recv"] = net_io.bytes_recv
        _last_net_stats["bytes_sent"] = net_io.bytes_sent

        # 4. Get Connections Count (Fast)
        connection_count = len(psutil.net_connections(kind='inet'))

        # 5. Get Interface Details
        interfaces: List[Dict[str, Any]] = []
        net_if_address = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()

        for name, address in net_if_address.items():
            if name.lower() == "lo" or name == "Loopback Pseudo-Interface 1":
                continue

            stats = net_if_stats.get(name)
            if stats and stats.isup:
                ipv4_address = [
                    addr.address for addr in address
                    if addr.family == socket.AF_INET
                ]

                if ipv4_address:
                    interfaces.append({
                        "name": name,
                        "is_up": stats.isup,
                        "speed_mbps": stats.speed,
                        "addresses": ipv4_address
                    })

        # 6. Determine Active Interface (Heuristic)
        # We assume the first UP interface with an IP is the active one
        active_if = interfaces[0]["name"] if interfaces else "Unknown"

        return {
            "download": round(download_speed, 1),
            "upload": round(upload_speed, 1),
            "connections": connection_count,
            "total_download": net_io.bytes_recv,
            "total_upload": net_io.bytes_sent,
            "interfaces": interfaces[:3],  # Top 3 only
            "active_interface": active_if,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to fetch network info: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)

        # Return safe fallback
        return {
            "download": 0, "upload": 0, "connections": 0,
            "total_download": 0, "total_upload": 0,
            "interfaces": [],
            "active_interface": "Unknown",
            "error": "Network data unavailable"
        }