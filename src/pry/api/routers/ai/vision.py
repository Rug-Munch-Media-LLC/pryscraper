"""Pry — Vision router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Body

from pry.api.client import get_client
from pry.api.routers.ai import vision_keys
from pry.core.deps import automator
from pry.core.errors import ExternalServiceError, InvalidRequestError, PryError, ScrapeError
from pry.engine.resilience import registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vision"])


@router.post("/v1/vision", tags=["Vision"], summary="Analyze an image with a free vision model")
async def vision(
    question: str = Body("Describe what is visible in this image.", embed=True),
    image: str | None = Body(None, embed=True),
    url: str | None = Body(None, embed=True),
    file_path: str | None = Body(None, embed=True),
    model: str | None = Body(None, embed=True),
    max_tokens: int = Body(800, embed=True),
    session_id: str | None = Body(None, embed=True),
    no_fallback: bool = Body(False, embed=True),
) -> dict[str, Any]:
    """Analyze an image with a free vision model.

    Provide ONE of: image (base64 or data URI), url (auto-screenshot),
    or file_path (local PNG/JPG).

    Auto-falls-back across 5 free OpenRouter vision models if the
    requested one is rate-limited.
    """
    try:
        # 1. Resolve the image bytes
        image_b64: str | None = None
        if url:
            # Auto-screenshot via playwright
            r = await automator.run_steps(
                steps=[{"action": "navigate", "url": url}, {"action": "screenshot"}],
                session_id=session_id,
            )
            for step in r.get("steps", []):
                if step.get("action") == "screenshot":
                    image_b64 = step.get("screenshot")
            if not image_b64:
                raise ScrapeError("screenshot returned empty")
        elif file_path:
            # Image files can be large; resolve path + read + base64 off the event loop.
            def _read_image_file(path: str) -> str:
                resolved = os.path.expanduser(path)
                if not os.path.isfile(resolved):
                    raise InvalidRequestError(f"file not found: {path}")
                with open(resolved, "rb") as f:
                    return base64.b64encode(f.read()).decode("ascii")

            image_b64 = await asyncio.to_thread(_read_image_file, file_path)
        elif image:
            # Strip data URI prefix if present
            image_b64 = image.split(",", 1)[1] if image.startswith("data:") else image
        else:
            raise InvalidRequestError("must provide one of: image, url, file_path")
        assert image_b64 is not None  # every non-raising branch above sets it

        # 2. Build the fallback chain
        if model:
            models_to_try = [model]
            if not no_fallback:
                models_to_try += [m for m in VISION_MODELS_FALLBACK if m != model]
        else:
            models_to_try = list(VISION_MODELS_FALLBACK)

        # 3. Try each model until one succeeds
        attempts = []
        for m in models_to_try:
            try:
                text, used, err = await _call_vision_api(image_b64, question, m, max_tokens)
                if err:
                    attempts.append({"model": m, "error": err})
                    continue
                return {
                    "success": True,
                    "data": {
                        "answer": text,
                        "model_used": used,
                        "question": question,
                        "image_size_bytes": len(image_b64) * 3 // 4,
                        "attempts": attempts,
                    },
                }
            except httpx.HTTPStatusError as e:
                logger.warning("vision_exception_handler", exc_info=True)
                attempts.append(
                    {
                        "model": m,
                        "error": f"http {e.response.status_code}",
                        "body": e.response.text[:200],
                    }
                )
            except OSError as e:
                logger.warning("vision_exception_handler", exc_info=True)
                attempts.append({"model": m, "error": str(e)})

        raise ExternalServiceError(
            "all vision models failed",
            details={"attempts": attempts},
        )
    except PryError:
        raise
    except OSError as e:
        raise ExternalServiceError(str(e)) from e


@router.get(
    "/v1/vision/models", tags=["Vision"], summary="List free vision-capable models on OpenRouter"
)
async def vision_models() -> dict[str, Any]:
    """List free vision-capable models on OpenRouter."""
    try:
        client = await get_client()
        resp = await client.get(
            "https://openrouter.ai/api/v1/models", headers={"User-Agent": "pry/3.0"}, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise ExternalServiceError(str(e)) from e

    free = []
    for m in data.get("data", []):
        arch = m.get("architecture", {})
        if "image" not in arch.get("input_modalities", []):
            continue
        pricing = m.get("pricing", {})
        try:
            pp = float(pricing.get("prompt", "1") or 1)
            cp = float(pricing.get("completion", "1") or 1)
        except (TypeError, ValueError) as e:
            logger.warning(
                "model_pricing_unparseable", extra={"model_id": m.get("id"), "error": str(e)}
            )
            continue
        if pp == 0 and cp == 0:
            free.append(
                {
                    "id": m["id"],
                    "name": m.get("name", ""),
                    "context": arch.get("context_length"),
                    "description": (m.get("description") or "")[:120],
                }
            )
    return {"success": True, "data": {"free_models": free, "count": len(free)}}


VISION_MODELS_FALLBACK = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openrouter/free",
]


async def _call_vision_api(
    image_b64: str, question: str, model: str, max_tokens: int = 800
) -> tuple[str | None, str | None, str | None]:
    """Single async vision call. Returns (text, model_used) or raises."""
    # Call-time read through the module (never a bound import) so a patch on
    # either module is honoured.
    key = vision_keys._get_or_key()
    if not key:
        return None, None, "OPENROUTER_API_KEY not set"
    if not registry.is_service_allowed("openrouter"):
        return None, None, "OpenRouter circuit breaker open"

    # Accept either data URI or raw base64
    data_uri = image_b64 if image_b64.startswith("data:") else f"data:image/png;base64,{image_b64}"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "max_tokens": max_tokens,
    }

    client = await get_client()
    resp = await client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://pry.local",
            "X-Title": "pry-vision",
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    registry.record_service_result("openrouter", True)
    return body["choices"][0]["message"]["content"], model, None


# Re-exported so `from pry.api.routers.ai.vision import _get_or_key` keeps working.
# NOT a bound local: it is the same object, and internal callers above go through
# the `vision_keys` module attribute so monkeypatching stays visible.
from pry.api.routers.ai.vision_keys import _get_or_key  # noqa: E402,F401
