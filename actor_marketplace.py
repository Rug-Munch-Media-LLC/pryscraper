"""Pry — Actor Marketplace (Apify-style).
Pre-built scrapers that can be subscribed to and run on schedule.
Users can publish their own actors. We earn from usage."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import json
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

ACTOR_DIR = PRY_DATA_DIR / "actors"
ACTOR_DIR.mkdir(parents=True, exist_ok=True)


class ActorVisibility(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    UNLISTED = "unlist"


class Actor:
    """A reusable scraper actor that can be run on demand or schedule."""

    def __init__(
        self,
        actor_id: str,
        name: str,
        description: str,
        template_id: str = "",
        code: str = "",
        price_per_run: float = 0.0,
        visibility: ActorVisibility = ActorVisibility.PRIVATE,
        schedule_cron: str = "",
        tags: list[str] | None = None,
    ):
        self.actor_id = actor_id
        self.name = name
        self.description = description
        self.template_id = template_id
        self.code = code
        self.price_per_run = price_per_run
        self.visibility = visibility
        self.schedule_cron = schedule_cron
        self.tags = tags or []
        self.created_at = datetime.now(UTC).isoformat()
        self.run_count = 0
        self.revenue_usd = 0.0
        self.author = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "name": self.name,
            "description": self.description,
            "template_id": self.template_id,
            "code": self.code,
            "price_per_run": self.price_per_run,
            "visibility": self.visibility.value,
            "schedule_cron": self.schedule_cron,
            "tags": self.tags,
            "created_at": self.created_at,
            "run_count": self.run_count,
            "revenue_usd": round(self.revenue_usd, 4),
            "author": self.author,
        }


class ActorMarketplace:
    """Manage and discover actors."""

    def __init__(self):
        self.actors: dict[str, Actor] = {}
        self._load()

    def _load(self) -> None:
        for f in ACTOR_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                actor = Actor.__new__(Actor)
                actor.__dict__.update(data)
                actor.visibility = ActorVisibility(data.get("visibility", "private"))
                self.actors[actor.actor_id] = actor
            except (json.JSONDecodeError, OSError, ValueError):
                continue

    def _save(self, actor: Actor) -> None:
        try:
            (ACTOR_DIR / f"{actor.actor_id}.json").write_text(json.dumps(actor.to_dict(), indent=2))
        except OSError as e:
            logger.warning("actor_save_failed", extra={"actor_id": actor.actor_id, "error": str(e)})

    def create(
        self,
        name: str,
        description: str,
        template_id: str = "",
        code: str = "",
        price_per_run: float = 0.0,
        visibility: ActorVisibility = ActorVisibility.PRIVATE,
        schedule_cron: str = "",
        tags: list[str] | None = None,
        author: str = "",
    ) -> Actor:
        actor = Actor(
            uuid.uuid4().hex[:12],
            name,
            description,
            template_id,
            code,
            price_per_run,
            visibility,
            schedule_cron,
            tags,
        )
        actor.author = author
        self.actors[actor.actor_id] = actor
        self._save(actor)
        return actor

    def list(self, visibility: str = "", tag: str = "") -> list[dict[str, Any]]:
        results = []
        for actor in self.actors.values():
            if visibility and actor.visibility.value != visibility:
                continue
            if tag and tag not in actor.tags:
                continue
            results.append(actor.to_dict())
        return sorted(results, key=lambda x: -x.get("run_count", 0))

    async def run(self, actor_id: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        actor = self.actors.get(actor_id)
        if not actor:
            return {"success": False, "error": f"Actor not found: {actor_id}"}
        actor.run_count += 1
        if actor.price_per_run > 0:
            actor.revenue_usd += actor.price_per_run
        self._save(actor)
        if actor.template_id:
            from template_engine import execute_template

            url = (inputs or {}).get("url", "")
            if not url:
                return {"success": False, "error": "Missing 'url' input"}
            result = await execute_template(actor.template_id, url)
            return {"success": True, "actor_id": actor_id, "data": result.get("data", {})}
        return {
            "success": True,
            "actor_id": actor_id,
            "message": "Custom actor code not yet executed",
        }
