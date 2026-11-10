from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.exc import SQLAlchemyError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import logger, ALLOWED_ORIGINS
from app.database import init_db
from app.api.auth import router as auth_router
from app.api.dashboard_overview import router as overview_router
from app.api.google_services_calender import router as calendar_router
from app.dependencies import get_current_user
from app.owner_access import is_server_owner
from app.api.google_services_gmail import router as gmail_router
from app.api.google_services_drive import router as drive_router
from app.api.gemini import router as gemini_upload_router
from app.websockets.ai_stream import router as ai_stream_router
from app.websockets.system_stream import router as system_stream_router
from app.api.projects import router as projects_router
from app.api.commands import router as commands_router
from app.api.todoist import router as todoist_router
from app.api.dashboard_system_monitoring import router as sys_monitor_router
from app.api.dashboard_system_analytics import router as sys_analytics_router
from app.api.dashboard_system_ops import router as sys_ops_router


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        init_db()
        yield

    app = FastAPI(title="Nexus Personal Dashboard API", description="Backend API for personal productivity dashboard", version="2.0.0", docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)
    (app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                        allow_origin_regex=r"https://personal-dashboard-frontend-[a-z0-9-]+\.vercel\.app",allow_credentials=True, allow_methods=["*"], allow_headers=["*"]))
    for router in (auth_router, overview_router, calendar_router, gmail_router, drive_router, projects_router, commands_router, gemini_upload_router, ai_stream_router, system_stream_router, todoist_router, sys_monitor_router, sys_analytics_router, sys_ops_router):
        app.include_router(router)

    @app.get("/health", tags=["System"])
    async def health_check():
        return {"status": "active", "timestamp": datetime.now(timezone.utc).isoformat(), "version": "2.0.0"}

    @app.get("/dashboard/owner-access", tags=["System"])
    def get_owner_access(user: dict = Depends(get_current_user)):
        """Return whether the authenticated user is the configured dashboard owner."""
        return {"is_owner": is_server_owner(user)}

    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(request, exc):
        logger.error("Database operation failed", exc_info=True)
        return JSONResponse(status_code=503, content={"error": "Database is temporarily unavailable", "status_code": 503, "timestamp": datetime.now(timezone.utc).isoformat()})

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "status_code": exc.status_code, "timestamp": datetime.now(timezone.utc).isoformat()})

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Internal server error", "status_code": 500, "timestamp": datetime.now(timezone.utc).isoformat()})

    return app


app = create_app()
