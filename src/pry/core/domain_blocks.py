"""Domain-level legal blocks (451) shared by routers and scrapers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import logging
import os
import re
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import Text, func, text

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)


def _data_dir() -> str:
    return os.environ.get("PRY_DATA_DIR", os.path.expanduser("~/.pry"))


_DDL = (
    "CREATE TABLE IF NOT EXISTS domain_blocks (domain VARCHAR(255) PRIMARY KEY, "
    "reason VARCHAR(255) NOT NULL DEFAULT '', created_at VARCHAR(40) NOT NULL DEFAULT '')"
)
_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _host(domain: str) -> str:
    """Normalise a URL or hostname to a bare lowercase host, or raise ValueError."""
    value = urlsplit(domain).hostname if "://" in domain else domain.split("/")[0]
    value = (value or "").strip().lower().rstrip(".").split(":")[0]
    if not _HOST_RE.match(value):
        raise ValueError(f"Invalid domain: {domain!r}")
    return value


def is_domain_blocked(domain: str) -> bool:
    """True when the host is blocked. Fails open (logged) if the DB is down."""
    from pry.core.db.session import session_scope

    try:
        host = _host(domain)
        with session_scope() as session:
            session.execute(text(_DDL))
            row = session.execute(
                text("SELECT 1 FROM domain_blocks WHERE domain = :d"), {"d": host}
            ).first()
            return row is not None
    except Exception:
        logger.warning("domain_block_check_failed", exc_info=True)
        return False


def _url_matches(host: str) -> Any:
    def matches(data: dict[str, Any]) -> bool:
        urls = [data.get("url"), (data.get("metadata") or {}).get("url")]
        return any(isinstance(u, str) and urlsplit(u).hostname == host for u in urls)

    return matches


def purge_domain(domain: str, dry_run: bool = True) -> dict[str, Any]:
    """Count (dry run) or purge every stored record whose URL belongs to ``domain``."""
    from pry.compliance import record_store
    from pry.compliance._deletion_scan import _purge_matching_json
    from pry.core.db.models import ScrapeJob, Usage
    from pry.core.db.session import session_scope

    host = _host(domain)
    reports: list[dict[str, Any]] = []
    roots = (("quality", PRY_DATA_DIR / "quality"), ("sessions", PRY_DATA_DIR / "sessions"))
    for store, directory in roots:
        if not directory.is_dir():
            reports.append({"store": store, "affected": 0, "state": "absent"})
        elif dry_run:
            matches = _url_matches(host)
            affected = sum(
                1
                for p in directory.glob("*.json")
                if (data := record_store.load(p)) is not None and matches(data)
            )
            reports.append({"store": store, "affected": affected, "state": "ok"})
        else:
            affected = _purge_matching_json(directory, _url_matches(host))[0]
            reports.append({"store": store, "affected": affected, "state": "ok"})
    with session_scope() as session:
        queries = (
            ("usage", session.query(Usage).filter(func.lower(Usage.endpoint).like(f"%{host}%"))),
            (
                "scrape_jobs",
                session.query(ScrapeJob).filter(
                    cast("ScrapeJob.input_data", Text).like(f"%{host}%")
                ),
            ),
        )
        for store, query in queries:
            affected = int(query.count())
            if affected and not dry_run:
                query.delete(synchronize_session=False)
            reports.append({"store": store, "affected": affected, "state": "ok"})
    return {
        "domain": host,
        "dry_run": dry_run,
        "stores": reports,
        "total_affected": sum(r["affected"] for r in reports),
    }
