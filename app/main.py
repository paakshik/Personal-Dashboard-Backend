"""
app/main.py - FastAPI Application Factory

This module serves as the single entry point for the Nexus Dashboard backend.

Responsibilities:
1. Initialize FastAPI app with metadata
2. Configure middleware (CORS, security, error handling)
3. Mount all API routers (auth, projects, commands, etc.)
4. Register WebSocket handlers
5. Initialize data files and sample data
6. Provide health check endpoints

IMPORTANT: No business logic here—only app assembly.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timezone

# Import configuration and initialization utilities
from app.config import logger
from app.utils.file_ops import init_data_files
from app.utils.initializers import init_sample_projects, init_sample_commands

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
from app.api.gemini import router as gemini_router

# Project & Command Management
from app.api.projects import router as projects_router
from app.api.commands import router as commands_router

# Todoist Integration
from app.api.todoist import router as todoist_router

# System Monitoring & Analytics
from app.api.dashboard_system_analytics import router as analytics_router
from app.api.dashboard_system_monitoring import router as monitoring_router
from app.api.dashboard_system_ops import router as system_ops_router

# ============================================================================
# IMPORT WEBSOCKET HANDLERS
# ============================================================================


from app.websockets.ai_stream import router as ai_stream_ws_router


# ============================================================================
# APPLICATION FACTORY
# ============================================================================

def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI application.

    This pattern allows:
    - Easy testing (create separate app instances per test)
    - Multiple app instances with different configs
    - Clean separation of concerns

    Returns:
        FastAPI: Fully configured application instance

    Raises:
        RuntimeError: If initialization fails (data files, sample data)
    """

    # 1. Initialize FastAPI app with metadata
    app = FastAPI(
        title="Nexus Dashboard API",
        description="A powerful personal dashboard integrating Google Services, Todoist, and Gemini AI",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json"
    )

    # 2. Initialize data files and sample data (one-time setup)
    try:
        init_data_files()
        init_sample_projects()
        init_sample_commands()
        logger.info("✅ Data files and sample data initialized successfully")
    except Exception as e:
        logger.critical(f"❌ Failed to initialize data files: {e}")
        raise RuntimeError(f"Application startup failed: {e}")

    # ========================================================================
    # MIDDLEWARE CONFIGURATION
    # ========================================================================

    # CORS Middleware (Cross-Origin Resource Sharing)
    # Allows frontend (React) running on different port to access backend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite dev server (React)
            "http://localhost:3000",  # Next.js dev server (alternative)
            "http://localhost:8080",  # Vue dev server (alternative)
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8080",
        ],
        allow_credentials=True,  # Allow cookies/auth headers
        allow_methods=["*"],  # Allow all HTTP methods
        allow_headers=[
            "Authorization",  # JWT tokens
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
        ],
    )

    # ========================================================================
    # REGISTER API ROUTERS
    # ========================================================================

    # Health check (must come first for fast response)
    @app.get("/health")
    async def health_check():
        """Quick health check endpoint for monitoring."""
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0"
        }

    @app.get("/")
    async def root():
        """Root endpoint - API documentation."""
        return {
            "status": "running",
            "message": "Nexus Dashboard API v2.0",
            "docs": "/docs",
            "version": "2.0.0"
        }

    # Authentication (MUST be registered before protected routes)
    app.include_router(auth_router)
    logger.info("✅ Registered: Authentication Routes")

    # Google Integrations
    app.include_router(calendar_router)
    app.include_router(gmail_router)
    app.include_router(drive_router)
    logger.info("✅ Registered: Google Service Routes")

    # Project & Command Management
    app.include_router(projects_router)
    app.include_router(commands_router)
    logger.info("✅ Registered: Project & Command Routes")

    # Gemini AI
    app.include_router(gemini_router)
    logger.info("✅ Registered: Gemini AI Routes")

    # Todoist Integration
    app.include_router(todoist_router)
    logger.info("✅ Registered: Todoist Routes")

    # System Monitoring & Analytics
    app.include_router(analytics_router)
    app.include_router(monitoring_router)
    app.include_router(system_ops_router)
    logger.info("✅ Registered: System Monitoring Routes")

    # ========================================================================
    # REGISTER WEBSOCKET HANDLERS
    # ========================================================================


    app.include_router(ai_stream_ws_router)
    logger.info("✅ Registered: WebSocket Handlers")

    # ========================================================================
    # GLOBAL EXCEPTION HANDLERS
    # ========================================================================

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        """
        Custom HTTP exception handler for consistent error responses.

        Maps all HTTPExceptions to a standard JSON format that the frontend
        can reliably parse.
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "status_code": exc.status_code,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        """
        Catch-all exception handler for unexpected errors.

        Logs the full stack trace and returns a safe error message
        without leaking internals to the client.
        """
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
    logger.info("🚀 Nexus Dashboard API v2.0 initialized successfully!")
    logger.info("=" * 70)

    return app


# ============================================================================
# CREATE APP INSTANCE (Used by Uvicorn)
# ============================================================================

# This is what Uvicorn looks for when you run: uvicorn app.main:app
app = create_app()