# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Contract tests for scripts/backup-postgres.sh and compose wiring.

pg_dump / b2 are replaced with recording stubs: these tests prove the
contract (timestamped name, sha256 sidecar, rotation, non-zero exit on a
failed dump, off-host upload) without a live database or bucket.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import stat
import subprocess
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backup-postgres.sh"


def _stub(bindir: pathlib.Path, name: str, body: str) -> pathlib.Path:
    path = bindir / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(
        bindir,
        "pg_dump",
        'out=""; while [ $# -gt 0 ]; do case "$1" in --file) out="$2"; shift 2;; '
        '*) shift;; esac; done; [ -n "$out" ] || exit 2; printf "FAKE-DUMP" > "$out"\n',
    )
    backup_dir = tmp_path / "backups"
    return {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "PRY_DATABASE_URL": "postgresql://pry:pw@postgres:5432/pry",
        "PRY_BACKUP_DIR": str(backup_dir),
        "HOME": str(tmp_path),
    }


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_backup_writes_timestamped_dump_and_checksum(env):
    proc = _run(env)
    assert proc.returncode == 0, proc.stderr
    dumps = list(pathlib.Path(env["PRY_BACKUP_DIR"]).glob("pry-*.dump"))
    assert len(dumps) == 1, proc.stderr
    dump = dumps[0]
    assert dump.read_bytes() == b"FAKE-DUMP"
    sidecar = pathlib.Path(f"{dump}.sha256")
    assert sidecar.exists()
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    assert sidecar.read_text().split()[0] == digest


def test_failed_pg_dump_exits_nonzero_and_leaves_no_dump(env):
    bindir = pathlib.Path(env["PATH"].split(":")[0])
    _stub(bindir, "pg_dump", "exit 3\n")
    proc = _run(env)
    assert proc.returncode != 0
    assert "pg_dump failed" in proc.stderr
    assert list(pathlib.Path(env["PRY_BACKUP_DIR"]).glob("*")) == []


def test_rotation_removes_dumps_older_than_retention(env):
    backup_dir = pathlib.Path(env["PRY_BACKUP_DIR"])
    backup_dir.mkdir()
    old = backup_dir / "pry-20000101T000000Z.dump"
    old.write_bytes(b"old")
    old_sidecar = pathlib.Path(f"{old}.sha256")
    old_sidecar.write_text("deadbeef  pry-20000101T000000Z.dump\n")
    stale = time.time() - 40 * 86400
    os.utime(old, (stale, stale))
    os.utime(old_sidecar, (stale, stale))

    proc = _run(env)
    assert proc.returncode == 0, proc.stderr
    assert not old.exists()
    assert not old_sidecar.exists()
    assert len(list(backup_dir.glob("pry-*.dump"))) == 1


def test_b2_upload_when_configured(env, tmp_path):
    bindir = pathlib.Path(env["PATH"].split(":")[0])
    log = tmp_path / "b2.log"
    _stub(bindir, "b2", f'printf "%s\\n" "$*" >> {log}\nexit 0\n')
    env["B2_BUCKET"] = "pry-backups"
    env["B2_PREFIX"] = "pry/postgres"
    env["B2_CLI"] = str(bindir / "b2")

    proc = _run(env)
    assert proc.returncode == 0, proc.stderr
    lines = log.read_text().splitlines()
    assert len(lines) == 2
    assert all("pry-backups" in line and "pry/postgres/pry-" in line for line in lines)
    assert any(line.endswith(".sha256") for line in lines)


def test_b2_configured_without_client_fails_closed(env, tmp_path):
    # Coreutils only: the real host has both b2 and aws, so a restricted PATH
    # is the only faithful way to model "bucket configured, no client".
    farm = tmp_path / "tools"
    farm.mkdir()
    for tool in (
        "bash",
        "date",
        "mkdir",
        "find",
        "sha256sum",
        "du",
        "cut",
        "sed",
        "mv",
        "wc",
        "basename",
        "dirname",
        "rm",
        "cat",
    ):
        target = shutil.which(tool)
        assert target
        (farm / tool).symlink_to(target)
    env["B2_BUCKET"] = "pry-backups"
    env["PATH"] = f"{farm}:{env['PATH'].split(':')[0]}"
    proc = _run(env)
    assert proc.returncode != 0
    assert "no 'b2' or 'aws' client" in proc.stderr


def test_unsupported_dsn_rejected():
    proc = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        env={"PATH": os.environ["PATH"], "PRY_DATABASE_URL": "mysql://x/y"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "unsupported DSN" in proc.stderr


def test_restore_test_restores_and_counts_three_tables(env, tmp_path):
    bindir = pathlib.Path(env["PATH"].split(":")[0])
    _stub(bindir, "psql", 'case "$*" in *"count(*)"*) echo 42;; esac\nexit 0\n')
    _stub(bindir, "pg_restore", "exit 0\n")
    assert _run(env).returncode == 0  # make a dump first
    proc = _run(env, "--restore-test")
    assert proc.returncode == 0, proc.stderr
    for table in ("x402_payment_records", "usage", "scrape_jobs"):
        assert f"{table} count=42" in proc.stderr
    assert "restore test PASSED" in proc.stderr


def _compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def _env_list(service: dict) -> list[str]:
    raw = service.get("environment") or []
    if isinstance(raw, dict):
        return [f"{k}={v}" for k, v in raw.items()]
    return list(raw)


def test_compose_requires_pre_migration_backup_by_default():
    services = _compose()["services"]
    assert "PRY_REQUIRE_PRE_MIGRATION_BACKUP=1" in _env_list(services["pry"])


def test_compose_redis_is_noeviction():
    redis = _compose()["services"]["redis"]
    command = redis["command"]
    assert "--maxmemory-policy noeviction" in command
    assert "allkeys-lru" not in command


def test_compose_ships_retention_and_backup_ops_services():
    services = _compose()["services"]
    assert services["retention"]["profiles"] == ["ops"]
    assert "scripts/retention.py" in " ".join(services["retention"]["entrypoint"])
    assert services["backup"]["profiles"] == ["ops"]
    assert "scripts/backup-postgres.sh" in " ".join(services["backup"]["entrypoint"])
