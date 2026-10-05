# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Public-behavior tests for the guardian dangerous-diff gate.

Covers the split modules ``scripts/guardian_core.py`` (diff parse/load,
Finding) and ``scripts/guardian_scan.py`` (the five rule families) through
their public functions only — ``parse_diff``/``load_diff``/``Finding`` and
``scan``. No network, no git, deterministic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "scripts"


def _import(name: str):
    """Load a hyphen-free guardian module from scripts/ by file path."""
    module_name = name.replace("-", "_")
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


guardian_core = _import("guardian_core")
guardian_scan = _import("guardian_scan")


def _diff(*files: str) -> str:
    """Join per-file unified-diff fragments into one diff text."""
    return "".join(files)


def _delete_test_file(path: str = "tests/test_old.py") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"deleted file mode 100644\n"
        f"--- a/{path}\n"
        f"+++ /dev/null\n"
        f"@@ -1,3 +0,0 @@\n"
        f"-def test_gone():\n"
        f"-    assert True\n"
        f"-\n"
    )


def _remove_def_test(path: str = "tests/test_x.py") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,3 +1,3 @@\n"
        f" def test_keep():\n"
        f"-def test_removed():\n"
        f"-    pass\n"
        f"+    assert True\n"
    )


def _add_line(path: str, line: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,1 @@\n+{line}\n"


class TestGuardianCleanDiff:
    """A benign diff must produce no findings and exit 0."""

    def test_clean_diff_produces_no_findings(self):
        diff = _diff(
            "diff --git a/src/pry/example.py b/src/pry/example.py\n"
            "--- a/src/pry/example.py\n"
            "+++ b/src/pry/example.py\n"
            "@@ -1,2 +1,3 @@\n"
            " def existing():\n"
            "-    return 1\n"
            "+    return 2\n"
            "+    # a comment\n"
        )
        findings, stats = guardian_scan.scan(guardian_core.parse_diff(diff), 40, 1500, False)
        assert findings == []
        assert stats["files"] == 1

    def test_main_returns_zero_on_clean_diff(self, tmp_path):
        diff_file = tmp_path / "clean.diff"
        diff_file.write_text(
            "diff --git a/src/pry/example.py b/src/pry/example.py\n"
            "--- a/src/pry/example.py\n"
            "+++ b/src/pry/example.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        module = _import("check-guardian")
        assert module.main(["--diff", str(diff_file)]) == 0


class TestGuardianTestDeletion:
    """Rule 1: deleting tests without a compensating new test blocks."""

    def test_deleted_test_file_blocks(self):
        findings, stats = guardian_scan.scan(
            guardian_core.parse_diff(_delete_test_file()), 40, 1500, False
        )
        rules = [f.rule for f in findings]
        assert guardian_core.R_TEST_DELETION in rules
        blocking = [f for f in findings if f.blocking]
        assert blocking, "a deleted test file with no new test must block"
        # The deleted file and the `def test_gone` line inside it each count.
        assert stats["tests_removed"] == 2

    def test_removed_def_test_blocks(self):
        findings, stats = guardian_scan.scan(
            guardian_core.parse_diff(_remove_def_test()), 40, 1500, False
        )
        assert any(f.rule == guardian_core.R_TEST_DELETION and f.blocking for f in findings)
        assert stats["tests_removed"] == 1
        assert stats["tests_added"] == 0

    def test_removed_test_with_compensating_new_test_passes(self):
        diff = _diff(
            _remove_def_test(),
            "diff --git a/tests/test_x.py b/tests/test_x.py\n"
            "--- a/tests/test_x.py\n"
            "+++ b/tests/test_x.py\n"
            "@@ -10,1 +10,2 @@\n"
            "+def test_new():\n"
            "+    assert True\n",
        )
        findings, stats = guardian_scan.scan(guardian_core.parse_diff(diff), 40, 1500, False)
        assert stats["tests_added"] == 1
        assert not [f for f in findings if f.rule == guardian_core.R_TEST_DELETION]
