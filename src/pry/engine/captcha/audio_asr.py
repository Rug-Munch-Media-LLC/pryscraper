"""Pry — T2: audio-challenge ASR, fully offline.

reCAPTCHA and hCaptcha both expose an audio variant of the challenge. The clip
is transcribed locally with faster-whisper (CPU, int8) — no audio leaves the
box and no key is involved. The model directory is configurable via
``PRY_CAPTCHA_ASR_MODEL``; absent model or absent faster-whisper is reported as
``unavailable.model`` instead of a slow failure.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

MODEL_ENV = "PRY_CAPTCHA_ASR_MODEL"
DEFAULT_MODEL = Path.home() / ".cache" / "pry" / "models" / "faster-whisper-base"
_NOISE = re.compile(r"[^a-z0-9]+")


def model_path() -> Path:
    """Model directory: env override first, then the per-user cache."""
    return Path(os.environ.get(MODEL_ENV, str(DEFAULT_MODEL)))


def capability() -> bool:
    """True when both faster-whisper and the model files are present."""
    if not model_path().is_dir():
        return False
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def normalize(text: str) -> str:
    """Reduce a transcript to the alphanumeric answer captchas accept."""
    return _NOISE.sub("", (text or "").lower())


def _transcribe(audio: bytes, model_dir: Path) -> str:
    """Blocking transcription; runs off the event loop."""
    from faster_whisper import WhisperModel

    model = WhisperModel(str(model_dir), device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=".mp3") as handle:
        handle.write(audio)
        handle.flush()
        segments, _info = model.transcribe(handle.name, language="en", beam_size=1)
        return " ".join(segment.text for segment in segments)


async def solve_audio(audio: bytes | None, timeout_s: float = 30.0) -> tuple[str | None, str]:
    """Transcribe an audio challenge -> (answer, reason)."""
    if not audio:
        return None, "not_applicable"
    if not capability():
        return None, f"unavailable.model:{model_path()}"
    try:
        async with asyncio.timeout(timeout_s):
            text = await asyncio.to_thread(_transcribe, audio, model_path())
    except TimeoutError:
        return None, "timeout"
    except (OSError, RuntimeError, ValueError):
        return None, "failed"
    answer = normalize(text)
    return (answer, "solved") if answer else (None, "unsolved")
