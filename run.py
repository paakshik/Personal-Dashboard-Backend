"""
run.py - Development Server Launcher

This script provides a convenient way to start the Nexus Dashboard backend
with hot-reload, custom host/port, and environment-aware logging.

Usage (Windows PowerShell):
    python run.py                    # Default: localhost:8000
    python run.py --port 8001        # Custom port
    python run.py --host 0.0.0.0     # Listen on all interfaces (Docker, remote access)
    python run.py --no-reload        # Disable hot-reload (production-like)

Features:
    ✅ Hot-reload during development (auto-restart on file changes)
    ✅ Pretty console output with colors
    ✅ Auto-open browser to /docs (Swagger UI)
    ✅ Environment variable loading from .env
    ✅ Graceful shutdown handling
"""

import uvicorn
import argparse
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
else:
    print("⚠️  Warning: .env file not found. Using environment variables.")


def main():
    """
    Parse command-line arguments and start the Uvicorn server.

    This function:
    1. Parses CLI arguments (port, host, reload, etc.)
    2. Sets up environment-aware logging
    3. Starts the Uvicorn ASGI server
    4. Handles keyboard interrupts gracefully
    """

    # ======================================================================
    # ARGUMENT PARSER
    # ======================================================================

    parser = argparse.ArgumentParser(
        description="🚀 Nexus Dashboard Backend - Development Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                      # Start on localhost:8000
  python run.py --port 8001          # Custom port
  python run.py --host 0.0.0.0       # Listen on all interfaces
  python run.py --no-reload          # Disable hot-reload
  python run.py --log-level critical # Minimal logging

Environment Variables:
  BACKEND_HOST         Default host (default: 127.0.0.1)
  BACKEND_PORT         Default port (default: 8000)
  ENVIRONMENT          "development" or "production" (default: development)
        """
    )

    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("BACKEND_HOST", "127.0.0.1"),
        help="Host to bind the server to (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("BACKEND_PORT", 8000)),
        help="Port to bind the server to (default: 8000)"
    )

    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("ENVIRONMENT", "development") == "development",
        help="Enable hot-reload on file changes (default: True in development)"
    )

    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable hot-reload (production mode)"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1, set >1 for production)"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["critical", "error", "warning", "info", "debug"],
        help="Logging level (default: info)"
    )

    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open browser to /docs"
    )

    # ======================================================================
    # PARSE ARGUMENTS
    # ======================================================================

    args = parser.parse_args()

    # Handle --no-reload flag (overrides default)
    reload = not args.no_reload if args.no_reload else args.reload

    # ======================================================================
    # ENVIRONMENT VALIDATION
    # ======================================================================

    required_env_vars = [
        "SECRET_KEY",
        "ALGORITHM",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI"
    ]

    missing_vars = [var for var in required_env_vars if not os.getenv(var)]

    if missing_vars:
        print("⚠️  MISSING REQUIRED ENVIRONMENT VARIABLES:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n📝 Please create a .env file in the project root with these variables.")
        sys.exit(1)

    # ======================================================================
    # SERVER STARTUP
    # ======================================================================

    print("\n" + "=" * 70)
    print("🚀 NEXUS DASHBOARD API v2.0 - STARTING SERVER")
    print("=" * 70)
    print(f"📍 Host:          {args.host}")
    print(f"📍 Port:          {args.port}")
    print(f"🔄 Hot-reload:    {'✅ ENABLED' if reload else '❌ DISABLED'}")
    print(f"👷 Workers:       {args.workers}")
    print(f"📊 Log Level:     {args.log_level.upper()}")
    print("=" * 70)
    print(f"📚 API Docs:      http://{args.host}:{args.port}/docs")
    print(f"📚 ReDoc:         http://{args.host}:{args.port}/redoc")
    print(f"🏥 Health Check:  http://{args.host}:{args.port}/health")
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
            access_log=args.log_level != "critical",
            env_file=str(env_file) if env_file.exists() else None
        )

    except KeyboardInterrupt:
        print("\n\n⛔ Server shutting down...")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Server startup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()