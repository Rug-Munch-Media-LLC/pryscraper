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
        ["    return ev" + "al(user_input)", "    ex" + "ec(code_string)"],
        ids=["eval", "exec"],
    )
    def test_added_eval_in_source_blocks(self, line):
        findings, _ = guardian_scan.scan(
            guardian_core.parse_diff(_add_line("src/pry/example.py", line)), 40, 1500, False
        )
        assert any(f.rule == guardian_core.R_EVAL_DYNAMIC and f.blocking for f in findings)

    def test_eval_in_test_file_is_not_blocked(self):
        findings, _ = guardian_scan.scan(
            guardian_core.parse_diff(
                _add_line("tests/test_example.py", "    x = ev" + "al('1 + 1')")
            ),
            40,
            1500,
            False,
        )
        assert not [f for f in findings if f.rule == guardian_core.R_EVAL_DYNAMIC]
