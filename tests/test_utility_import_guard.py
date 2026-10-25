"""Fail when a new rate-limit / retry / dedupe module appears outside canon.

Allowlist entries carry a reason and must match a real file, so the list can
only shrink (tech-debt ratchet). Run against a repo root with ``XDUP_ROOT``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("XDUP_ROOT", "/srv/work/wt/xdup45"))
REPOS = {"pryscraper": "src", "rugbrain": "src", "rmi-backend": "app"}
SCOPE = re.compile(r"(^|/)_?[\w]*(rate_?limit|retry|backoff|dedup)[\w]*\.py$", re.I)

# (repo, path prefix, reason) — canonical owners first, then legacy debt.
ALLOW = [
    ("pryscraper", "src/pry/engine/retry.py", "canonical retry (pry)"),
    ("pryscraper", "src/pry/engine/retry_after.py", "canonical Retry-After helper"),
    ("pryscraper", "src/pry/engine/tier_retry_policy.py", "per-tier policy data for canonical retry"),
    ("pryscraper", "src/pry/core/ratelimit.py", "canonical outbound rate limiter"),
    ("pryscraper", "src/pry/core/middleware_ratelimit.py", "canonical inbound middleware"),
    ("pryscraper", "src/pry/core/user_ratelimit", "canonical per-user quota cluster (4 modules)"),
    ("pryscraper", "src/pry/engine/dedup.py", "SimHash page dedupe, no rugbrain equivalent"),
    ("rmi-backend", "app/core/rate_limiter.py", "canonical inbound limiter (UnifiedRateLimiter)"),
    ("rmi-backend", "app/core/rate_limits.py", "canonical tier/category data"),
    ("rmi-backend", "app/core/rate_limit_tiers.py", "canonical tier enum, consumed by rate_limits"),
    ("rmi-backend", "app/core/rate_limit_config.py", "canonical settings for rate_limits"),
    ("rmi-backend", "app/caching_shield/rate_limiter.py", "LEGACY deprecated but still imported by caching_shield/router.py"),
    ("rmi-backend", "app/rate_limiter.py", "LEGACY LLM provider dispatcher, different job: rename to llm_capacity"),
    ("rmi-backend", "app/assistant_gateway/ratelimit.py", "LEGACY migrate to core.rate_limiter"),
    ("rmi-backend", "app/databus/x_intel/x_proxy/ratelimit.py", "LEGACY migrate to core.rate_limiter"),
    ("rmi-backend", "app/domains/billing/x402_exact/ratelimit.py", "LEGACY migrate to core.rate_limiter"),
    ("rmi-backend", "app/domains/poly_attribution/rate_limit.py", "LEGACY migrate to core.rate_limiter"),
    ("rmi-backend", "app/domains/prediction/opportunities/rate_limit.py", "LEGACY migrate to core.rate_limiter"),
    ("rmi-backend", "app/routers/x402_databus_tools/rate_limit.py", "LEGACY migrate to core.rate_limiter"),
    ("rmi-backend", "app/utils/dedup", "LEGACY rmi dedupe cluster (13 modules)"),
    ("rmi-backend", "app/mmr_dedup.py", "LEGACY MMR dedupe, no owner yet"),
    ("rmi-backend", "app/feed_quality_pipeline/deduplicator.py", "LEGACY migrate to rugbrain story_key"),
    ("rmi-backend", "app/databus/services/dedup.py", "LEGACY migrate to rugbrain story_key"),
    ("rugbrain", "src/rugbrain/content_dedupe.py", "canonical near-dup collapse"),
    ("rugbrain", "src/rugbrain/ingest_sources/ingest_dedupe.py", "canonical shingle/jaccard primitives"),
    ("rugbrain", "src/rugbrain/ingest_sources/shared/retry.py", "canonical retry (rugbrain), parity-pinned to pry"),
    ("rugbrain", "src/rugbrain/ingest_sources/x_intel/dedupe.py", "LEGACY migrate to ingest_dedupe"),
    ("rugbrain", "src/rugbrain/app_chunking/_dedup.py", "LEGACY chunk dedupe, migrate to ingest_dedupe"),
    ("rugbrain", "src/rugbrain/scam_watch/dedupe.py", "LEGACY migrate to story_key"),
    ("rugbrain", "src/rugbrain/monitors/social_sentiment/rate_limit.py", "LEGACY 1 rps on module globals, migrate to a limiter instance"),
]


def allowed(repo: str, rel: str) -> bool:
    return any(repo == r and rel.startswith(prefix) for r, prefix, _ in ALLOW)


def find_modules(root: Path = ROOT) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for repo, sub in REPOS.items():
        base = root / repo / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root / repo).as_posix()
            if SCOPE.search(rel):
                found.append((repo, rel))
    return found


def test_no_utility_module_outside_canonical():
    violations = [f"{repo}/{rel}" for repo, rel in find_modules() if not allowed(repo, rel)]
    assert not violations, (
        "new rate-limit/retry/dedupe module outside canonical location: "
        f"{violations}. Extend the canonical module, or add an ALLOW entry with a reason."
    )


def test_allowlist_has_no_stale_entries():
    found = find_modules()
    stale = [
        f"{repo}/{prefix}"
        for repo, prefix, _ in ALLOW
        if not any(r == repo and rel.startswith(prefix) for r, rel in found)
    ]
    assert not stale, f"allowlist entries match no file (delete them, ratchet only shrinks): {stale}"


def test_every_allow_entry_states_a_reason():
    assert all(len(reason) > 10 for _, _, reason in ALLOW)


def test_guard_rejects_a_new_copy(tmp_path):
    (tmp_path / "pryscraper/src/pry/core").mkdir(parents=True)
    (tmp_path / "pryscraper/src/pry/core/rate_limit_v2.py").write_text("x = 1\n")
    (tmp_path / "pryscraper/src/pry/engine").mkdir(parents=True)
    (tmp_path / "pryscraper/src/pry/engine/retry_after.py").write_text("x = 1\n")
    found = find_modules(tmp_path)
    assert ("pryscraper", "src/pry/core/rate_limit_v2.py") in found
    assert not allowed("pryscraper", "src/pry/core/rate_limit_v2.py")
    assert allowed("pryscraper", "src/pry/engine/retry_after.py")


# --- utility-module ownership (pry-utils-49) -------------------------------
# A second rate_limit*/extractor*/retry* module re-creates duplication this repo
# already paid for (19 rate-limit copies, 17 extractor copies). One owner per
# capability; the allowlist is shrink-only (dead entries fail too).
_UTILITY_OWNERS: dict[str, str] = {
    "core/ratelimit.py": "inbound per-IP bucket (Redis + memory)",
    "core/outbound_politeness.py": "outbound per-key spacing + capped backoff",
    "engine/extractor.py": "canonical schema extractor",
    "engine/retry.py": "retry policy + backoff math",
    "engine/email_scraper/extractor.py": "email-pattern extractor (own domain)",
}


def test_utility_modules_have_one_owner():
    import re

    pattern = re.compile(r"^(rate_?limit|extractor|retry)")
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "pry"
    offenders = sorted(
        str(p.relative_to(src))
        for p in src.rglob("*.py")
        if "__pycache__" not in p.parts and pattern.search(p.stem)
    )
    unknown = [rel for rel in offenders if rel not in _UTILITY_OWNERS]
    assert unknown == [], (
        f"utility module outside a canonical path: {unknown}. "
        "Reuse the canonical module or add it to _UTILITY_OWNERS with a reason."
    )


def test_utility_owner_allowlist_has_no_dead_entries():
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "pry"
    missing = [rel for rel in _UTILITY_OWNERS if not (src / rel).is_file()]
    assert missing == [], f"stale allowlist entries (shrink-only): {missing}"

