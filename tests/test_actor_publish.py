# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for batch Apify publication (actor_factory.publish).

Covers staging completeness (everything the generated Dockerfile COPYs must
exist in the staged dir), per-actor failure isolation, push retry semantics,
and resume behaviour — the upload itself is always mocked; no network.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from actor_factory import publish
from actor_factory.presets import ALL_PRESETS
from actor_factory.publish import (
    ENGINE_FILES,
    PushResult,
    load_results,
    push_actor,
    run_batch,
    sorted_specs,
    stage_actor,
)

REPO = Path(publish.__file__).resolve().parents[1]


# ── staging ──────────────────────────────────────────────────────────────────


class TestStageActor:
    def test_staged_package_is_complete(self, tmp_path: Path) -> None:
        spec = ALL_PRESETS["pry-cve-advisory-watch"]
        stage = stage_actor(spec, REPO, tmp_path)
        assert (stage / ".actor" / "actor.json").is_file()
        assert (stage / ".actor" / "INPUT_SCHEMA.json").is_file()
        assert (stage / ".actor" / "Dockerfile").is_file()
        assert (stage / ".actor" / "icon.svg").is_file()
        assert (stage / "src" / "main.py").is_file()
        for name in ENGINE_FILES:
            assert (stage / name).is_file(), f"missing engine file {name}"
        assert (stage / "actor_factory" / "generator.py").is_file()

    def test_actor_json_carries_preset_identity(self, tmp_path: Path) -> None:
        spec = ALL_PRESETS["pry-cve-advisory-watch"]
        stage = stage_actor(spec, REPO, tmp_path)
        actor_json = json.loads((stage / ".actor" / "actor.json").read_text())
        assert actor_json["name"] == spec.name.removeprefix("pry-")
        assert actor_json["title"] == spec.title

    def test_restaging_replaces_previous_output(self, tmp_path: Path) -> None:
        spec = ALL_PRESETS["pry-cve-advisory-watch"]
        stage = stage_actor(spec, REPO, tmp_path)
        stale = stage / "requirements.lock"
        stale.write_text("stale-content")
        stage_actor(spec, REPO, tmp_path)  # re-stage must not keep stale bytes
        assert stale.read_text() != "stale-content"

    def test_missing_engine_file_raises(self, tmp_path: Path) -> None:
        spec = ALL_PRESETS["pry-cve-advisory-watch"]
        empty_root = tmp_path / "empty-repo"
        empty_root.mkdir()
        with pytest.raises(FileNotFoundError, match="engine file missing"):
            stage_actor(spec, empty_root, tmp_path / "staging")

    def test_staged_lock_is_curated_runtime_set(self, tmp_path: Path) -> None:
        """Actor images ship ONLY runtime pins - the full repo lock carries
        dev/test deps (pact, pandas) that conflict on the platform builder,
        and git+ssh editables that cannot resolve without SSH keys."""
        staged_lock = tmp_path / "pry-cve-advisory-watch" / "requirements.lock"
        if not staged_lock.exists():  # stage on demand for hermetic run
            spec = ALL_PRESETS["pry-cve-advisory-watch"]
            stage_actor(spec, REPO, tmp_path)
        content = staged_lock.read_text()
        assert "git+ssh://" not in content
        assert "-e " not in content
        assert "pact" not in content
        assert "pandas" not in content
        assert "pytest" not in content
        for pkg in ("httpx==", "pydantic==", "trafilatura=="):
            assert pkg in content, f"runtime pin missing: {pkg}"

    def test_actor_lock_contents_unit(self, tmp_path: Path) -> None:
        repo_lock = tmp_path / "repo.lock"
        repo_lock.write_text(
            "# comment\n"
            "httpx==0.28.1\n"
            "pytest==8.0.0\n"
            "-e git+ssh://git@git.example.com/repo.git@abc#egg=pry\n"
            "pydantic==2.13.4\n"
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(publish, "ACTOR_RUNTIME_PACKAGES", ("httpx", "pydantic"))
            out = publish._actor_lock_contents(repo_lock)
        assert "httpx==0.28.1" in out
        assert "pydantic==2.13.4" in out
        assert "pytest" not in out
        assert "git+ssh" not in out

    def test_actor_lock_missing_package_raises(self, tmp_path: Path) -> None:
        repo_lock = tmp_path / "repo.lock"
        repo_lock.write_text("httpx==0.28.1\n")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(publish, "ACTOR_RUNTIME_PACKAGES", ("httpx", "some-missing-pkg"))
            with pytest.raises(ValueError, match="some-missing-pkg"):
                publish._actor_lock_contents(repo_lock)

    def test_every_preset_stages_clean(self, tmp_path: Path) -> None:
        """Full-catalog gate: every preset produces a valid staged package."""
        staged = [stage_actor(spec, REPO, tmp_path) for spec in sorted_specs()]
        assert len(staged) == len(ALL_PRESETS)
        for stage in staged:
            assert (stage / ".actor" / "actor.json").is_file()


# ── selection ────────────────────────────────────────────────────────────────


class TestSortedSpecs:
    def test_sorted_by_name(self) -> None:
        names = [s.name for s in sorted_specs()]
        assert names == sorted(names)

    def test_only_filter(self) -> None:
        specs = sorted_specs(only=["pry-cve-advisory-watch", "pry-recipe-miner"])
        assert [s.name for s in specs] == ["pry-cve-advisory-watch", "pry-recipe-miner"]

    def test_unknown_preset_raises(self) -> None:
        with pytest.raises(KeyError, match="no-such-actor"):
            sorted_specs(only=["no-such-actor"])


# ── push execution (mocked CLI) ──────────────────────────────────────────────


class TestPushActor:
    def test_invokes_cli_with_dir_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[Any] = []

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="pushed", stderr="")

        monkeypatch.setattr(publish.subprocess, "run", fake_run)
        ok, detail = push_actor(tmp_path)
        assert ok
        assert detail == "pushed"
        argv, _kwargs = calls[0]
        assert argv[0].endswith("npx")
        assert argv[1:5] == ["--yes", "apify-cli", "push", "--force"]
        assert "--dir" in argv
        assert str(tmp_path) in argv

    def test_retries_then_reports_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts: list[list[str]] = []

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            attempts.append(argv)
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

        monkeypatch.setattr(publish.subprocess, "run", fake_run)
        monkeypatch.setattr(publish.time, "sleep", lambda _: None)
        ok, detail = push_actor(tmp_path)
        assert not ok
        assert "boom" in detail
        assert len(attempts) == publish.PUSH_RETRIES

    def test_timeout_counts_as_failed_attempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(1)
            raise subprocess.TimeoutExpired(cmd="apify", timeout=1)

        monkeypatch.setattr(publish.subprocess, "run", fake_run)
        monkeypatch.setattr(publish.time, "sleep", lambda _: None)
        ok, detail = push_actor(tmp_path)
        assert not ok
        assert "timed out" in detail
        assert len(calls) == publish.PUSH_RETRIES


class TestCheckAuth:
    def test_ok_when_cli_reports_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 0, stdout="username: cryptorugmunch\n")

        monkeypatch.setattr(publish.subprocess, "run", fake_run)
        ok, detail = publish.check_auth()
        assert ok
        assert "cryptorugmunch" in detail

    def test_fails_when_not_logged_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="not logged in")

        monkeypatch.setattr(publish.subprocess, "run", fake_run)
        ok, detail = publish.check_auth()
        assert not ok
        assert "apify login" in detail


# ── batch orchestration ──────────────────────────────────────────────────────


class TestRunBatch:
    @staticmethod
    def _ok_push(stage: Path, actor_id: str | None = None) -> tuple[bool, str]:
        return True, "pushed"

    def test_dry_run_yields_all_without_results_file(self, tmp_path: Path) -> None:
        results = list(
            run_batch(REPO, tmp_path, only=["pry-recipe-miner"], dry_run=True, delay_seconds=0)
        )
        assert [r.ok for r in results] == [True]
        assert results[0].detail == "dry-run"
        assert not load_results(tmp_path)  # dry-run never records pushes

    def test_results_persisted_incrementally(self, tmp_path: Path) -> None:
        names = ["pry-cve-advisory-watch", "pry-recipe-miner"]
        out = list(
            run_batch(
                REPO,
                tmp_path,
                only=names,
                push_fn=self._ok_push,
                delay_seconds=0,
            )
        )
        assert all(r.ok for r in out)
        saved = load_results(tmp_path)
        assert set(saved) == set(names)

    def test_stage_failure_isolated_not_fatal(self, tmp_path: Path) -> None:
        # empty repo root -> every stage fails, but batch yields per-actor results
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        out = list(
            run_batch(
                empty_root,
                tmp_path / "staging",
                only=["pry-recipe-miner"],
                push_fn=self._ok_push,
                delay_seconds=0,
            )
        )
        assert len(out) == 1
        assert not out[0].ok
        assert "engine file missing" in out[0].detail

    def test_resume_skips_already_pushed(self, tmp_path: Path) -> None:
        pushed_with: list[str] = []

        def tracking_push(stage: Path, actor_id: str | None = None) -> tuple[bool, str]:
            pushed_with.append(stage.name)
            return True, "pushed"

        first = PushResult(name="pry-cve-advisory-watch", ok=True, detail="pushed")
        (tmp_path / "results.json").write_text(
            json.dumps({first.name: {"ok": True, "detail": "pushed"}}) + "\n"
        )
        out = list(
            run_batch(
                REPO,
                tmp_path,
                only=["pry-cve-advisory-watch", "pry-recipe-miner"],
                resume=True,
                push_fn=tracking_push,
                delay_seconds=0,
            )
        )
        assert pushed_with == ["pry-recipe-miner"]  # cve skipped via results.json
        assert len(out) == 1

    def test_failed_push_is_recorded_for_retry(self, tmp_path: Path) -> None:
        def failing_push(stage: Path, actor_id: str | None = None) -> tuple[bool, str]:
            return False, "platform 500"

        out = list(
            run_batch(
                REPO,
                tmp_path,
                only=["pry-recipe-miner"],
                push_fn=failing_push,
                delay_seconds=0,
            )
        )
        assert not out[0].ok
        saved = load_results(tmp_path)
        assert saved["pry-recipe-miner"].ok is False
        # resume does NOT skip a failed entry - it retries it
        retried = list(
            run_batch(
                REPO,
                tmp_path,
                only=["pry-recipe-miner"],
                resume=True,
                push_fn=self._ok_push,
                delay_seconds=0,
            )
        )
        assert retried[0].ok

    def test_auth_failure_aborts_before_any_push(self, tmp_path: Path) -> None:
        pushed: list[str] = []

        def deny_auth() -> tuple[bool, str]:
            return False, "not logged in"

        def tracking_push(stage: Path, actor_id: str | None = None) -> tuple[bool, str]:
            pushed.append(stage.name)
            return True, "pushed"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(publish, "check_auth", deny_auth)  # type: ignore[arg-type]
            mp.setattr(publish, "push_actor", tracking_push)  # type: ignore[arg-type]
            with pytest.raises(RuntimeError, match="not logged in"):
                list(
                    run_batch(
                        REPO,
                        tmp_path,
                        only=["pry-recipe-miner"],
                        delay_seconds=0,
                    )
                )
        assert pushed == []  # nothing staged-pushed when auth fails

    def test_custom_push_fn_skips_auth_probe(self, tmp_path: Path) -> None:
        out = list(
            run_batch(
                REPO,
                tmp_path,
                only=["pry-recipe-miner"],
                push_fn=self._ok_push,
                delay_seconds=0,
            )
        )
        assert out[0].ok


# ── F44: staged-package secret scan (defense in depth) ──────────────────────


class TestStagedSecretScan:
    def test_clean_stage_passes(self, tmp_path: Path) -> None:
        spec = ALL_PRESETS["pry-cve-advisory-watch"]
        stage = stage_actor(spec, REPO, tmp_path)  # must not raise
        assert stage.is_dir()

    def test_planted_secret_blocks_staging(self, tmp_path: Path) -> None:
        """A leaked AWS key in engine files must refuse to stage."""
        spec = ALL_PRESETS["pry-cve-advisory-watch"]
        # ENGINE_DIRS copies src/pry + actor_factory into the stage — plant
        # inside a file that actually ships.
        planted = REPO / "actor_factory" / "generator.py"
        original = planted.read_text()
        # ghp_ + exactly 36 alphanumerics matches gitleaks' GitHub PAT rule
        # (the classic AKIAIOSFODNN7EXAMPLE key is excluded as a doc example)
        token = "ghp_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        planted.write_text(original + f'\nTOKEN = "{token}"\n')
        try:
            with pytest.raises(ValueError, match="secret scan"):
                stage_actor(spec, REPO, tmp_path)
        finally:
            planted.write_text(original)

    def test_scan_helper_signature(self, tmp_path: Path) -> None:
        """Sanity: helper returns (bool, str) even for an empty dir."""
        clean, report = publish.scan_staged_for_secrets(tmp_path, REPO)
        assert isinstance(clean, bool)
        assert isinstance(report, str)
