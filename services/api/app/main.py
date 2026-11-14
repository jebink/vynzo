"""VYNZO API entrypoint: `uvicorn app.main:app` from services/api."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.integrations.postgres import create_pool
from app.middleware.error_handler import register_error_handlers
from app.middleware.request_id import RequestIdMiddleware
from app.modules.companies.router import router as companies_router
from app.modules.focus.router import router as focus_router
from app.modules.fundamentals.router import router as fundamentals_router
from app.modules.instruments.router import router as instruments_router
from app.modules.market_data.router import router as market_data_router
from app.modules.opportunities.router import router as opportunities_router
from app.modules.signals.router import router as signals_router
from app.modules.stock_grading.router import router as stock_grading_router

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = create_pool(settings.database_url)
    pool.open(wait=False)
    app.state.db_pool = pool
    yield
    pool.close()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)

for router in (
    instruments_router,
    companies_router,
    market_data_router,
    opportunities_router,
    fundamentals_router,
    signals_router,
    stock_grading_router,
    focus_router,
):
    app.include_router(router, prefix="/v1")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness: the process is up. Does not touch the database."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready(request: Request) -> JSONResponse:
    """Readiness: the database answers."""
    try:
        with request.app.state.db_pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - report any DB failure as not ready
        return JSONResponse(status_code=503, content={"status": "unavailable", "db": str(exc)})
    return JSONResponse(content={"status": "ok", "db": "ok"})
