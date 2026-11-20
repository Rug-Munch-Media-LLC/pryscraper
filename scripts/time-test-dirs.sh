#!/usr/bin/env bash
# Time each top-level test directory separately, so the slow set is measured
# rather than guessed. A directory that hits the cap is reported, not hidden.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
CAP=${CAP:-240}

printf '%-42s %8s %8s\n' DIR WALL_S RESULT
for d in tests/*/; do
    [ -d "$d" ] || continue
    s=$(date +%s)
    out=$(timeout "$CAP" "$PY" -m pytest "$d" -q --no-header \
        --timeout=15 --timeout-method=thread -p no:randomly 2>&1 | tail -1)
    e=$(date +%s)
    wall=$((e - s))
    printf '%-42s %8s %s\n' "$d" "$wall" "$(echo "$out" | cut -c1-40)"
done
