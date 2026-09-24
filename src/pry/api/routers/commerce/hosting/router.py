"""Shared router object for the hosted-Pry HTTP surface."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from fastapi import APIRouter

router = APIRouter(tags=["hosting"])
