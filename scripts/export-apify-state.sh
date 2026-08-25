#!/usr/bin/env bash
# F46 — nightly Apify state export to Backblaze B2.
# Exports actor inventory + recent run stats as timestamped JSON, then
# rclone-copies to b2-crypt:rmi-data/pry-apify-state/ (copy, never sync).
# Fail-soft: missing token or network errors log and exit 0 — a monitoring
# gap must never page anyone at 3AM.
set -uo pipefail

LOG_TAG="[pry-apify-export]"
# Token arrives via APIFY_TOKEN env — injected by the scheduler from the
# secret store. Never hardcode or reference secret-store paths here:
# this file ships in a public repository.
TOKEN="${APIFY_TOKEN:-}"
OUT_ROOT="/srv/data/backups/pry-apify-state"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

if [ -z "$TOKEN" ]; then
    echo "$LOG_TAG $(date -u +%FT%TZ) no APIFY_TOKEN env — skipping — skipping"
    exit 0
fi

mkdir -p "$OUT_ROOT"

api() { # api <path> — GET the Apify API v2
    curl -sfm 30 -H "Authorization: Bearer $TOKEN" "https://api.apify.com/v2/$1" 2>/dev/null
}

# 1. Actor inventory (store + internal), trimmed to identity fields
if api "acts?limit=200" >/tmp/apify_actors.$$; then
    python3 - <<EOF
import json
raw = json.load(open('/tmp/apify_actors.$$'))
data = raw.get('data', {}).get('items', [])
slim = [{
    'id': a.get('id'), 'name': a.get('name'),
    'username': a.get('username'), 'title': a.get('title'),
    'modifiedAt': a.get('modifiedAt'),
} for a in data]
json.dump({'exported_at': '$(date -u +%FT%TZ)', 'count': len(slim), 'actors': slim},
          open('$OUT_ROOT/actors-$STAMP.json', 'w'), indent=1)
print(f"$LOG_TAG actors exported: {len(slim)}")
EOF
else
    echo "$LOG_TAG $(date -u +%FT%TZ) Apify API unreachable for acts — skipping runs"
fi

# 2. Recent runs across all actors (last 24h window is implicit in limit)
if api "runs?limit=100&desc=true" >/tmp/apify_runs.$$; then
    python3 - <<EOF
import json
raw = json.load(open('/tmp/apify_runs.$$'))
data = raw.get('data', {}).get('items', [])
slim = [{
    'id': r.get('id'), 'actId': r.get('actId'), 'status': r.get('status'),
    'startedAt': r.get('startedAt'), 'finishedAt': r.get('finishedAt'),
    'stats': r.get('stats', {}),
} for r in data]
json.dump({'exported_at': '$(date -u +%FT%TZ)', 'count': len(slim), 'runs': slim},
          open('$OUT_ROOT/runs-$STAMP.json', 'w'), indent=1)
print(f"$LOG_TAG runs exported: {len(slim)}")
EOF
fi

rm -f /tmp/apify_actors.$$ /tmp/apify_runs.$$

# 3. Ship to B2 (copy not sync — remote files are never deleted)
if compgen -G "$OUT_ROOT/*-$STAMP.json" >/dev/null; then
    if rclone copy "$OUT_ROOT" "b2-crypt:rmi-data/pry-apify-state/" --max-age 48h --quiet; then
        echo "$LOG_TAG $(date -u +%FT%TZ) shipped to b2-crypt:rmi-data/pry-apify-state/"
        # keep 60 local days, B2 retains per lifecycle rules
        find "$OUT_ROOT" -name '*.json' -mtime +60 -delete
    else
        echo "$LOG_TAG $(date -u +%FT%TZ) rclone ship FAILED — local copies retained"
        exit 0
    fi
fi
exit 0
