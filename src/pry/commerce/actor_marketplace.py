# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pry.core.deps import scraper as _scraper
from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)
ACTOR_DIR = PRY_DATA_DIR / "actors"
ACTOR_DIR.mkdir(parents=True, exist_ok=True)


def preset_specs() -> dict[str, Any]:
    """Return ``{preset_id: ActorSpec}``; empty when actor_factory is absent."""
    try:
        from actor_factory.presets import ALL_PRESETS
    except Exception:
        logger.warning("actor_presets_unavailable", exc_info=True)
        return {}
    return dict(ALL_PRESETS)


class ActorVisibility(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    UNLISTED = "unlist"


@dataclass
class Actor:
    """A reusable scraper actor that can be run on demand or schedule."""

    actor_id: str
    name: str
    description: str
    template_id: str = ""
    code: str = ""
    price_per_run: float = 0.0
    visibility: ActorVisibility = ActorVisibility.PRIVATE
    schedule_cron: str = ""
    tags: list[str] = field(default_factory=list)
    author: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    run_count: int = 0
    revenue_usd: float = 0.0
    processor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["visibility"] = self.visibility.value
        data["revenue_usd"] = round(self.revenue_usd, 4)
        return data


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
            tags or [],
            author,
        )
        self.actors[actor.actor_id] = actor
        self._save(actor)
        return actor

    def list(self, visibility: str = "", tag: str = "") -> list[dict[str, Any]]:
        rows = [
            a.to_dict()
            for a in self.actors.values()
            if (not visibility or a.visibility.value == visibility) and (not tag or tag in a.tags)
        ]
        return sorted(rows, key=lambda x: -x.get("run_count", 0))

    async def run(self, actor_id: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        actor = self.actors.get(actor_id)
        ephemeral = actor is None
        if actor is None:
            spec = preset_specs().get(actor_id)
            if spec is None:
                return {
                    "success": False,
                    "code": "not_found",
                    "error": f"Actor not found: {actor_id}",
                }
            category = str(getattr(spec.category, "value", spec.category))
            actor = Actor(
                actor_id,
                spec.title or actor_id,
                spec.description,
                visibility=ActorVisibility.PUBLIC,
                tags=[category],
            )
            actor.processor = spec.processor
        if ephemeral and actor.processor is None:
            return {
                "success": False,
                "code": "requires_processor",
                "error": f"Actor '{actor_id}' is unpriced (no processor)",
            }
        url = str((inputs or {}).get("url") or "").strip()
        if not url:
            return {"success": False, "code": "invalid_input", "error": "Missing 'url' input"}
        if actor.template_id:
            result = await self._run_template(actor.template_id, url)
        elif ephemeral and actor.processor:
            result = await self._run_scrape(url)
        else:
            return {
                "success": False,
                "code": "no_template",
                "error": f"Actor '{actor_id}' has no template to execute",
            }
        if not result["success"]:
            return {"success": False, "code": result["code"], "error": result["error"]}
        data = result["data"]
        if not data:
            return {
                "success": False,
                "code": "empty_result",
                "error": f"Actor '{actor_id}' produced no data",
            }
        # Accounting only after a real, non-empty result; never for presets.
        if not ephemeral:
            actor.run_count += 1
            if actor.price_per_run > 0:
                actor.revenue_usd += actor.price_per_run
            self._save(actor)
        extra = {"engine": actor.processor} if ephemeral else {}
        return {"success": True, "actor_id": actor_id, "data": data, **extra}

    async def _run_template(self, template_id: str, url: str) -> dict[str, Any]:
        from pry.commerce.template_engine import execute_template

        try:
            result = await execute_template(template_id, url)
        except Exception as e:
            logger.exception("actor_template_failed", extra={"template_id": template_id})
            return {"success": False, "code": "execution_error", "error": f"Template failed: {e}"}
        if result.get("success"):
            return {"success": True, "data": result.get("data") or {}}
        error = str(result.get("error") or "Template execution failed")
        code = "template_not_found" if error.startswith("Template not found") else "execution_error"
        return {"success": False, "code": result.get("code") or code, "error": error}

    async def _run_scrape(self, url: str) -> dict[str, Any]:

        try:
            result = await _scraper.scrape(url, {"bypass_cloudflare": True})
        except Exception as e:
            logger.exception("actor_scrape_failed", extra={"url": url})
            return {"success": False, "code": "scrape_failed", "error": f"Scrape failed: {e}"}
        if result.get("status") != "ok":
            return {
                "success": False,
                "code": "scrape_failed",
                "error": result.get("error") or "Scrape failed",
            }
        content = str(result.get("content") or result.get("raw_html") or "")
        return {
            "success": True,
            "data": {
                "url": url,
                "status": "ok",
                "content": content,
                "content_length": len(content),
            },
        }
