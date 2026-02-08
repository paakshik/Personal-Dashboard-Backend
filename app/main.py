"""
app/main.py - FastAPI Application Factory

This module serves as the single entry point for the Nexus Dashboard backend.

Responsibilities:
1. Initialize FastAPI app with metadata
2. Configure middleware (CORS, security, error handling)
3. Mount all API routers (auth, projects, commands, etc.)
4. Register WebSocket handlers
5. Provide health check endpoints
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timezone

# Import configuration
from app.config import logger

# ============================================================================
# IMPORT ALL ROUTERS (API Endpoints)
# ============================================================================

# Authentication & User Management
from app.api.auth import router as auth_router

# Google Integrations
from app.api.google_services_calender import router as calendar_router
from app.api.google_services_gmail import router as gmail_router
from app.api.google_services_drive import router as drive_router

# AI & Gemini
from app.api.gemini import router as gemini_upload_router
from app.websockets.ai_stream import router as ai_stream_router
from app.api.projects import router as projects_router
from app.api.commands import router as commands_router
from app.api.todoist import router as todoist_router
from app.api.dashboard_system_monitoring import router as sys_monitor_router
from app.api.dashboard_system_analytics import router as sys_analytics_router
from app.api.dashboard_system_ops import router as sys_ops_router

def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI application.
    """
    main_app = FastAPI(
        title="Nexus Personal Dashboard API",
        description="Backend API for personal productivity dashboard",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # ========================================================================
    # MIDDLEWARE CONFIGURATION
    # ========================================================================

    # CORS (Cross-Origin Resource Sharing)
    main_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ========================================================================
    # ROUTER REGISTRATION
    # ========================================================================

    # Core Identity
    main_app.include_router(auth_router)
    logger.info("Registered: Authentication Routes")

    # Productivity Services
    main_app.include_router(calendar_router)
    main_app.include_router(gmail_router)
    main_app.include_router(drive_router)
    logger.info("Registered: Google Service Routes")

    main_app.include_router(projects_router)
    main_app.include_router(commands_router)
    logger.info("Registered: Project & Command Routes")

    # AI Services
    main_app.include_router(gemini_upload_router)
    main_app.include_router(ai_stream_router)
    logger.info("Registered: Gemini AI Routes")

    main_app.include_router(todoist_router)
    logger.info("Registered: Todoist Routes")

    # System Monitoring
    main_app.include_router(sys_monitor_router)
    main_app.include_router(sys_analytics_router)
    main_app.include_router(sys_ops_router)
    logger.info("Registered: System Monitoring Routes")

    # ========================================================================
    # HEALTH CHECKS (Startup Event Removed)
    # ========================================================================

    @main_app.get("/health", tags=["System"])
    async def health_check():
        """Simple heartbeat endpoint for uptime monitoring."""
        return {
            "status": "active",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0"
        }

    # ========================================================================
    # EXCEPTION HANDLERS
    # ========================================================================

    @main_app.exception_handler(HTTPException)
    async def http_exception_handler(request,exc):
        """Standardizes HTTP error responses."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "status_code": exc.status_code,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    @main_app.exception_handler(Exception)
    async def global_exception_handler(request,exc):
        """Catch-all for unexpected server errors."""
        logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "status_code": 500,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    logger.info("=" * 70)
    logger.info("Nexus Dashboard API v2.0 initialized successfully!")
    logger.info("=" * 70)
    return main_app


# ============================================================================
# CREATE APP INSTANCE
# ============================================================================
app = create_app()