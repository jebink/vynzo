import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.exception("unhandled error (request_id=%s)", request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "request_id": request_id},
        )
