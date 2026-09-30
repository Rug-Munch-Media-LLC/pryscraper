"""In-memory issue tracker for the admin surface.

Split from admin_shared.py on 2026-08-29 to clear the 200-line structure cap.
Pure stdlib, no FastAPI surface: admin_issues.py imports these names lazily from
admin_shared, and admin_shared re-exports them, so every import path is unchanged.
"""

from __future__ import annotations

import itertools
import logging
import threading
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_ISSUES: dict[str, dict[str, Any]] = {}
_ISSUES_LOCK = threading.Lock()
_ISSUE_SEQ = itertools.count(1)


def _create_issue(
    title: str,
    severity: str = "medium",
    description: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Register a new support issue and return it."""
    issue_id = f"ISS-{next(_ISSUE_SEQ):04d}"
    issue = {
        "id": issue_id,
        "title": title,
        "description": description,
        "severity": severity if severity in ("critical", "high", "medium", "low") else "medium",
        "status": "open",
        "user_id": user_id,
        "created_at": datetime.now(UTC).isoformat(),
        "resolved_at": None,
    }
    with _ISSUES_LOCK:
        _ISSUES[issue_id] = issue
    return issue


def _resolve_issue(issue_id: str) -> dict[str, Any] | None:
    """Mark an issue resolved (idempotent); None only if the ID is unknown."""
    with _ISSUES_LOCK:
        issue = _ISSUES.get(issue_id)
        if issue is None:
            return None
        if issue["status"] != "resolved":
            issue["status"] = "resolved"
            issue["resolved_at"] = datetime.now(UTC).isoformat()
        return dict(issue)


class _SeverityCounter(dict[str, int]):
    """Count open issues per severity, highest first in the summary payload."""

    def __init__(self, severities) -> None:
        super().__init__(dict.fromkeys(("critical", "high", "medium", "low"), 0))
        for sev in severities:
            if sev in self:
                self[sev] += 1


def _unresolved_payment_count() -> int:
    """Failed payments in the last 30 days; degrades to 0 rather than failing."""
    try:
        from pry.compliance.earnings import PaymentAnalytics

        return int(PaymentAnalytics().get_revenue_summary(30).get("failed_payments", 0))
    except Exception as exc:  # noqa: BLE001 - summary must degrade, not fail
        logger.warning("issue_unresolved_payments_fetch_failed", extra={"error": str(exc)})
        return 0


def _issue_summary() -> dict[str, Any]:
    """Aggregate open issues by severity plus unresolved payment count."""
    with _ISSUES_LOCK:
        issues = [dict(i) for i in _ISSUES.values()]
    open_issues = [i for i in issues if i["status"] == "open"]
    by_sev = _SeverityCounter(i["severity"] for i in open_issues)
    recent = sorted(issues, key=lambda i: i["created_at"], reverse=True)[:20]
    unresolved_payments = _unresolved_payment_count()
    return {
        "open_issues": len(open_issues),
        "critical": by_sev.get("critical", 0),
        "high": by_sev.get("high", 0),
        "medium": by_sev.get("medium", 0),
        "low": by_sev.get("low", 0),
        "recent_issues": recent,
        "unresolved_payments": unresolved_payments,
    }
