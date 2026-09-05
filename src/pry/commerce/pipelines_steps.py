"""Pry — Pipeline step type registry.

Metadata definitions for every step type the visual pipeline builder
supports. A UI can render these as drag-and-drop blocks."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from typing import Any

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
