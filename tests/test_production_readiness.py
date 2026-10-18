# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Production-readiness contracts: compose renders, env is documented, alembic
has one head, /health and /ready fail closed, no CI gate is neutralised, every
job is timed. No network, no container runtime, no database required."""

from __future__ import annotations

# Deliberately shells out to the `docker` CLI; no untrusted input.
# ruff: noqa: S603, S607
import glob
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ["docker-compose.yml", "compose.monitoring.yml"]
# Overlays use `!reset`/`!override` and are only valid MERGED over the base.
COMPOSE_OVERLAYS = [("docker-compose.yml", "docker-compose.selfhost.yml")]
_WF = str(REPO / ".forgejo/workflows/*.yml") + "," + str(REPO / ".github/workflows/*.yml")
WORKFLOWS = sorted(f for pat in _WF.split(",") for f in glob.glob(pat))

# OS/pytest keys, not Pry configuration.
_ENV_IGNORE = {"USER", "HOME", "PATH", "PYTEST_CURRENT_TEST", "HOSTNAME", "TZ"}
_OWN_NAMESPACES = ("PRY_", "OTEL_", "SILICONFLOW_", "OPENCODE_ZEN_")


def _compose(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args, "config", "-q"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "POSTGRES_PASSWORD": "readiness-probe",
            "GRAFANA_PASSWORD": "readiness-probe",
        },
        check=False,
    )


def _docker_available() -> bool:
    return subprocess.run(["which", "docker"], capture_output=True).returncode == 0

@pytest.mark.parametrize("compose_file", COMPOSE_FILES)
def test_compose_renders(compose_file: str) -> None:
    """`docker compose config` must accept every compose file we ship."""
    if not (REPO / compose_file).exists():
        pytest.skip(f"{compose_file} not present")
    if not _docker_available():
        pytest.skip("docker CLI unavailable")
    result = _compose(["-f", compose_file])
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.mark.parametrize(("base", "overlay"), COMPOSE_OVERLAYS)
def test_compose_overlay_renders_on_top_of_base(base: str, overlay: str) -> None:
    """Each overlay must merge cleanly over the production file."""
    if not _docker_available():
        pytest.skip("docker CLI unavailable")
    result = _compose(["-f", base, "-f", overlay])
    assert result.returncode == 0, result.stderr[-2000:]


def _source_env_keys() -> set[str]:
    pattern = re.compile(
        r"os\.(?:getenv|environ\.get)\(\s*[\"']([A-Z0-9_]+)[\"']"
        r"|os\.environ\[\s*[\"']([A-Z0-9_]+)[\"']\s*\]"
    )
    keys: set[str] = set()
    for path in (REPO / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(text):
            keys.add(match.group(1) or match.group(2))
    return keys


def _documented_keys() -> set[str]:
    keys: set[str] = set()
    for name in (".env.example", ".env.selfhost.example"):
        path = REPO / name
        if path.exists():
            keys |= set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]{2,})=", path.read_text(), re.M))
    return keys


def test_every_own_env_key_is_documented() -> None:
    """A var read in source but absent from .env.example is an outage waiting."""
    undocumented = {
        key
        for key in _source_env_keys() - _documented_keys() - _ENV_IGNORE
        if key.startswith(_OWN_NAMESPACES)
    }
    assert not undocumented, f"undocumented env keys: {sorted(undocumented)}"


def test_alembic_has_single_head() -> None:
    """`alembic upgrade head` is fatal with more than one head."""
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in (REPO / "alembic/versions").glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)", text, re.M)
        down = re.search(r"^down_revision(?::[^=]+)?\s*=\s*(.+)$", text, re.M)
        if rev:
            revisions.add(rev.group(1))
        if down:
            parents |= set(re.findall(r"[\"']([^\"']+)[\"']", down.group(1)))
    assert revisions, "no alembic revisions found"
    heads = sorted(revisions - parents)
    assert len(heads) == 1, f"expected exactly one head, found {heads}"


def test_health_and_ready_are_503_when_critical_dep_is_down() -> None:
    """/health and /ready must fail closed on a critical dependency."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pry.api.routers.core import health as health_module

    app = FastAPI()
    app.include_router(health_module.router)
    client = TestClient(app)

    async def up() -> bool:
        return True

    async def down() -> bool:
        return False

    health_module._check_database = up  # type: ignore[assignment]
    health_module._check_redis = up  # type: ignore[assignment]
    # /healthz is liveness: never dependency-gated.
    assert client.get("/healthz").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200

    health_module._check_database = down  # type: ignore[assignment]
    health_response = client.get("/health")
    assert health_response.status_code == 503
    assert health_response.json()["services"]["database"] == "down"
    assert client.get("/ready").status_code == 503


_CONTINUE_ON_ERROR = re.compile(r"continue-on-error:\s*true")
# A `|| true` only neutralises a gate when attached to the SCANNER call;
# `pip install ... || true` / `git fetch ... || true` are setup, not the gate.
_SCANNER = r"(semgrep|bandit|gitleaks|trivy|pip-audit|osv-scanner|trufflehog|guardian)"
_SOFT_SCANNER_FAIL = re.compile(rf"{_SCANNER}.*\|\|\s*(?:true|echo)")
_SECURITY_JOB = re.compile(
    r"^  (semgrep|security|secrets|trivy-scan|pip-audit|supply-chain|guardian):\s*$"
)
# Known, deliberate advisories; a NEW neutralisation still fails the test.
# Blocking gates: semgrep, gitleaks, bandit, pip-audit, OSV, trufflehog, guardian.
_KNOWN_ADVISORY = {"ci.yml:trivy-scan:continue-on-error"}


def _neutralisation_token(line: str, workflow: Path, job: str) -> str | None:
    if "if: always()" in line:
        return None  # artifact upload, not a gate
    if _CONTINUE_ON_ERROR.search(line):
        return f"{workflow.name}:{job}:continue-on-error"
    if _SOFT_SCANNER_FAIL.search(line):
        return f"{workflow.name}:{job}:soft-fail"
    return None


def test_no_security_gate_is_neutralised() -> None:
    """A blocking gate that swallows its own failure is decoration."""
    offenders: list[str] = []
    for workflow_name in WORKFLOWS:
        workflow = Path(workflow_name)
        current_job = None
        for number, line in enumerate(workflow.read_text().splitlines(), 1):
            job = _SECURITY_JOB.match(line)
            if job:
                current_job = job.group(1)
                continue
            if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
                current_job = None
                continue
            if not current_job:
                continue
            token = _neutralisation_token(line, workflow, current_job)
            if token and token not in _KNOWN_ADVISORY:
                offenders.append(f"{workflow.name}:{number} [{current_job}] {line.strip()}")
    assert not offenders, "neutralised security gate(s):\n" + "\n".join(offenders)

def test_every_ci_job_has_a_timeout() -> None:
    """An untimed job can pin a runner until the queue stalls."""
    missing = [
        f"{Path(workflow).name}::{job}"
        for workflow in WORKFLOWS
        for job, spec in (
            (yaml.safe_load(Path(workflow).read_text()) or {}).get("jobs") or {}
        ).items()
        if "timeout-minutes" not in (spec or {})
    ]
    assert not missing, f"CI jobs without timeout-minutes: {missing}"
