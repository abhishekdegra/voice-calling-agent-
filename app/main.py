"""FastAPI application entry point for Welfog Voice Agent."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes.health import router as health_router
from app.routes.calls import router as calls_router
from app.routes.webhooks import router as webhooks_router
from app.routes.websocket import router as websocket_router
from app.utils.logging import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and graceful shutdown."""
    settings = get_settings()
    logger.info(
        "welfog_voice_server_starting",
        extra={
            "environment": settings.environment,
            "port": settings.port,
            "host": settings.host,
            "telecmi_app_id": settings.telecmi_app_id
        }
    )
    try:
        from app.services.db_service import get_db_service
        db = get_db_service()
        db._ensure_database_and_tables()
    except Exception as e:
        logger.error("db_startup_init_failed", error=str(e))
    yield
    logger.info("welfog_voice_server_stopped")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="Welfog Custom AI Voice Calling Agent",
        description="Real-time AI voice calling server integrating TeleCMI, Gemini Multimodal Live API, Welfog Order APIs, and Qdrant RAG.",
        version="1.0.0",
        lifespan=lifespan
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.routes.admin import router as admin_router
    from app.services.auth_service import verify_session_token, SESSION_COOKIE_NAME

    # Register Routers
    app.include_router(health_router)
    app.include_router(calls_router)
    app.include_router(webhooks_router)
    app.include_router(websocket_router)
    app.include_router(admin_router)

    # Static files and Web views
    import os
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi import Request

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def root_redirect(request: Request):
            token = request.cookies.get(SESSION_COOKIE_NAME)
            if token and verify_session_token(token):
                return RedirectResponse(url="/dashboard", status_code=303)
            return RedirectResponse(url="/login", status_code=303)

        @app.get("/login", include_in_schema=False)
        async def serve_login(request: Request):
            token = request.cookies.get(SESSION_COOKIE_NAME)
            if token and verify_session_token(token):
                return RedirectResponse(url="/dashboard", status_code=303)
            return FileResponse(os.path.join(static_dir, "login.html"))

        @app.get("/dashboard", include_in_schema=False)
        async def serve_dashboard(request: Request):
            token = request.cookies.get(SESSION_COOKIE_NAME)
            if not token or not verify_session_token(token):
                return RedirectResponse(url="/login", status_code=303)
            return FileResponse(os.path.join(static_dir, "dashboard.html"))

        @app.get("/dialer", include_in_schema=False)
        async def serve_dialer(request: Request):
            token = request.cookies.get(SESSION_COOKIE_NAME)
            if not token or not verify_session_token(token):
                return RedirectResponse(url="/login", status_code=303)
            return FileResponse(os.path.join(static_dir, "index.html"))

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=(settings.environment == "development")
    )
