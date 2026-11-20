#!/usr/bin/env bash
# Time root-level test files in chunks. The root tests/ directory holds ~990
# files, so a per-directory measurement says nothing; this slices alphabetically
# and reports each chunk's wall time, which localises the slow set.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
CAP=${CAP:-180}

mapfile -t FILES < <(ls tests/test_*.py 2>/dev/null)
total=${#FILES[@]}
echo "root test files: $total"
CHUNK=${CHUNK:-100}
printf '%-16s %8s %8s %s\n' RANGE WALL_S FILES RESULT
for ((i = 0; i < total; i += CHUNK)); do
    slice=("${FILES[@]:i:CHUNK}")
    s=$(date +%s)
    out=$(timeout "$CAP" "$PY" -m pytest "${slice[@]}" -q --no-header \
        --timeout=15 --timeout-method=thread -p no:randomly 2>&1 | tail -1)
    e=$(date +%s)
    printf '%-16s %8s %8s %s\n' "$i-$((i + CHUNK - 1))" "$((e - s))" "${#slice[@]}" "$(echo "$out" | cut -c1-44)"
done
