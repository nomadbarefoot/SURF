#!/bin/bash
set -euo pipefail

BASE="${SURF_BASE_URL:-http://127.0.0.1:17777}"
AUTH_ARGS=()
if [ -n "${SURF_API_TOKEN:-}" ]; then
  AUTH_ARGS=(-H "Authorization: Bearer ${SURF_API_TOKEN}")
fi

SESSION_RESP=$(curl -s -X POST "$BASE/sessions/" "${AUTH_ARGS[@]}" -H "Content-Type: application/json" -d '{"config":{"profile_id":"test-sites","persist_profile":true}}')
SESSION=$(echo "$SESSION_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['session_id'])")
echo "Session: $SESSION"

sites=(
  "https://www.gov.tv"
  "https://www.llv.li"
  "https://www.gouv.mc"
)

for url in "${sites[@]}"; do
  echo "Testing $url"
  curl -s -X POST "$BASE/browser/navigate" "${AUTH_ARGS[@]}" -H "Content-Type: application/json" \
    -d "{\"session_id\":\"$SESSION\",\"url\":\"$url\",\"wait_until\":\"domcontentloaded\",\"timeout\":45000}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success'), d.get('data',{}).get('status'), d.get('data',{}).get('title'))"
done

curl -s -X DELETE "$BASE/sessions/$SESSION" "${AUTH_ARGS[@]}" > /dev/null
echo "Done"
