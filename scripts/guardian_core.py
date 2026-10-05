#!/usr/bin/env python3
"""guardian_core.py — shared mechanism for the guardian dangerous-diff gate.

Split out of check-guardian.py to honour the ≤200-line cap. Holds the diff
parser, the diff loader, the rule constants/regexes and the Finding type.
check-guardian.py holds the policy (the scan() rules and the CLI verdict).

See check-guardian.py for the full policy statement and why gate config must
be read from the base branch.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Rule identifiers — stable strings; CI logs and reviewers key off these.
R_TEST_DELETION = "test_deletion"
R_CI_MODIFICATION = "ci_modification"
R_PROCESS_EXEC = "process_execution"
R_EVAL_DYNAMIC = "eval_dynamic"
R_SCOPE_CREEP = "scope_creep"

TEST_PATH_ANY_RE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$")
DEF_TEST_RE = re.compile(r"^\s*(async\s+)?def\s+test_")
CI_PATH_RE = re.compile(r"^(\.forgejo|\.github)/workflows/")

# Added lines only — a removal of `os.system(` is a fix, not a risk.
PROCESS_EXEC_RE = re.compile(
    r"subprocess\.[A-Za-z_]*\([^)]*shell\s*=\s*True"
    r"|os\.system\s*\("
    r"|os\.exec[a-z]*\s*\("
    r"|os\.popen\s*\("
)
EVAL_RE = re.compile(r"\b(eval|exec)\s*\(")

# Documentation guards: a rule string inside a comment or docstring is policy
# text, not an executed call. Without this, the gate flags its own rule
# documentation. State is tracked per file so a triple-quoted block (which may
# span lines and contain `=` prose) is excluded deterministically.
_DOC_LEAD_RE = re.compile(r"^\s*(#|//|--|\*|-|\||>)")


class DocTracker:
    """Per-file docstring/comment state for a diff's added lines.

    A line is documentation when it is a comment/bullet-led line, or when it
    lies inside a triple-quoted string opened earlier in the same file hunk
    stream. Real call lines (`x = os.system(cmd)`) are neither, so the exec/eval
    rules stay fail-closed on executable code.
    """

    __slots__ = ("_in_triple",)

    def __init__(self):
        self._in_triple = False

    def consume(self, line: str) -> bool:
        """Return True if `line` is documentation; update docstring state."""
        triples = line.count('"""') + line.count("'''")
        if self._in_triple:
            if triples % 2 == 1:  # this line closes the block
                self._in_triple = False
            return True
        if triples % 2 == 1:  # this line opens an unclosed block
            self._in_triple = True
            return True
        return bool(_DOC_LEAD_RE.match(line))


class Finding:
    """One rule hit. `blocking` decides the exit code; WARNs never gate."""

    __slots__ = ("blocking", "detail", "lineno", "path", "rule")

    def __init__(self, rule, path, lineno, detail, blocking):
        self.rule = rule
        self.path = path
        self.lineno = lineno
        self.detail = detail
        self.blocking = blocking

    def render(self) -> str:
        loc = f"{self.path}:{self.lineno}" if self.lineno else self.path
        tag = "BLOCK" if self.blocking else "WARN "
        return f"[{tag}] {self.rule}: {loc} — {self.detail}"


def _strip_prefix(path: str) -> str:
    """git diff shows `a/foo` and `b/foo`; keep the repo-relative path."""
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def parse_diff(text: str):
    """Split a unified diff into per-file records.

    Returns a list of dicts: path, added (list of (lineno, text)), removed
    (list of (lineno, text)), deleted (bool). lineno is the number shown in
    the hunk header / side, best-effort.
    """
    files = []
    current = None
    pending_old = None  # path from the `--- a/...` line, used for deletions
    new_line = old_line = 0
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            current = None
            pending_old = None
            continue
        if raw.startswith("--- "):
            pending_old = _strip_prefix(raw[4:].strip())
            continue
        if raw.startswith("+++ "):
            path = _strip_prefix(raw[4:].strip())
            if path == "/dev/null":
                # Whole-file deletion: the `+++` is /dev/null, so the real path
                # is the one from the preceding `--- a/...` line.
                if pending_old and pending_old != "/dev/null":
                    current = {
                        "path": pending_old,
                        "added": [],
                        "removed": [],
                        "deleted": True,
                    }
                    files.append(current)
                else:
                    current = None
                continue
            current = {"path": path, "added": [], "removed": [], "deleted": False}
            files.append(current)
            continue
        if current is None:
            continue
        if raw.startswith("deleted file mode"):
            current["deleted"] = True
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            if m:
                new_line = int(m.group(1))
            m2 = re.search(r"-(\d+)(?:,(\d+))?", raw)
            if m2:
                old_line = int(m2.group(1))
            continue
        if raw.startswith(("+++", "---")):
            continue
        if raw.startswith("+"):
            current["added"].append((new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-"):
            current["removed"].append((old_line, raw[1:]))
            old_line += 1
        elif raw.startswith(" "):
            new_line += 1
            old_line += 1
    return files


def load_diff(diff_file):
    """Read the diff from a file, or from `git diff --cached` by default.

    Returns the diff text, or None when it could not be read (the caller must
    treat None as 'unmeasured' and fail closed, never fail open).
    """
    if diff_file:
        p = Path(diff_file)
        # /dev/null is the documented "clean" sentinel.
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8", errors="replace")
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--no-color", "--no-ext-diff"],  # noqa: S607 - git is resolved from PATH by design
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return out.stdout
