# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Vision request stages — validation, dispatch, response shaping.

Split out of the router (2026-10-18) so ``vision()`` stays a short, low-branch
handler. The upstream callable is injected by the router, which keeps the
existing ``vision._call_vision_api`` patch target working unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from pry.api.routers.ai.vision_keys import read_image_file, resolve_models
from pry.core.deps import automator
from pry.core.errors import (
    ExternalServiceError,
    InvalidRequestError,
    ScrapeError,
)

logger = logging.getLogger(__name__)

VisionCall = Callable[[str, str, str, int], Awaitable[tuple[str | None, str | None, str | None]]]


def success_body(
    payload: Any, image_b64: str, text: str | None, used: str | None, attempts: list
) -> dict[str, Any]:
    """Build the unchanged success envelope for a completed vision call."""
    return {
        "success": True,
        "data": {
            "answer": text,
            "model_used": used,
            "question": payload.question,
            "image_size_bytes": len(image_b64) * 3 // 4,
            "attempts": attempts,
        },
    }


async def resolve_image(payload: Any) -> str:
    """Validation stage: turn url/file_path/image into base64, or raise."""
    if payload.url:
        result = await automator.run_steps(
            steps=[{"action": "navigate", "url": payload.url}, {"action": "screenshot"}],
            session_id=payload.session_id,
        )
        image_b64 = next(
            (
                s.get("screenshot")
                for s in result.get("steps", [])
                if s.get("action") == "screenshot"
            ),
            None,
        )
        if not image_b64:
            raise ScrapeError("screenshot returned empty")
        return image_b64
    if payload.file_path:
        return await asyncio.to_thread(read_image_file, payload.file_path)
    if payload.image:
        return (
            payload.image.split(",", 1)[1] if payload.image.startswith("data:") else payload.image
        )
    raise InvalidRequestError("must provide one of: image, url, file_path")


async def dispatch(payload: Any, image_b64: str, call: VisionCall) -> dict[str, Any]:
    """Dispatch stage: try each candidate model, collecting failure codes."""
    attempts: list[dict[str, str]] = []
    for model in resolve_models(payload.model, payload.no_fallback):
        try:
            text, used, err = await call(image_b64, payload.question, model, payload.max_tokens)
        except httpx.HTTPStatusError as e:
            logger.warning("vision_upstream_http", extra={"status": e.response.status_code})
            attempts.append({"model": model, "code": f"http_{e.response.status_code}"})
            continue
        except OSError:
            logger.warning("vision_upstream_transport", exc_info=True)
            attempts.append({"model": model, "code": "transport_error"})
            continue
        if err:
            attempts.append({"model": model, "code": err})
            continue
        return success_body(payload, image_b64, text, used, attempts)
    raise ExternalServiceError("vision_upstream_unavailable", details={"attempts": attempts})


__all__ = ["dispatch", "resolve_image", "success_body"]
