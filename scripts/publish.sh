#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
#
# Build and publish the `pryscraper-mcp` PyPI distribution.
#
# Usage:
#   bash scripts/publish.sh            # full pre-publish checklist + build + upload
#   bash scripts/publish.sh --check    # run the pre-publish checklist only
#   bash scripts/publish.sh --build    # checklist + build, no upload
#   bash scripts/publish.sh --dry-run  # checklist + build + twine upload --repository testpypi
#
# In a parallel-agent working tree (multiple agents editing the same checkout),
# the git-clean gate below blocks every non-`all` mode. Set PRY_ALLOW_DIRTY=1
# to downgrade that gate from die -> warn for --check/--build/--dry-run. The
# production `all` mode still requires a clean tree (no bypass).
#
# PyPI token resolution (in order of precedence; NEVER hardcode the token):
#   1. PRY_PYPI_TOKEN env var
#   2. /root/.secrets/pypi_token            (documented location in gopass pry/pypi_note)
#   3. `gopass show pry/pypi_token`   (create after PyPI account activation)
#
# The token is passed to twine via stdin (`-p` reads from the prompt when stdin
# is a tty, so we pipe it) and is never echoed. Use `__token__` as the username
# (PyPI API-token auth).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${PRY_VENV:-$ROOT/.venv}"
PY="${VENV}/bin/python"

MODE="${1:-all}"
case "$MODE" in
--check)
    DO_CHECK=1
    DO_BUILD=0
    DO_UPLOAD=0
    ;;
--build)
    DO_CHECK=1
    DO_BUILD=1
    DO_UPLOAD=0
    ;;
--dry-run)
    DO_CHECK=1
    DO_BUILD=1
    DO_UPLOAD=1
    DRY_RUN=1
    ;;
all)
    DO_CHECK=1
    DO_BUILD=1
    DO_UPLOAD=1
    DRY_RUN=0
    ;;
*)
    echo "usage: $0 [--check|--build|--dry-run|all]" >&2
    exit 2
    ;;
esac

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die() {
    printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Pre-publish checklist
# ---------------------------------------------------------------------------
if [ "$DO_CHECK" = "1" ]; then
    say "Pre-publish checklist"

    say "git status / branch"
    if [ "${PRY_ALLOW_DIRTY:-0}" = "1" ] && [ "$DO_UPLOAD" != "1" ]; then
        git status --short | grep -q . && warn "working tree is not clean (PRY_ALLOW_DIRTY=1) — build only, not upload"
    else
        git status --short | grep -q . && die "working tree is not clean: run git status"
    fi
    [ "$(git branch --show-current)" = "main" ] || warn "not on main (current: $(git branch --show-current))"

    say "version consistency (pyproject.toml vs server.json)"
    PKG_VERSION="$("$PY" -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
    SERVER_VERSION="$("$PY" -c "import json;print(json.load(open('server.json'))['version'])")"
    [ "$PKG_VERSION" = "$SERVER_VERSION" ] ||
        warn "version mismatch: pyproject=$PKG_VERSION server.json=$SERVER_VERSION"

    say "MCP tool count consistency (server.json vs pry_mcp/tools.py)"
    SERVER_TOOLS="$("$PY" -c "import json;print(len(json.load(open('server.json'))['tools']))")"
    MCP_TOOLS="$("$PY" -c "from pry_mcp.tools import PRY_TOOLS;print(len(PRY_TOOLS))" 2>/dev/null ||
        "$PY" -c "import sys;sys.path.insert(0,'.');from pry_mcp.tools import PRY_TOOLS;print(len(PRY_TOOLS))")"
    [ "$SERVER_TOOLS" = "$MCP_TOOLS" ] ||
        warn "tool-count mismatch: server.json=$SERVER_TOOLS pry_mcp/tools.py=$MCP_TOOLS"

    say "gitleaks secret scan"
    if command -v gitleaks >/dev/null 2>&1; then
        gitleaks detect --no-git --exit-code 0 || warn "gitleaks reported findings (check output above)"
    else
        warn "gitleaks not installed — skipping (CI gate will catch)"
    fi

    say "ruff"
    if command -v ruff >/dev/null 2>&1 || [ -x "$VENV/bin/ruff" ]; then
        "${VENV}/bin/ruff" check . || die "ruff check failed"
    else
        warn "ruff not installed — skipping"
    fi

    say "tests (fast suite, excludes integration)"
    if [ -x "$VENV/bin/pytest" ]; then
        "$VENV/bin/pytest" -q -m "not integration" --ignore=tests/contract --disable-warnings ||
            die "pytest failed"
    else
        warn "pytest not installed in $VENV — skipping tests"
    fi

    echo "version bump reminder: current version is $PKG_VERSION"
    echo "  - bump [project] version + server.json version together (semver)"
    echo "  - add CHANGELOG entry"
fi

if [ "$DO_BUILD" != "1" ]; then
    say "checklist complete (--check mode, nothing built)"
    exit 0
fi

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
say "Installing build tooling if needed"
"$PY" -m pip install --quiet build twine

say "Building sdist + wheel"
rm -rf dist build
"$PY" -m build --sdist --wheel

say "Artifacts:"
ls -1 dist/

if [ "$DO_UPLOAD" != "1" ]; then
    say "build complete (--build mode, not uploaded)"
    exit 0
fi

# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
# Resolve token WITHOUT printing it.
TOKEN=""
if [ -n "${PRY_PYPI_TOKEN:-}" ]; then
    TOKEN="$PRY_PYPI_TOKEN"
elif [ -r /root/.secrets/pypi_token ]; then
    TOKEN="$(cat /root/.secrets/pypi_token)"
elif command -v gopass >/dev/null 2>&1 && gopass show pry/pypi_token >/dev/null 2>&1; then
    TOKEN="$(gopass show pry/pypi_token)"
fi

[ -n "$TOKEN" ] || die "no PyPI token found. Set PRY_PYPI_TOKEN, create /root/.secrets/pypi_token, or add gopass pry/pypi_token (see gopass pry/pypi_note for account setup)"

if [ "${DRY_RUN:-0}" = "1" ]; then
    REPO="--repository testpypi"
    say "DRY RUN: uploading to TestPyPI"
else
    REPO=""
    say "Uploading to PyPI (token from gopass/env — never echoed)"
fi

# shellcheck disable=SC2086 # $REPO is intentionally split (empty or "--repository testpypi")
printf '%s\n' "$TOKEN" | "$VENV/bin/twine" upload $REPO dist/* --username __token__ --password-stdin --non-interactive
say "done."
