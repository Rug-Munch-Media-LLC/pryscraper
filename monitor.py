"""Pry — scheduled monitors with AI change detection.
Cron-based monitors that diff content and judge meaningful changes."""

import difflib
import json
import logging
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MONITORS_DIR = Path(os.path.expanduser("~/.pry/monitors"))
MONITORS_DIR.mkdir(parents=True, exist_ok=True)


def _monitor_path(monitor_id: str) -> Path:
    return MONITORS_DIR / f"{monitor_id}.json"


def _snapshot_path(monitor_id: str, version: int) -> Path:
    snap_dir = MONITORS_DIR / monitor_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    return snap_dir / f"snapshot_{version}.json"


def _compute_diff(previous: str, current: str) -> str:
    differ = difflib.Differ()
    diff = list(differ.compare(previous.splitlines(), current.splitlines()))
    added = sum(1 for line in diff if line.startswith("+ "))
    removed = sum(1 for line in diff if line.startswith("- "))
    return f"{added} lines added, {removed} lines removed"


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

        # Check if goal keywords appear in newly-added tokens
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

        # Content changed and goal keywords still present -> meaningful update
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

        # Large generic change (no goal or goal keywords absent)
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
                return json.loads(json_match.group(0))  # type: ignore[no-any-return]
        except Exception:
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
    monitor = {
        "id": monitor_id,
        "name": name,
        "target_url": target_url,
        "schedule_cron": schedule_cron,
        "goal": goal,
        "webhook_url": webhook_url,
        "use_llm_judge": use_llm_judge,
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
        "last_run_at": None,
        "current_version": 0,
        "last_content": "",
        "total_checks": 0,
        "total_changes": 0,
    }
    path = _monitor_path(monitor_id)
    path.write_text(json.dumps(monitor, indent=2))
    logger.info("monitor_created", extra={"monitor_id": monitor_id, "name": name})
    return monitor


async def run_monitor(monitor_id: str) -> dict[str, Any]:
    path = _monitor_path(monitor_id)
    if not path.exists():
        return {"error": f"Monitor not found: {monitor_id}"}

    monitor = json.loads(path.read_text())
    previous_content = monitor.get("last_content", "")

    try:
        from scraper import PryScraper

        scraper = PryScraper()
        result = await scraper.scrape(monitor["target_url"])
        current_content = result.get("content", "")
    except Exception as e:
        logger.exception("monitor_scrape_failed", extra={"monitor_id": monitor_id})
        return {"error": f"Scrape failed: {e!s}"}

    judger = ChangeJudger(use_llm=monitor.get("use_llm_judge", False))
    judgment = await judger.judge(previous_content, current_content, monitor.get("goal", ""))

    monitor["last_run_at"] = datetime.now(UTC).isoformat()
    monitor["total_checks"] += 1
    if previous_content and current_content != previous_content:
        monitor["total_changes"] += 1
        monitor["current_version"] += 1
        snap = {
            "version": monitor["current_version"],
            "content": current_content,
            "detected_at": monitor["last_run_at"],
        }
        _snapshot_path(monitor_id, monitor["current_version"]).write_text(json.dumps(snap))
    monitor["last_content"] = current_content
    path.write_text(json.dumps(monitor, indent=2))

    result = {
        "monitor_id": monitor_id,
        "name": monitor["name"],
        "changed": bool(previous_content) and current_content != previous_content,
        "previous_content_length": len(previous_content),
        "current_content_length": len(current_content),
        "judgment": judgment,
        "total_checks": monitor["total_checks"],
        "total_changes": monitor["total_changes"],
    }

    if judgment["meaningful"] and monitor.get("webhook_url"):
        await _fire_webhook(monitor["webhook_url"], result)

    return result


async def _fire_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    try:
        from client import get_client

        client = await get_client()
        await client.post(webhook_url, json=payload, timeout=10)
        logger.info("monitor_webhook_fired", extra={"webhook": webhook_url})
    except Exception as e:
        logger.warning("monitor_webhook_failed", extra={"webhook": webhook_url, "error": str(e)})


async def list_monitors() -> list[dict[str, Any]]:
    monitors = []
    for path in sorted(MONITORS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            monitors.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return monitors


async def delete_monitor(monitor_id: str) -> bool:
    path = _monitor_path(monitor_id)
    snap_dir = MONITORS_DIR / monitor_id
    if snap_dir.exists():
        shutil.rmtree(snap_dir)
    if path.exists():
        path.unlink()
        return True
    return False
