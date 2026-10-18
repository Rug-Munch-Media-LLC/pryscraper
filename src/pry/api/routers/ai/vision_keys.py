"""Vision policy: OpenRouter key resolution, free-model allowlist, upload confinement.

Split out of ``vision.py`` so credential lookup and the request-side safety
policy have one owner. The route module imports this and calls through module
attributes at call time, so patching either module is visible to the other.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import time
from typing import TYPE_CHECKING

from pry.core.errors import InvalidRequestError, RateLimitError
from pry.core.settings import settings

if TYPE_CHECKING:
    from fastapi import Request

VISION_MODELS_FALLBACK = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openrouter/free",
]
VISION_MODELS_ALLOWED = frozenset(VISION_MODELS_FALLBACK)
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
MAX_IMAGE_BYTES = 8 * 1024 * 1024
VISION_TOKEN_BUDGET = int(os.getenv("PRY_VISION_TOKEN_BUDGET", "100000"))
_budget: dict[str, tuple[float, int]] = {}


def _get_or_key() -> str | None:
    """Pull OPENROUTER_API_KEY from ~/.hermes/.env or env."""
    key = settings.openrouter_api_key
    if key:
        return key
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.isfile(env_path):
        return None
    with open(env_path) as f:
        for line in f:
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def resolve_models(requested: str | None, no_fallback: bool) -> list[str]:
    """Return an ordered list of FREE models; reject anything else."""
    if not requested:
        return list(VISION_MODELS_FALLBACK)
    if requested not in VISION_MODELS_ALLOWED:
        raise InvalidRequestError("model is not in the free vision allowlist")
    if no_fallback:
        return [requested]
    return [requested] + [m for m in VISION_MODELS_FALLBACK if m != requested]


def read_image_file(path: str) -> str:
    """Read a server-side upload with realpath containment and a size cap."""
    root = os.path.realpath(os.getenv("PRY_VISION_UPLOAD_DIR", tempfile.gettempdir()))
    expanded = os.path.expanduser(path)
    if os.path.islink(expanded):
        raise InvalidRequestError("file_path must not be a symlink")
    resolved = os.path.realpath(expanded)
    if os.path.commonpath([resolved, root]) != root:
        raise InvalidRequestError("file_path is outside the vision upload directory")
    if os.path.splitext(resolved)[1].lower() not in IMAGE_EXTENSIONS:
        raise InvalidRequestError("file_path must be a PNG/JPG/WEBP/GIF/BMP image")
    if not os.path.isfile(resolved):
        raise InvalidRequestError("file not found")
    with open(resolved, "rb") as handle:
        raw = handle.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise InvalidRequestError("image is empty or exceeds the 8 MiB limit")
    return base64.b64encode(raw).decode("ascii")


def charge_budget(request: Request, tokens: int) -> None:
    """Charge the caller's hourly token budget (bearer key, else peer IP)."""
    auth = request.headers.get("authorization", "")
    token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    if token:
        key = "key:" + hashlib.sha256(token.encode()).hexdigest()[:16]
    else:
        key = f"ip:{request.client.host if request.client else 'unknown'}"
    now = time.monotonic()
    started, used = _budget.get(key, (now, 0))
    if now - started >= 3600:
        started, used = now, 0
    if used + tokens > VISION_TOKEN_BUDGET:
        raise RateLimitError("vision token budget exceeded; retry later")
    _budget[key] = (started, used + tokens)
