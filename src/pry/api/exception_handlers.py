"""Exception handlers — RFC 7807 Problem Details responses.

Split out of api.py (god-file split, 2026-09).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pry.core.errors import PryError
from pry.core.logging_config import get_logger

logger = get_logger(__name__)


def add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(
                request_id=req_id,
                instance=str(request.url),
            ),
        )

    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """RFC 7807 Problem Details for HTTP errors (404, 401, 403, etc)."""
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        status = exc.status_code
        titles = {
            "Bad Request": 400,
            "Unauthorized": 401,
            "Forbidden": 403,
            "Not Found": 404,
            "Conflict": 409,
            "Too Many Requests": 429,
            "Internal Server Error": 500,
            "Bad Gateway": 502,
            "Service Unavailable": 503,
        }
        title = {v: k for k, v in titles.items()}.get(status, "Error")
        detail = exc.detail if isinstance(exc.detail, str) else "Bad Request"
        return JSONResponse(
            status_code=status,
            media_type="application/problem+json",
            content={
                "type": "/errors/" + title.lower().replace(" ", "-")
                if status != 500
                else "about:blank",
                "title": title,
                "status": status,
                "detail": detail,
                "request_id": req_id,
                "instance": str(request.url),
                "timestamp": datetime.now(UTC).isoformat(),
                "code": title.lower().replace(" ", "_"),
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        logger.exception("unhandled_exception", extra={"request_id": req_id})

        return JSONResponse(
            status_code=500,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred",
                "request_id": req_id,
                "instance": str(request.url),
                "timestamp": datetime.now(UTC).isoformat(),
                "code": "internal_error",
            },
        )
