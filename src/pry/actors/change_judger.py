"""Pry — change judgement for monitors (LLM or heuristic)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import difflib
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _change_verdict(ratio: float, goal_relevant: bool) -> dict[str, Any]:
    return {
        "meaningful": True,
        "confidence": "medium" if goal_relevant else "low",
        "reason": (
            "Goal-relevant content was updated"
            if goal_relevant
            else f"Content changed by {ratio:.1%}"
        ),
        "meaningful_changes": [
            {"type": "changed", "description": f"Content size changed by {ratio:.1%}"}
        ],
    }


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

        if len(previous) > 0:
            ratio = abs(len(current) - len(previous)) / len(previous)
            if ratio > (0.01 if goal_in_current else 0.1):
                return _change_verdict(ratio, goal_in_current)

        return {
            "meaningful": False,
            "confidence": "low",
            "reason": "Minor or irrelevant change",
            "meaningful_changes": [],
        }

    async def _llm_judge(self, previous: str, current: str, goal: str) -> dict[str, Any]:
        try:
            from pry.api.client import get_client
            from pry.core.settings import settings

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
