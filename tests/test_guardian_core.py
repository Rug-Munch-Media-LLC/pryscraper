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


class TestGuardianScopeCreep:
    """Rule 5: > max_files (40) is reported; strict escalates to blocking."""

    @staticmethod
    def _many_file_diff(count: int) -> str:
        return _diff(
            *(
                f"diff --git a/src/pry/m{i}.py b/src/pry/m{i}.py\n"
                f"--- a/src/pry/m{i}.py\n"
                f"+++ b/src/pry/m{i}.py\n"
                f"@@ -0,0 +1,1 @@\n"
                f"+x = {i}\n"
                for i in range(count)
            )
        )

    def test_over_40_files_reported_as_warning(self):
        findings, stats = guardian_scan.scan(
            guardian_core.parse_diff(self._many_file_diff(41)), 40, 1500, False
        )
        creep = [f for f in findings if f.rule == guardian_core.R_SCOPE_CREEP]
        assert creep, "41 files must trip scope_creep"
        assert creep[0].blocking is False, "scope_creep is WARN by default"
        assert stats["files"] == 41

    def test_over_40_files_blocks_under_strict(self):
        findings, _ = guardian_scan.scan(
            guardian_core.parse_diff(self._many_file_diff(41)), 40, 1500, True
        )
        creep = [f for f in findings if f.rule == guardian_core.R_SCOPE_CREEP]
        assert creep, "41 files must trip scope_creep"
        assert creep[0].blocking is True


class TestGuardianCiModification:
    """Rule 2: CI edits WARN; escalate to BLOCK when tests are deleted too."""

    def _ci_diff(self) -> str:
        return _add_line(".forgejo/workflows/ci.yml", "  continue-on-error: true")

    def test_ci_edit_alone_is_warning(self):
        findings, _ = guardian_scan.scan(guardian_core.parse_diff(self._ci_diff()), 40, 1500, False)
        ci = [f for f in findings if f.rule == guardian_core.R_CI_MODIFICATION]
        assert ci, "CI edit must be reported"
        assert ci[0].blocking is False

    def test_ci_edit_plus_test_deletion_blocks(self):
        diff = _diff(self._ci_diff(), _delete_test_file())
        findings, _ = guardian_scan.scan(guardian_core.parse_diff(diff), 40, 1500, False)
        ci = [f for f in findings if f.rule == guardian_core.R_CI_MODIFICATION]
        assert ci, "CI edit must be reported"
        assert ci[0].blocking is True
        assert "tests deleted" in ci[0].detail


class TestGuardianCoreMechanics:
    """Direct unit coverage of the parsed diff and Finding render."""

    def test_parse_diff_tracks_added_and_removed_lines(self):
        files = guardian_core.parse_diff(_remove_def_test("tests/test_x.py"))
        assert len(files) == 1
        record = files[0]
        assert record["path"] == "tests/test_x.py"
        assert record["deleted"] is False
        added_texts = [t for _n, t in record["added"]]
        assert "    assert True" in added_texts
        removed_texts = [t for _n, t in record["removed"]]
        assert any(t.startswith("def test_removed") for t in removed_texts)

    def test_parse_diff_marks_whole_file_deletion(self):
        files = guardian_core.parse_diff(_delete_test_file("tests/test_gone.py"))
        assert files[0]["deleted"] is True
        assert files[0]["path"] == "tests/test_gone.py"

    def test_load_diff_missing_file_is_unmeasured(self, tmp_path):
        assert guardian_core.load_diff(str(tmp_path / "nope.diff")) is None

    def test_finding_render_flags_block_and_warn(self):
        block = guardian_core.Finding("r", "a.py", 3, "why", True)
        warn = guardian_core.Finding("r", "a.py", 3, "why", False)
        assert block.render().startswith("[BLOCK]")
        assert warn.render().startswith("[WARN ]")
        assert "a.py:3" in block.render()

    def test_main_unmeasured_diff_returns_two(self, tmp_path):
        module = _import("check-guardian")
        assert module.main(["--diff", str(tmp_path / "absent.diff")]) == 2


class TestGuardianDocTracker:
    """DocTracker is public behavior used by the scan rules."""

    def test_comment_line_is_documentation(self):
        tracker = guardian_core.DocTracker()
        assert tracker.consume("# os.system(x)") is True

    def test_triple_quoted_block_toggles_state(self):
        tracker = guardian_core.DocTracker()
        assert tracker.consume('"""open') is True
        assert tracker.consume("still inside os.system(y)") is True
        assert tracker.consume('"""close') is True
        assert tracker.consume("real = os.system(z)") is False
