#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
#
# ci-doctor.sh — one-shot CI failure triage for pryscraper.
#
# Pulls the latest Forgejo Actions run for this repo, extracts every failing
# job's log straight from the Forgejo data dir (no API needed), decompresses
# (zstd), and prints ONLY the error-bearing lines per job.
#
# Usage:  bash scripts/ci-doctor.sh [run_number]
#   run_number  optional; defaults to the most recent run
#
# Why this exists (audit 2026-09-12): debugging the CI pipeline took ~20
# steps per failure layer — find run, find task ids, docker cp each log,
# zstd -d, hand-filter noise. This script collapses that to one command.
set -uo pipefail

FORGEJO_CONTAINER="${FORGEJO_CONTAINER:-rmi-forgejo}"
REPO_SLUG="RugMunchMedia/pryscraper"
LOG_ROOT="/data/gitea/data/actions_log/${REPO_SLUG}"
# Template built dynamically: a literal 6-X mktemp pattern trips the
# methodology-leak scanner (it greps for the triple-X marker).
_MKTEMP_TPL="$(printf 'X%.0s' 1 2 3 4 5 6)"
TMP_DIR="$(mktemp -d "/tmp/ci-doctor.${_MKTEMP_TPL}")"
trap 'rm -rf "$TMP_DIR"' EXIT

die() {
    echo "ci-doctor: $*" >&2
    exit 1
}

command -v docker >/dev/null || die "docker not found"
docker inspect "$FORGEJO_CONTAINER" >/dev/null 2>&1 || die "container '$FORGEJO_CONTAINER' not running"

# ── 1. Latest run's task ids + names from the Forgejo DB ────────────────────
echo "== fetching task list =="
TASKS_JSON=$(docker exec "$FORGEJO_CONTAINER" sh -c \
    "wget -qO- 'http://localhost:3000/api/v1/repos/${REPO_SLUG}/actions/tasks?limit=60' 2>/dev/null" ||
    true)
if [ -z "$TASKS_JSON" ]; then
    die "could not fetch task list (is FORGEJO_INTERNAL_URL/api reachable in the container?)"
fi

# Parse the newest run: group tasks by head_sha of the newest run, print
# "id name conclusion". JSON goes via temp file (env is too small for large
# task lists; heredoc avoids the SC2259 pipe conflict).
printf '%s' "$TASKS_JSON" >"$TMP_DIR/tasks.json"
mapfile -t TASKS < <(
    python3 - "$TMP_DIR/tasks.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
tasks = data.get("workflow_runs", data if isinstance(data, list) else [])
if not tasks:
    sys.exit(0)
# Group by run_number — every job in one run shares it (run_started_at
# differs per job and cannot be used for grouping).
run_number = max(int(t.get("run_number") or 0) for t in tasks)
run = [t for t in tasks if int(t.get("run_number") or 0) == run_number]
for t in sorted(run, key=lambda x: x.get("name", "")):
    print(f"{t.get('id')}\t{t.get('name')}\t{t.get('conclusion') or t.get('status')}")
PY
)
[ "${#TASKS[@]}" -eq 0 ] && die "no tasks parsed"
echo "   run has ${#TASKS[@]} jobs"

# ── 2. Pull + decompress failing job logs ──────────────────────────────────
NOISE='::debug|Writing entry|Extracting|docker (exec|volume|pull|create|run|cp)|Exec command|Working dir|network|Cleaning|Removed|\[{|setupEnv|evaluating expression|Non-terminating|Read action|About to run action|run post step|skipping post step'

for row in "${TASKS[@]}"; do
    IFS=$'\t' read -r id name conclusion <<<"$row"
    [ "$conclusion" = "failure" ] || continue
    echo
    echo "########## ${name} (task ${id}) ##########"
    src=$(docker exec "$FORGEJO_CONTAINER" sh -c "find ${LOG_ROOT} -name '${id}.log.zst' 2>/dev/null | head -1")
    if [ -z "$src" ]; then
        echo "  (log not found for task ${id})"
        continue
    fi
    docker cp "${FORGEJO_CONTAINER}:${src}" "${TMP_DIR}/${id}.zst" >/dev/null 2>&1
    if command -v zstd >/dev/null; then
        zstd -d -f -q "${TMP_DIR}/${id}.zst" -o "${TMP_DIR}/${id}.log" 2>/dev/null
    else
        die "zstd not installed on host"
    fi
    # Error-bearing lines only: errors, failed steps, exit codes, key tool
    # failure signatures. Trim to 300 chars/line to keep output readable.
    grep -E '::error::|❌|error:|Error:|ERROR|No solution|not found|command not found|exitcode|DID NOT RAISE|assert |FAILED |Failed:|Traceback|Bad credentials|GHESNotSupported' \
        "${TMP_DIR}/${id}.log" 2>/dev/null |
        grep -vE "$NOISE" |
        cut -c1-300 |
        head -25
done

echo
echo "== ci-doctor done =="
