"""
run.py - Development Server Launcher

This script provides a convenient way to start the Nexus Dashboard backend
with hot-reload, custom host/port, and environment-aware logging.

Usage (Windows PowerShell):
    python run.py                    # Default: localhost:8000
    python run.py --port 8001        # Custom port
    python run.py --host 0.0.0.0     # Listen on all interfaces
    python run.py --no-reload        # Disable hot-reload
"""

import uvicorn
import argparse
import sys
from  app.config import sentry_sdk,logger


def main() -> None:
    """
    Parse command-line arguments and start the Uvicorn server.

    This function serves as the entry point for the backend application.
    It configures the server host, port, reload behavior, and logging level
    via command-line arguments, then delegates execution to Uvicorn.

    Command Line Arguments:
        --host (str): Network interface to bind (default: 127.0.0.1)
        --port (int): Port number to listen on (default: 8000)
        --no-reload (bool): Disable auto-reload (useful for production)
        --workers (int): Number of worker processes (default: 1)
        --log-level (str): Uvicorn logging verbosity (default: info)

    Returns:
        None: This function runs indefinitely until interrupted.

    Raises:
        SystemExit: Exits with code 0 on user interrupt (CTRL+C) or code 1
                    on fatal server initialization errors.
    """
    parser = argparse.ArgumentParser(description="Personal Dashboard API Server "
                                                 "Launcher")

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind to (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)"
    )

    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable hot-reload (recommended for production)"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1)"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Logging verbosity level"
    )

    args = parser.parse_args()

    # Invert the flag so default is reload=True (easier for dev)
    reload = not args.no_reload

    # ======================================================================
    # SERVER STARTUP
    # ======================================================================

    # Use the configured logger instead of print for consistency
    logger.info("=" * 70)
    logger.info("NEXUS DASHBOARD API v2.0 - STARTING SERVER")
    logger.info("=" * 70)
    logger.info(f"Host:          {args.host}")
    logger.info(f"Port:          {args.port}")
    logger.info(f"Hot-reload:    {'ENABLED' if reload else 'DISABLED'}")
    logger.info(f"Workers:       {args.workers}")
    logger.info(f"Log Level:     {args.log_level.upper()}")
    logger.info("=" * 70)

    # Keep standard print for clickable links in terminal (Loggers sometimes strip formatting)
    print(f"API Docs:      http://{args.host}:{args.port}/docs")
    print(f"ReDoc:         http://{args.host}:{args.port}/redoc")
    print(f"Health Check:  http://{args.host}:{args.port}/health")
    print("=" * 70)
    print("Press CTRL+C to shutdown the server\n")

    try:
        # Start Uvicorn server
        uvicorn.run(
            "app.main:app",  # Module:app reference
            host=args.host,
            port=args.port,
            reload=reload,  # Hot-reload on file changes
            log_level=args.log_level,
            workers=args.workers,
        )
    except KeyboardInterrupt:
        logger.info("Server shutdown requested by user.")
        sys.exit(0)
    except Exception as e:
        # Capture fatal startup errors in Sentry
        sentry_sdk.capture_exception(e)
        logger.critical(f"Fatal Server Error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()