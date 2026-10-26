"""T2/T3 model-path contract: the refusal must name the path that was tried."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import sys
import types

import pytest

from pry.engine.captcha import audio_asr, image_ocr


def _stub(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    module = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.asyncio
async def test_asr_refusal_names_missing_model_path(monkeypatch, tmp_path):
    bogus = tmp_path / "absent-whisper"
    monkeypatch.setenv(audio_asr.MODEL_ENV, str(bogus))
    assert audio_asr.capability() is False
    assert await audio_asr.solve_audio(b"clip") == (None, f"unavailable.model:{bogus}")


@pytest.mark.asyncio
async def test_ocr_refusal_names_missing_model_path(monkeypatch, tmp_path):
    bogus = tmp_path / "absent-common.onnx"
    monkeypatch.setenv(image_ocr.MODEL_ENV, str(bogus))
    assert image_ocr.capability() is False
    assert await image_ocr.solve_image(b"img") == (None, f"unavailable.model:{bogus}")


def test_asr_capability_true_with_model_dir_stub(monkeypatch, tmp_path):
    model_dir = tmp_path / "tiny.en"
    model_dir.mkdir()
    monkeypatch.setenv(audio_asr.MODEL_ENV, str(model_dir))
    _stub(monkeypatch, "faster_whisper")
    assert audio_asr.capability() is True


def test_ocr_capability_true_with_model_file_stub(monkeypatch, tmp_path):
    model_file = tmp_path / "common.onnx"
    model_file.write_bytes(b"stub")
    monkeypatch.setenv(image_ocr.MODEL_ENV, str(model_file))
    _stub(monkeypatch, "onnxruntime")
    assert image_ocr.capability() is True
