# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""--breakdown is reporting only: same verdict, same exit code, same baseline."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / "scripts" / "check-antipatterns.py"

SRC_HANDLER = """
import logging

log = logging.getLogger(__name__)


def guarded(x):
    try:
        return do(x)
    except ValueError:
        return None, "failed"


def swallowed(x):
    try:
        return do(x)
    except ValueError:
        pass


def rethrows(x):
    try:
        return do(x)
    except ValueError:
        raise
"""

TEST_MONKEY = """
def test_patch(monkeypatch):
    monkeypatch.setattr("os.getcwd", lambda: "/tmp")
    assert True
"""


@pytest.fixture
def frozen_repo(tmp_path):
    """A tiny repo whose findings are known exactly, so nothing drifts."""
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "handlers.py").write_text(SRC_HANDLER)
    # The monkeypatch fixture belongs under src/, NOT tests/. is_production_path
    # exempts anything in a tests/ dir or named test_*, because monkeypatch in a
    # test is the correct tool for stubbing and 1254 of 1291 findings were test
    # fixtures. Placing it in tests/ therefore made this fixture invisible and the
    # assertion below wrong. The rule targets shipped code that rewrites its own
    # dependencies at import time, so the fixture must live where that applies.
    (tmp_path / "src" / "pkg" / "hooks.py").write_text(TEST_MONKEY)
    baseline = tmp_path / "scripts" / "antipattern-baseline.json"
    baseline.parent.mkdir(parents=True)
    # A deliberately tight baseline so the gate fails, and we can compare the
    # failing set with and without the flag.
    baseline.write_text(json.dumps({"rules": {"monkeypatch": 0, "bare-except": 0}, "total": 0}))
    return tmp_path


def _load(name, filename):
    """Import a module from scripts/ by path (the gate's filename has a dash).

    The triage modules import each other by bare name, so scripts/ goes on the
    path for the duration of the import, exactly as the gate's --breakdown does.
    """
    sys.path.insert(0, str(GATE.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, GATE.parent / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(GATE.parent))
    return module


@pytest.fixture(scope="module")
def modules():
    return (
        _load("antipattern_handlers", "antipattern_handlers.py"),
        _load("antipattern_breakdown", "antipattern_breakdown.py"),
        _load("check_antipatterns", "check-antipatterns.py"),
    )


def _run(repo, *flags):
    """Invoke the real gate CLI against the frozen repo."""
    proc = subprocess.run(  # noqa: S603 - fixed argv: this interpreter, this script
        [sys.executable, str(GATE), "--repo", str(repo), *flags],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc


def _failing_rules(stdout):
    """The rule names the gate reported as growing past the baseline."""
    tail = stdout.split("FAIL (antipattern ratchet):", 1)
    if len(tail) == 1:
        return []
    return sorted(
        line.strip().lstrip("- ").split(":", 1)[0]
        for line in tail[1].strip().splitlines()
        if line.strip().startswith("- ")
    )


def test_breakdown_matches_gate_counts_exactly(modules, frozen_repo):
    """Every per-rule total in the report equals the gate's own count."""
    _handlers, breakdown, gate = modules
    data = breakdown.scan(frozen_repo, gate)
    assert breakdown.reconcile(data, gate.scan(frozen_repo)) == []


def test_breakdown_places_findings_by_zone(modules, frozen_repo):
    """The fixture's monkeypatch is in src/, so it lands in the src zone.

    It used to sit in tests/, where is_production_path exempts it entirely —
    which is correct policy (monkeypatch in a test is the right tool for
    stubbing) but made this fixture unable to exercise the rule at all.
    """
    _handlers, breakdown, gate = modules
    data = breakdown.scan(frozen_repo, gate)
    assert data["monkeypatch"]["src"]["n"] == 1
    assert data["monkeypatch"]["tests"]["n"] == 0
    assert data["monkeypatch"]["other"]["n"] == 0


def test_breakdown_separates_failure_return_from_silence(modules, frozen_repo):
    """`return None, "failed"` is handling; `pass` is a silent fallthrough."""
    handlers_mod, breakdown, gate = modules
    handlers = breakdown.scan(frozen_repo, gate)["bare-except"]["src"]
    assert handlers["n"] == 2
    assert handlers[handlers_mod.EXPLICIT] == 1
    assert handlers[handlers_mod.SILENT] == 1


def test_flag_does_not_change_verdict_or_exit_code(frozen_repo):
    """Same exit code and same failing set with and without --breakdown."""
    plain, with_flag = _run(frozen_repo), _run(frozen_repo, "--breakdown")
    assert plain.returncode == 1
    assert with_flag.returncode == plain.returncode
    assert _failing_rules(with_flag.stdout) == _failing_rules(plain.stdout)
    assert _failing_rules(plain.stdout) == ["bare-except", "monkeypatch"]


def test_flag_does_not_touch_the_baseline_file(frozen_repo):
    """A reporting flag must leave the shrink-only baseline byte-identical."""
    baseline = frozen_repo / "scripts" / "antipattern-baseline.json"
    before = hashlib.sha256(baseline.read_bytes()).hexdigest()
    _run(frozen_repo, "--breakdown")
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == before


def test_flag_prints_the_report_and_its_own_disclaimer(frozen_repo):
    """The report shows up on stdout and says the verdict is unchanged."""
    stdout = _run(frozen_repo, "--breakdown").stdout
    assert "REPORTING ONLY" in stdout
    assert "reconciles with gate counts: yes" in stdout
    assert "explicit-failure-return" in stdout
    assert "silent-fallthrough" in stdout


def test_flag_never_runs_alongside_update_baseline(frozen_repo):
    """--update-baseline stays the only writer; --breakdown adds no output."""
    plain = _run(frozen_repo).stdout
    assert "REPORTING ONLY" not in plain
    combined = _run(frozen_repo, "--update-baseline", "--breakdown").stdout
    assert "REPORTING ONLY" not in combined
