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

import pytest

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


class TestGuardianProcessExecution:
    """Rule 3: newly added shell/exec calls block."""

    @pytest.mark.parametrize(
        "line",
        [
            "    subprocess.run(cmd, shell=True)",
            "    os.system('rm -rf /')",
            "    os.execvp('sh', ['sh'])",
            "    os.popen('cat file')",
        ],
        ids=["subprocess-shell", "os-system", "os-exec", "os-popen"],
    )
    def test_added_process_exec_blocks(self, line):
        findings, _ = guardian_scan.scan(
            guardian_core.parse_diff(_add_line("src/pry/example.py", line)), 40, 1500, False
        )
        assert any(f.rule == guardian_core.R_PROCESS_EXEC and f.blocking for f in findings)

    def test_docstring_mention_does_not_block(self):
        """Rule text quoted in a docstring is policy, not an executed call.

        Real docstrings open the triple quote on its own line, which is what
        DocTracker's state machine recognises; the policy text inside the
        block is then skipped.
        """
        diff = (
            "diff --git a/src/pry/example.py b/src/pry/example.py\n"
            "--- a/src/pry/example.py\n"
            "+++ b/src/pry/example.py\n"
            "@@ -0,0 +1,4 @@\n"
            '+"""Guard policy: never use os.system(cmd).\n'
            "+\n"
            '+"""\n'
            "+VALUE = 1\n"
        )
        findings, _ = guardian_scan.scan(guardian_core.parse_diff(diff), 40, 1500, False)
        assert not [f for f in findings if f.rule == guardian_core.R_PROCESS_EXEC]

    def test_same_line_triple_quote_is_not_a_docstring_block(self):
        """A line that opens and closes quotes on itself is not tracked.

        Documented behavior: DocTracker toggles per line, so an even number of
        quotes leaves it out of-triple, and a line with no comment lead is
        treated as code. This pins that contract so it cannot drift silently.
        """
        diff = _add_line("src/pry/example.py", '"""one liner os.system(cmd)."""')
        findings, _ = guardian_scan.scan(guardian_core.parse_diff(diff), 40, 1500, False)
        assert any(f.rule == guardian_core.R_PROCESS_EXEC for f in findings)


class TestGuardianEvalDynamic:
    """Rule 4: dynamic eval/exec in non-test source blocks."""

    @pytest.mark.parametrize(
        "line",
        ["    return eval(user_input)", "    exec(code_string)"],
        ids=["eval", "exec"],
    )
    def test_added_eval_in_source_blocks(self, line):
        findings, _ = guardian_scan.scan(
            guardian_core.parse_diff(_add_line("src/pry/example.py", line)), 40, 1500, False
        )
        assert any(f.rule == guardian_core.R_EVAL_DYNAMIC and f.blocking for f in findings)

    def test_eval_in_test_file_is_not_blocked(self):
        findings, _ = guardian_scan.scan(
            guardian_core.parse_diff(_add_line("tests/test_example.py", "    x = eval('1 + 1')")),
            40,
            1500,
            False,
        )
        assert not [f for f in findings if f.rule == guardian_core.R_EVAL_DYNAMIC]


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
