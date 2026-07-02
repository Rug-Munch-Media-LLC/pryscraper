"""Pry — No-Code Visual Pipeline Builder.
JSON-defined workflow engine. Users define pipelines as structured steps,
the engine executes them sequentially with branching and error handling.

A UI can render these steps as drag-and-drop blocks."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

PIPELINE_DIR = PRY_DATA_DIR / "pipelines"
PIPELINE_DIR.mkdir(parents=True, exist_ok=True)

# ── Step Types Registry ──

STEP_TYPES: dict[str, dict[str, Any]] = {
    "scrape": {
        "name": "Scrape URL",
        "icon": "globe",
        "description": "Scrape a single URL",
        "inputs": [
            {"key": "url", "type": "url", "label": "URL to scrape", "required": True},
            {
                "key": "bypass_cloudflare",
                "type": "boolean",
                "label": "Bypass Cloudflare",
                "default": True,
            },
        ],
        "outputs": ["content", "title", "html", "status"],
    },
    "extract_css": {
        "name": "CSS Extraction",
        "icon": "clipboard",
        "description": "Extract structured data with CSS selectors",
        "inputs": [
            {"key": "url", "type": "url", "label": "URL", "required": True},
            {"key": "schema", "type": "json", "label": "Extraction Schema", "required": True},
        ],
        "outputs": ["items", "count"],
    },
    "extract_llm": {
        "name": "LLM Extraction",
        "icon": "robot",
        "description": "Extract with AI + chunking",
        "inputs": [
            {"key": "url", "type": "url", "label": "URL", "required": True},
            {
                "key": "instruction",
                "type": "text",
                "label": "Extraction instruction",
                "required": True,
            },
            {
                "key": "chunk_strategy",
                "type": "select",
                "options": ["topic", "sentence", "regex"],
                "label": "Chunk strategy",
                "default": "topic",
            },
        ],
        "outputs": ["chunks", "total_chunks"],
    },
    "quality_check": {
        "name": "Quality Check",
        "icon": "check-circle",
        "description": "Validate data quality before delivery",
        "inputs": [
            {"key": "url", "type": "url", "label": "Source URL", "required": True},
            {"key": "data", "type": "json", "label": "Data to validate", "required": True},
            {
                "key": "expected_types",
                "type": "json",
                "label": "Expected field types",
                "required": False,
            },
        ],
        "outputs": ["quality_score", "anomalies", "completeness"],
    },
    "send_slack": {
        "name": "Send to Slack",
        "icon": "message-circle",
        "description": "Send results to a Slack channel",
        "inputs": [
            {"key": "webhook_url", "type": "url", "label": "Slack Webhook URL", "required": True},
            {"key": "message", "type": "text", "label": "Message", "required": True},
        ],
        "outputs": ["success"],
    },
    "send_email": {
        "name": "Send Email",
        "icon": "mail",
        "description": "Send results via email",
        "inputs": [
            {"key": "recipient", "type": "email", "label": "Recipient", "required": True},
            {"key": "subject", "type": "text", "label": "Subject", "required": True},
            {"key": "body", "type": "text", "label": "Body", "required": True},
        ],
        "outputs": ["success"],
    },
    "compliance_check": {
        "name": "Compliance Check",
        "icon": "shield",
        "description": "Legal compliance scan before scraping",
        "inputs": [
            {"key": "url", "type": "url", "label": "URL to check", "required": True},
        ],
        "outputs": ["risk_level", "risk_score", "recommendations"],
    },
    "reconcile": {
        "name": "Entity Reconciliation",
        "icon": "link",
        "description": "Match records across sources",
        "inputs": [
            {"key": "records", "type": "json", "label": "Records to reconcile", "required": True},
            {
                "key": "vertical",
                "type": "select",
                "options": ["product", "job", "real_estate", "review"],
                "label": "Vertical",
                "default": "product",
            },
        ],
        "outputs": ["entities", "report"],
    },
    "conditional": {
        "name": "Conditional Branch",
        "icon": "git-branch",
        "description": "Branch based on a condition",
        "inputs": [
            {
                "key": "condition",
                "type": "text",
                "label": "JavaScript condition expression",
                "required": True,
            },
        ],
        "outputs": ["true", "false"],
    },
    "delay": {
        "name": "Delay",
        "icon": "clock",
        "description": "Wait before next step",
        "inputs": [
            {
                "key": "seconds",
                "type": "number",
                "label": "Seconds to wait",
                "default": 5,
                "required": True,
            },
        ],
        "outputs": ["waited"],
    },
    "transform": {
        "name": "Transform Data",
        "icon": "refresh-cw",
        "description": "Apply JSON transformation to data",
        "inputs": [
            {"key": "data", "type": "json", "label": "Input data", "required": True},
            {
                "key": "transform",
                "type": "json",
                "label": "JQ-style transform rules",
                "required": True,
            },
        ],
        "outputs": ["result"],
    },
    "export_training": {
        "name": "Export Training Data",
        "icon": "brain",
        "description": "Export as AI training dataset",
        "inputs": [
            {"key": "records", "type": "json", "label": "Records to export", "required": True},
            {
                "key": "clean_room",
                "type": "boolean",
                "label": "Strip PII/copyright",
                "default": True,
            },
        ],
        "outputs": ["dataset_id", "record_count"],
    },
}


# ── Pipeline Engine ──


def validate_pipeline(pipeline: dict[str, Any]) -> list[str]:
    """Validate a pipeline definition. Returns list of errors."""
    errors = []
    steps = pipeline.get("steps", [])
    if not steps:
        errors.append("Pipeline must have at least one step")

    step_ids = set()
    for i, step in enumerate(steps):
        step_id = step.get("id", f"step_{i}")
        if step_id in step_ids:
            errors.append(f"Duplicate step ID: {step_id}")
        step_ids.add(step_id)

        step_type = step.get("type")
        if step_type not in STEP_TYPES:
            errors.append(f"Step {i}: Unknown type '{step_type}'")
            continue

        step_def = STEP_TYPES[step_type]
        for inp in step_def["inputs"]:
            if inp.get("required") and inp["key"] not in step.get("inputs", {}):
                errors.append(f"Step '{step_id}': Missing required input '{inp['key']}'")

    return errors


async def run_pipeline(
    pipeline: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute a pipeline definition sequentially.

    Args:
        pipeline: Pipeline definition with steps array
        context: Initial context variables

    Returns execution results with step outputs.
    """
    pipeline_id = pipeline.get("id") or uuid.uuid4().hex[:8]
    steps = pipeline.get("steps", [])
    ctx = dict(context or {})
    results: list[dict[str, Any]] = []
    failed = False
    error: str | None = None

    for i, step in enumerate(steps):
        step_id = step.get("id", f"step_{i}")
        step_type = step.get("type")
        inputs = step.get("inputs", {})

        # Resolve template variables in inputs
        resolved_inputs = _resolve_templates(inputs, ctx)

        logger.info(
            "pipeline_step_start",
            extra={"pipeline_id": pipeline_id, "step": step_id, "type": step_type},
        )

        step_result: dict[str, Any] = {
            "step_id": step_id,
            "type": step_type,
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
        }

        try:
            output = await _execute_step(step_type, resolved_inputs, ctx)
            step_result["status"] = "success"
            step_result["output"] = output
            # Store outputs in context as step_id.output_key
            if isinstance(output, dict):
                for key, value in output.items():
                    ctx[f"{step_id}.{key}"] = value
        except Exception as e:  # noqa: BLE001
            step_result["status"] = "failed"
            step_result["error"] = str(e)[:500]
            logger.error(
                "pipeline_step_failed",
                extra={"pipeline_id": pipeline_id, "step": step_id, "error": str(e)},
            )
            failed = True
            error = str(e)
            if step.get("on_error") == "abort":
                results.append(step_result)
                break

        step_result["finished_at"] = datetime.now(UTC).isoformat()
        results.append(step_result)

    return {
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline.get("name", "Unnamed"),
        "total_steps": len(steps),
        "completed_steps": len(results),
        "successful_steps": sum(1 for r in results if r["status"] == "success"),
        "failed_steps": sum(1 for r in results if r["status"] == "failed"),
        "failed": failed,
        "error": error,
        "steps": results,
        "context_keys": list(ctx.keys()),
    }


async def _execute_step(
    step_type: str, inputs: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """Execute a single pipeline step."""
    if step_type == "scrape":
        from scraper import PryScraper

        s = PryScraper()
        result = await s.scrape(
            inputs.get("url", ""), {"bypass_cloudflare": inputs.get("bypass_cloudflare", True)}
        )
        return result

    elif step_type == "extract_css":
        from extraction import JsonCssExtractionStrategy
        from scraper import PryScraper

        s = PryScraper()
        result = await s.scrape(inputs.get("url", ""))
        html = result.get("raw_html", "")
        if not html:
            from client import get_client

            client = await get_client()
            resp = await client.get(inputs["url"], timeout=30, follow_redirects=True)
            html = resp.text
        strategy = JsonCssExtractionStrategy(inputs.get("schema", {}))
        items = strategy.extract(html)
        return {"items": items, "count": len(items)}

    elif step_type == "quality_check":
        from quality import run_quality_check

        return await run_quality_check(
            url=inputs.get("url", ""),
            data=inputs.get("data", {}),
        )

    elif step_type == "compliance_check":
        from compliance import run_compliance_check

        return await run_compliance_check(inputs.get("url", ""))

    elif step_type == "reconcile":
        from reconciliation import reconcile

        return await reconcile(
            records=inputs.get("records", []),
            vertical=inputs.get("vertical", "product"),
        )

    elif step_type == "send_slack":
        from destinations import write_to_slack

        result = await write_to_slack(
            webhook_url=inputs.get("webhook_url", ""),
            message=inputs.get("message", ""),
        )
        return result

    elif step_type == "send_email":
        from destinations import write_to_email

        result = await write_to_email(
            recipient=inputs.get("recipient", ""),
            subject=inputs.get("subject", ""),
            body=inputs.get("body", ""),
        )
        return result

    elif step_type == "delay":
        import asyncio

        seconds = inputs.get("seconds", 5)
        await asyncio.sleep(seconds)
        return {"waited": seconds}

    elif step_type == "transform":
        data = inputs.get("data", {})
        transform = inputs.get("transform", {})
        result = _apply_transform(data, transform)
        return {"result": result}

    elif step_type == "export_training":
        from training_data import export_training_dataset

        result = export_training_dataset(
            records=inputs.get("records", []),
            clean_room=inputs.get("clean_room", True),
        )
        return result

    else:
        raise ValueError(f"Unknown step type: {step_type}")


def _resolve_templates(inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Resolve {{ variable }} templates in input values."""
    import re

    resolved: dict[str, Any] = {}
    for key, value in inputs.items():
        if isinstance(value, str):
            resolved[key] = re.sub(
                r"\{\{(\w+(?:\.\w+)*)\}\}", lambda m: str(ctx.get(m.group(1), m.group(0))), value
            )
        elif isinstance(value, dict):
            resolved[key] = _resolve_templates(value, ctx)
        elif isinstance(value, list):
            resolved[key] = [
                _resolve_templates(v, ctx) if isinstance(v, dict) else v for v in value
            ]
        else:
            resolved[key] = value
    return resolved


def _apply_transform(data: Any, transform: dict[str, Any]) -> Any:
    """Apply simple JQ-style transforms."""
    if isinstance(transform, dict):
        result: dict[str, Any] = {}
        for key, rule in transform.items():
            if isinstance(rule, str) and rule.startswith("$."):
                # JSON path extraction
                path = rule[2:].split(".")
                value = data
                for part in path:
                    if isinstance(value, dict):
                        value = value.get(part, None)
                    elif isinstance(value, list) and part.isdigit():
                        idx = int(part)
                        value = value[idx] if 0 <= idx < len(value) else None
                    else:
                        value = None
                result[key] = value
            elif isinstance(rule, str) and rule.startswith("$"):
                result[key] = data
            else:
                result[key] = rule
        return result
    return data


# ── Pipeline CRUD ──


def save_pipeline(pipeline: dict[str, Any]) -> dict[str, Any]:
    """Save a pipeline definition."""
    pipeline_id = pipeline.get("id") or uuid.uuid4().hex[:8]
    pipeline["id"] = pipeline_id
    pipeline["updated_at"] = datetime.now(UTC).isoformat()
    path = PIPELINE_DIR / f"{pipeline_id}.json"
    try:
        path.write_text(json.dumps(pipeline, indent=2))
        logger.info(
            "pipeline_saved",
            extra={"pipeline_id": pipeline_id, "pipeline_name": pipeline.get("name")},
        )
        return {"success": True, "pipeline_id": pipeline_id}
    except OSError as e:
        return {"success": False, "error": str(e)}


def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    """Get a saved pipeline definition."""
    path = PIPELINE_DIR / f"{pipeline_id}.json"
    if not path.exists():
        return None
    try:
        return cast("dict[str, Any]", json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


def list_pipelines() -> list[dict[str, Any]]:
    """List all saved pipelines."""
    pipelines = []
    for path in sorted(PIPELINE_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            pipelines.append(
                {
                    "id": data.get("id"),
                    "name": data.get("name", "Unnamed"),
                    "description": data.get("description", ""),
                    "step_count": len(data.get("steps", [])),
                    "updated_at": data.get("updated_at"),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return pipelines


def delete_pipeline(pipeline_id: str) -> bool:
    """Delete a saved pipeline."""
    path = PIPELINE_DIR / f"{pipeline_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
