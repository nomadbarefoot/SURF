#!/bin/bash
set -euo pipefail

BASE="${SURF_BASE_URL:-http://127.0.0.1:17777}"
AUTH_ARGS=()
if [ -n "${SURF_API_TOKEN:-}" ]; then
  AUTH_ARGS=(-H "Authorization: Bearer ${SURF_API_TOKEN}")
fi

SESSION_RESP=$(curl -s -X POST "$BASE/sessions/" "${AUTH_ARGS[@]}" -H "Content-Type: application/json" -d '{"config":{"profile_id":"test-browse","persist_profile":true}}')
SESSION=$(echo "$SESSION_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['session_id'])")
echo "Session: $SESSION"

curl -s -X POST "$BASE/browser/navigate" "${AUTH_ARGS[@]}" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION\",\"url\":\"https://example.com\",\"wait_until\":\"domcontentloaded\",\"timeout\":30000}" | python3 -m json.tool

curl -s -X POST "$BASE/browser/observe" "${AUTH_ARGS[@]}" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION\",\"max_text_length\":1000,\"max_items\":20}" | python3 -m json.tool

curl -s -X DELETE "$BASE/sessions/$SESSION" "${AUTH_ARGS[@]}" | python3 -m json.tool
