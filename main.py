"""
Thrifted Shoes Assistant & Invoicing System - Main FastAPI Application.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.logging import get_logger, setup_logging
from app.connectors.google_sheets import get_sheets_sync
from app.api.orders import router as orders_router
from app.webhook.routes import router as webhook_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logging()
    logger.info("application_startup", env=settings.ENVIRONMENT, port=settings.PORT)
    
    # Init database
    try:
        init_db()
    except Exception as e:
        logger.error("database_init_error", error=str(e))
    
    # Ensure Google Sheets headers
    try:
        sheets = get_sheets_sync()
        sheets.ensure_headers()
    except Exception as e:
        logger.warning("google_sheets_init_warning", error=str(e))

    yield

    # Shutdown
    logger.info("application_shutdown")


app = FastAPI(
    title="ThriftPulse",
    description="Automated Sneaker Order Intake, Google Sheets Sync, Waybill Printing & WhatsApp AI Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files mount for uploaded shoe photos, invoices, and assets
static_path = Path(__file__).resolve().parent / "app" / "static"
try:
    static_path.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Include Routers
app.include_router(orders_router)
app.include_router(webhook_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.is_dev)
