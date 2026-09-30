#!/usr/bin/env bash
# shellcheck disable=SC2119,SC2120
# (helpers intentionally take optional args)
# ci-gate-selftest.sh — prove the cost/quality gates ACTUALLY catch violations.
#
# Builds a throwaway fixture repo and injects one violation at a time. Every
# injection MUST make its gate exit 1; a clean fixture MUST exit 0. Any
# mismatch exits non-zero, which fails the CI quality job.
#
# Covered assertions:
#   (i)   501-line file                -> structure gate exits 1
#   (ii)  >200 non-allowlisted file    -> structure gate exits 1
#   (iii) allowlist-growth case        -> structure gate exits 1
#   (iv)  +1 monkeypatch occurrence    -> monkeypatch gate exits 1
#   (v)   phantom package-discovery    -> discovery gate exits 1
#   (vi)  omitted real package         -> discovery gate exits 1
#   (0)   clean fixture                -> every gate exits 0
#
# Usage: bash scripts/ci-gate-selftest.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Works both when synced into <repo>/scripts/ and when run from the canonical
# fleet/gates/ directory: the gates always sit next to this script.
STRUCT="$SCRIPT_DIR/check-structure.py"
MONKEY="$SCRIPT_DIR/check-monkeypatch.py"
DISCOVERY="$SCRIPT_DIR/check-package-discovery.py"

PY="${PYTHON:-python3}"
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PY="$REPO_ROOT/.venv/bin/python"
fi

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

fails=0
pass() { printf '  ok    %s\n' "$1"; }
fail() {
    printf '  FAIL  %s (rc=%s)\n' "$1" "${2:-?}"
    fails=$((fails + 1))
}

reset_fixture() {
    rm -rf "$FIXTURE"
    mkdir -p "$FIXTURE/src/rugbrain" "$FIXTURE/scripts"
    printf 'x = 1\n' >"$FIXTURE/src/rugbrain/small.py"
}

# discovery_fixture <include-list-toml> — a src-layout fixture whose
# packages.find include list is the given array body.
discovery_fixture() {
    rm -rf "$FIXTURE"
    mkdir -p "$FIXTURE/src/rugbrain/nested" "$FIXTURE/scripts"
    printf 'x = 1\n' >"$FIXTURE/src/rugbrain/small.py"
    printf 'y = 2\n' >"$FIXTURE/src/rugbrain/nested/deep.py"
    : >"$FIXTURE/src/rugbrain/__init__.py"
    : >"$FIXTURE/src/rugbrain/nested/__init__.py"
    {
        printf '[tool.setuptools.packages.find]\n'
        printf 'where = ["src"]\n'
        printf 'include = [%s]\n' "$1"
    } >"$FIXTURE/pyproject.toml"
}

# gen <n> <file> — write exactly n lines.
gen() {
    local n="$1" f="$2" i=0
    : >"$f"
    while [ "$i" -lt "$n" ]; do
        printf '# line\n' >>"$f"
        i=$((i + 1))
    done
}

struct_rc() {
    "$PY" "$STRUCT" --repo "$FIXTURE" "$@" >/dev/null 2>&1
    echo $?
}
monkey_rc() {
    "$PY" "$MONKEY" --repo "$FIXTURE" >/dev/null 2>&1
    echo $?
}
discovery_rc() {
    "$PY" "$DISCOVERY" --repo "$FIXTURE" >/dev/null 2>&1
    echo $?
}

expect_rc() { # expect_rc <want> <actual> <label>
    if [ "$2" -eq "$1" ]; then
        pass "$3"
    else
        fail "$3" "$2"
    fi
}

echo "gate-selftest: clean fixture must PASS (exit 0)"
# Both gates now FAIL CLOSED (exit 2) on an absent baseline, because an unreadable
# baseline previously made them report PASS — which is exactly the false confidence
# this selftest exists to prevent. So a "clean" fixture must actually carry the
# baselines; without them the expected code is 2, not 0.
reset_fixture
expect_rc 0 "$(struct_rc)" "clean fixture (structure)"
reset_fixture
printf '{"total": 0, "files": {}}' >"$FIXTURE/scripts/monkeypatch-baseline.json"
expect_rc 0 "$(monkey_rc)" "clean fixture (monkeypatch)"
reset_fixture
expect_rc 2 "$(monkey_rc)" "absent baseline -> exit 2 (cannot measure)"

echo "gate-selftest: injected violations must FAIL (exit 1)"
reset_fixture
gen 501 "$FIXTURE/src/rugbrain/god.py"
expect_rc 1 "$(struct_rc)" "501-line file -> exit 1"

reset_fixture
gen 201 "$FIXTURE/src/rugbrain/over.py"
expect_rc 1 "$(struct_rc)" "201-line non-allowlisted -> exit 1"

reset_fixture
printf '{"files": {"src/rugbrain/growth.py": 205}}' >"$FIXTURE/scripts/structure-baseline.json"
gen 260 "$FIXTURE/src/rugbrain/growth.py"
expect_rc 1 "$(struct_rc)" "allowlist growth -> exit 1"

reset_fixture
printf '{"total": 0, "files": {}}' >"$FIXTURE/scripts/monkeypatch-baseline.json"
printf 'import monkeypatch as monkeypatch\nmonkeypatch.setattr(x, "y", z)\n' \
    >"$FIXTURE/src/rugbrain/mp.py"
expect_rc 1 "$(monkey_rc)" "+1 monkeypatch -> exit 1"

discovery_fixture '"rugbrain*"'
expect_rc 0 "$(discovery_rc)" "clean include list (package discovery)"
discovery_fixture '"rugbrain*", "does_not_exist*"'
expect_rc 1 "$(discovery_rc)" "phantom include pattern -> exit 1"
discovery_fixture '"rugbrain.nested*"'
expect_rc 1 "$(discovery_rc)" "omitted real package -> exit 1"

if [ "$fails" -ne 0 ]; then
    echo "gate-selftest: FAIL ($fails assertion(s) did not match)"
    exit 1
fi
echo "gate-selftest: PASS — every gate catches its violation class"
exit 0
