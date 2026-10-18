"""Pry — Vision router (remaining api.py routes).

Hardened 2026-10-18: file_path is confined to a realpath-checked upload root
(extension allowlist, symlink rejection, 8 MiB cap); only free models are
accepted; max_tokens is clamped; unknown fields are rejected; a per-caller
token budget is charged before dispatch; the breaker records failures and
failures return codes, never upstream bodies.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator

from pry.api.client import get_client
from pry.api.routers.ai import vision_keys
from pry.api.routers.ai.vision_keys import (
    VISION_MODELS_FALLBACK,  # noqa: F401 - re-exported for tests/callers
    charge_budget,
    read_image_file,
    resolve_models,
)
from pry.core.deps import automator
from pry.core.errors import (
    ExternalServiceError,
    InvalidRequestError,
    PryError,
    ScrapeError,
)
from pry.engine.resilience import registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Vision"])
MAX_VISION_TOKENS = 1024


class VisionRequest(BaseModel):
    """Strict body — unknown fields are rejected, max_tokens is clamped."""

    model_config = ConfigDict(extra="forbid")
    question: str = "Describe what is visible in this image."
    image: str | None = None
    url: str | None = None
    file_path: str | None = None
    model: str | None = None
    max_tokens: int = 800
    session_id: str | None = None
    no_fallback: bool = False

    @field_validator("max_tokens")
    @classmethod
    def _clamp_max_tokens(cls, value: int) -> int:
        return max(1, min(int(value), MAX_VISION_TOKENS))


@router.post("/v1/vision", tags=["Vision"], summary="Analyze an image with a free vision model")
async def vision(payload: VisionRequest, request: Request) -> dict[str, Any]:
    """Analyze an image with a free vision model.

    Provide ONE of: image (base64 or data URI), url (auto-screenshot), or
    file_path (inside ``PRY_VISION_UPLOAD_DIR``).
    """
    models_to_try = resolve_models(payload.model, payload.no_fallback)
    if not registry.is_service_allowed("openrouter"):
        raise HTTPException(status_code=503, detail="vision_upstream_unavailable")
    try:
        image_b64: str | None = None
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
        elif payload.file_path:
            image_b64 = await asyncio.to_thread(read_image_file, payload.file_path)
        elif payload.image:
            image_b64 = (
                payload.image.split(",", 1)[1]
                if payload.image.startswith("data:")
                else payload.image
            )
        else:
            raise InvalidRequestError("must provide one of: image, url, file_path")
        assert image_b64 is not None
        charge_budget(
            request, len(image_b64) // 4 + len(payload.question) // 4 + payload.max_tokens
        )
        attempts: list[dict[str, str]] = []
        for model in models_to_try:
            try:
                text, used, err = await _call_vision_api(
                    image_b64, payload.question, model, payload.max_tokens
                )
                if err:
                    attempts.append({"model": model, "code": err})
                    continue
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
            except httpx.HTTPStatusError as e:
                logger.warning("vision_upstream_http", extra={"status": e.response.status_code})
                attempts.append({"model": model, "code": f"http_{e.response.status_code}"})
            except OSError:
                logger.warning("vision_upstream_transport", exc_info=True)
                attempts.append({"model": model, "code": "transport_error"})
        raise ExternalServiceError("vision_upstream_unavailable", details={"attempts": attempts})
    except PryError:
        raise
    except OSError as e:
        raise ExternalServiceError("vision_input_unavailable") from e


@router.get("/v1/vision/models", tags=["Vision"], summary="List free vision models")
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
        raise ExternalServiceError("vision_models_unavailable") from e
    free = []
    for m in data.get("data", []):
        arch = m.get("architecture", {})
        if "image" not in arch.get("input_modalities", []):
            continue
        try:
            pricing = m.get("pricing", {})
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


async def _call_vision_api(
    image_b64: str, question: str, model: str, max_tokens: int = 800
) -> tuple[str | None, str | None, str | None]:
    """Single async vision call. Returns (text, model_used, code) or raises."""
    max_tokens = max(1, min(int(max_tokens), MAX_VISION_TOKENS))
    key = vision_keys._get_or_key()
    if not key:
        registry.record_service_result("openrouter", False)
        return None, None, "vision_key_missing"
    if not registry.is_service_allowed("openrouter"):
        return None, None, "vision_breaker_open"
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
    try:
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
        text = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        registry.record_service_result("openrouter", False)
        raise
    registry.record_service_result("openrouter", True)
    return text, model, None


# Re-exported so `from pry.api.routers.ai.vision import _get_or_key` keeps working.
from pry.api.routers.ai.vision_keys import _get_or_key  # noqa: E402,F401
