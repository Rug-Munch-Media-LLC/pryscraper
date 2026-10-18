#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
#
# smoke-wheel.sh — prove the BUILT WHEEL is installable and complete.
#
# Regression guard for the 2026-10-18 P0: with `where = ["src"]` the wheel
# shipped zero files for the seven root-level runtime packages, so the installed
# `pry serve` and `pry-mcp` binaries died on ModuleNotFoundError. Building from
# the source tree hides this (imports resolve against the repo), therefore every
# check here runs against the wheel installed in a clean venv from a non-repo
# working directory.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

REQUIRED=(pry pry_mcp extraction compliance site_catalog datasets actor_factory crypto_market)

echo "== build wheel"
"$PY" -m pip wheel "$REPO_ROOT" -w "$WORK/dist" --no-deps -q
WHEEL="$(find "$WORK/dist" -maxdepth 1 -name '*.whl' -print -quit)"
[ -n "$WHEEL" ] || {
    echo "FAIL: no wheel built" >&2
    exit 1
}

echo "== assert wheel membership"
"$PY" - "$WHEEL" "${REQUIRED[@]}" <<'PY'
import sys
import zipfile

wheel, required = sys.argv[1], sys.argv[2:]
names = zipfile.ZipFile(wheel).namelist()
failed = False
for package in required:
    members = [n for n in names if n == f"{package}/" or n.startswith(f"{package}/")]
    print(f"  {package:16s} {len(members):5d}")
    if not members:
        print(f"FAIL: zero members for required package {package!r}", file=sys.stderr)
        failed = True
tests = [n for n in names if n.startswith("tests/")]
if tests:
    print(f"FAIL: {len(tests)} test file(s) shipped in the wheel", file=sys.stderr)
    failed = True
if failed:
    sys.exit(1)
print(f"  wheel members: {len(names)}; tests: 0")
PY

echo "== install into a clean venv"
# --system-site-packages supplies the runtime dependency set; the wheel itself is
# installed --no-deps so this check measures packaging, not dependency solving.
"$PY" -m venv --system-site-packages "$WORK/venv"
"$WORK/venv/bin/python" -m pip install --no-deps --force-reinstall "$WHEEL" -q

echo "== entry points and imports (from a non-repo cwd)"
cd "$WORK"
"$WORK/venv/bin/pry" --help >/dev/null
"$WORK/venv/bin/pry-mcp" --help >/dev/null
"$WORK/venv/bin/python" -c \
    "import pry, pry_mcp, extraction, compliance, site_catalog, datasets, actor_factory, crypto_market"
echo "smoke-wheel: PASS"
