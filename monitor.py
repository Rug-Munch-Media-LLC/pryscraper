"""Pry — scheduled monitors with AI change detection.
Cron-based monitors that diff content and judge meaningful changes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import difflib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from db import Monitor, MonitorRun, session_scope

logger = logging.getLogger(__name__)


def _compute_diff(previous: str, current: str) -> str:
    differ = difflib.Differ()
    diff = list(differ.compare(previous.splitlines(), current.splitlines()))
    added = sum(1 for line in diff if line.startswith("+ "))
    removed = sum(1 for line in diff if line.startswith("- "))
    return f"{added} lines added, {removed} lines removed"


def _monitor_to_dict(m: Monitor) -> dict[str, Any]:
    return {
        "id": m.monitor_id,
        "name": m.monitor_name,
        "target_url": m.url,
        "schedule_cron": m.schedule_cron,
        "goal": m.goal or "",
        "webhook_url": m.webhook_url or "",
        "use_llm_judge": m.use_llm_judge or False,
        "status": "active" if m.active else "inactive",
        "created_at": m.created_at.isoformat() if m.created_at else "",
        "last_run_at": m.last_run_at.isoformat() if m.last_run_at else None,
        "current_version": m.current_version or 0,
        "last_content": m.last_content or "",
        "total_checks": m.total_checks or 0,
        "total_changes": m.total_changes or 0,
    }


class ChangeJudger:
    """Judge whether a content change is meaningful using LLM or heuristics."""

    def __init__(self, use_llm: bool = False) -> None:
        self.use_llm = use_llm

    async def judge(self, previous: str, current: str, goal: str = "") -> dict[str, Any]:
        """Judge if a change is meaningful.

        Returns:
            meaningful: bool
            confidence: str (high/medium/low)
            reason: str
            meaningful_changes: list[dict]
        """
        if previous == current:
            return {
                "meaningful": False,
                "confidence": "high",
                "reason": "No change detected",
                "meaningful_changes": [],
            }
        if not goal:
            return {
                "meaningful": True,
                "confidence": "high",
                "reason": "Content changed",
                "meaningful_changes": [{"type": "changed", "description": "Content was modified"}],
            }
        if self.use_llm:
            return await self._llm_judge(previous, current, goal)
        return self._heuristic_judge(previous, current, goal)

    def _heuristic_judge(self, previous: str, current: str, goal: str) -> dict[str, Any]:
        goal_keywords = goal.lower().split()
        prev_text_lower = previous.lower()
        curr_text_lower = current.lower()

        prev_keywords = set(prev_text_lower.split())
        curr_keywords = set(curr_text_lower.split())
        added = curr_keywords - prev_keywords

        goal_in_current = any(gk in curr_text_lower for gk in goal_keywords)

        def _keyword_match(tokens: set[str]) -> list[str]:
            matched: list[str] = []
            for gk in goal_keywords:
                for t in tokens:
                    if gk in t or t in gk:
                        matched.append(gk)
                        break
            return matched

        goal_added = _keyword_match(added)

        if goal_added:
            return {
                "meaningful": True,
                "confidence": "medium",
                "reason": f"Goal-related keywords appeared: {', '.join(sorted(goal_added))}",
                "meaningful_changes": [
                    {
                        "type": "added",
                        "description": f"Relevant keywords appeared: {', '.join(sorted(goal_added))}",
                    }
                ],
            }

        if goal_in_current and len(previous) > 0:
            change_ratio = abs(len(current) - len(previous)) / len(previous)
            if change_ratio > 0.01:
                return {
                    "meaningful": True,
                    "confidence": "medium",
                    "reason": "Goal-relevant content was updated",
                    "meaningful_changes": [
                        {
                            "type": "changed",
                            "description": f"Content size changed by {change_ratio:.1%}",
                        }
                    ],
                }

        if len(previous) > 0:
            change_ratio = abs(len(current) - len(previous)) / len(previous)
            if change_ratio > 0.1:
                return {
                    "meaningful": True,
                    "confidence": "low",
                    "reason": f"Content changed by {change_ratio:.1%}",
                    "meaningful_changes": [
                        {
                            "type": "changed",
                            "description": f"Content size changed by {change_ratio:.1%}",
                        }
                    ],
                }

        return {
            "meaningful": False,
            "confidence": "low",
            "reason": "Minor or irrelevant change",
            "meaningful_changes": [],
        }

    async def _llm_judge(self, previous: str, current: str, goal: str) -> dict[str, Any]:
        try:
            from client import get_client
            from settings import settings

            diff = _compute_diff(previous, current)
            prompt = f"""Goal: {goal}

Previous content:
{previous[:1000]}

Current content:
{current[:1000]}

Diff:
{diff[:500]}

Is this change meaningful given the goal? Respond with JSON:
{{"meaningful": bool, "confidence": "high/medium/low", "reason": "string", "meaningful_changes": [{{"type": "changed/added/removed", "description": "string"}}]}}
"""
            client = await get_client()
            resp = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": "qwen2.5-coder:3b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_ctx": 4096, "temperature": 0.1},
                },
                timeout=30,
            )
            response_text = resp.json().get("response", "")
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except (json.JSONDecodeError, ValueError):
            logger.warning("llm_judge_failed, falling back to heuristic")

        return self._heuristic_judge(previous, current, goal)


async def create_monitor(
    name: str,
    target_url: str,
    schedule_cron: str = "0 */6 * * *",
    goal: str = "",
    webhook_url: str = "",
    use_llm_judge: bool = False,
) -> dict[str, Any]:
    monitor_id = uuid.uuid4().hex[:12]
    now = datetime.now(UTC)
    monitor = Monitor(
        monitor_id=monitor_id,
        url=target_url,
        monitor_name=name,
        schedule_cron=schedule_cron,
        goal=goal,
        use_llm_judge=use_llm_judge,
        active=True,
        webhook_url=webhook_url,
        created_at=now,
        current_version=0,
        last_content="",
        total_checks=0,
        total_changes=0,
    )
    try:
        with session_scope() as s:
            s.add(monitor)
        logger.info("monitor_created", extra={"monitor_id": monitor_id, "monitor_name": name})
        return _monitor_to_dict(monitor)
    except Exception:
        logger.exception("monitor_creation_failed", extra={"monitor_name": name})
        raise


async def run_monitor(monitor_id: str) -> dict[str, Any]:
    try:
        with session_scope() as s:
            monitor = s.query(Monitor).filter(Monitor.monitor_id == monitor_id).first()
            if not monitor:
                return {"error": f"Monitor not found: {monitor_id}"}

            previous_content = monitor.last_content or ""

            try:
                from scraper import PryScraper

                scraper = PryScraper()
                result = await scraper.scrape(monitor.url)
                current_content = result.get("content", "")
            except Exception as e:
                logger.exception("monitor_scrape_failed", extra={"monitor_id": monitor_id})
                run = MonitorRun(
                    monitor_id=monitor_id,
                    ts=datetime.now(UTC),
                    status="error",
                    error=str(e),
                )
                s.add(run)
                return {"error": f"Scrape failed: {e!s}"}

            judger = ChangeJudger(use_llm=monitor.use_llm_judge)
            judgment = await judger.judge(previous_content, current_content, monitor.goal or "")

            changed = bool(previous_content) and current_content != previous_content
            now = datetime.now(UTC)
            monitor.last_run_at = now
            monitor.total_checks = (monitor.total_checks or 0) + 1

            run_status = "success"
            diff_data = {}
            if changed:
                monitor.total_changes = (monitor.total_changes or 0) + 1
                monitor.current_version = (monitor.current_version or 0) + 1
                run_status = "changed"
                diff_data = {
                    "previous_length": len(previous_content),
                    "current_length": len(current_content),
                    "diff": _compute_diff(previous_content, current_content),
                }

            monitor.last_content = current_content

            run = MonitorRun(
                monitor_id=monitor_id,
                ts=now,
                status=run_status,
                diff=diff_data,
            )
            s.add(run)

            result = {
                "monitor_id": monitor_id,
                "name": monitor.monitor_name,
                "changed": changed,
                "previous_content_length": len(previous_content),
                "current_content_length": len(current_content),
                "judgment": judgment,
                "total_checks": monitor.total_checks,
                "total_changes": monitor.total_changes,
            }

            webhook_url = monitor.webhook_url
            meaningful = judgment["meaningful"]

        if meaningful and webhook_url:
            await _fire_webhook(webhook_url, result)

        return result
    except Exception:
        logger.exception("monitor_run_failed", extra={"monitor_id": monitor_id})
        return {"error": f"Monitor run failed: {monitor_id}"}


async def _fire_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    try:
        from client import get_client

        client = await get_client()
        await client.post(webhook_url, json=payload, timeout=10)
        logger.info("monitor_webhook_fired", extra={"webhook": webhook_url})
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning("monitor_webhook_failed", extra={"webhook": webhook_url, "error": str(e)})


async def list_monitors() -> list[dict[str, Any]]:
    try:
        with session_scope() as s:
            monitors = (
                s.query(Monitor)
                .filter(Monitor.active.is_(True))
                .order_by(Monitor.created_at.desc())
                .all()
            )
            return [_monitor_to_dict(m) for m in monitors]
    except Exception:
        logger.exception("monitor_list_failed")
        return []


async def delete_monitor(monitor_id: str) -> bool:
    try:
        with session_scope() as s:
            monitor = s.query(Monitor).filter(Monitor.monitor_id == monitor_id).first()
            if not monitor:
                return False
            s.delete(monitor)
        logger.info("monitor_deleted", extra={"monitor_id": monitor_id})
        return True
    except Exception:
        logger.exception("monitor_delete_failed", extra={"monitor_id": monitor_id})
        return False
