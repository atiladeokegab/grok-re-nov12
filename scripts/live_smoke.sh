#!/usr/bin/env bash
# Live smoke of a deployed X-ray service: one PASS/FAIL line per check, non-zero exit on any FAIL.
#   scripts/live_smoke.sh https://xray-<n>.europe-west1.run.app
#   [PROJECT=hackathon-starter-ao] [REGION=europe-west1] [SERVICE=<from the URL>]
#   [EXPECT_COMMIT=<12-char sha; default origin/main>] [LISTING=demo]
# Reads the admin password from Secret Manager as deployer@ (as deploy.sh does; the VM account has
# no access of its own); it and every token stay out of argv and output.
set -uo pipefail
set +x

URL="${1:?usage: $0 URL}"; URL="${URL%/}"
PROJECT="${PROJECT:-hackathon-starter-ao}"
REGION="${REGION:-europe-west1}"
host="${URL#https://}"
case "$host" in  # xray-<hash>-ew.a.run.app, or xray-<project number>.europe-west1.run.app
  *.a.run.app) SERVICE="${SERVICE:-${host%-*-*.a.run.app}}" ;;
  *) SERVICE="${SERVICE:-${host%-*.*.run.app}}" ;;
esac
LISTING="${LISTING:-demo}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
failed=0
pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; failed=1; }
get() { curl -fsS --max-time 30 "$@"; }

# 1. /health answers ok, and the service's commit label is origin/main.
if health="$(get "$URL/health")" && jq -e '.status == "ok"' <<<"$health" >/dev/null; then
  pass "health: $(jq -c '{mode, providers, narrator}' <<<"$health")"
else
  fail "health: ${health:-no answer}"
fi
if [[ -z "${EXPECT_COMMIT:-}" ]]; then
  timeout 60 git fetch -q origin main 2>/dev/null
  EXPECT_COMMIT="$(git rev-parse --short=12 origin/main)"
fi
label="$(timeout 120 gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format 'value(metadata.labels.commit)' 2>/dev/null)"
if [[ -n "$label" && "$label" == "$EXPECT_COMMIT" ]]; then
  pass "commit label: $SERVICE commit=$label matches"
else
  fail "commit label: $SERVICE commit=${label:-?}, expected $EXPECT_COMMIT (origin/main unless EXPECT_COMMIT)"
fi

# 2. An offline X-ray of the demo listing finishes with a score and a finding citing a source URL.
run_id="$(jq -nc --arg l "$LISTING" '{listing_id: $l, offline: true}' |
  get -X POST -H 'content-type: application/json' --data @- "$URL/api/xray" | jq -r '.run_id // empty')"
status=""
if [[ -n "$run_id" ]]; then
  for _ in $(seq 60); do
    get "$URL/api/xray/$run_id" >"$tmp/report.json" 2>/dev/null &&
      status="$(jq -r .status "$tmp/report.json")"
    [[ "$status" == running || -z "$status" ]] || break
    sleep 2
  done
fi
# A finding has a source URL when one of its evidence ids names evidence with source_url.
if [[ "$status" == done ]] && jq -e '
    (.trust_score | type == "number") and
    ([.evidence[] | select(.source_url) | .id] as $src
     | any(.findings[]; any(.evidence_ids[]; . as $e | $src | index($e))))' \
    "$tmp/report.json" >/dev/null; then
  pass "xray: $run_id $(jq -c '{trust_score, counts}' "$tmp/report.json")"
else
  fail "xray: run=${run_id:-none} status=${status:-none} $(jq -c '{trust_score, error, n: (.findings | length)}' "$tmp/report.json" 2>/dev/null)"
fi

# 3. The run's SSE stream ends with a done event.
if [[ -n "$run_id" ]] &&
  curl -sSN --max-time 60 "$URL/api/xray/$run_id/events" 2>/dev/null | grep -qm1 '^event: done'; then
  pass "sse: event done"
else
  fail "sse: no done event for ${run_id:-no run}"
fi

# 4. /mcp: log in, mint an MCP token, initialize, and tools/list names the three X-ray tools.
tools=""; why=""
if pw="$(timeout 120 gcloud secrets versions access latest --secret admin-password \
  --project "$PROJECT" --impersonate-service-account "deployer@$PROJECT.iam.gserviceaccount.com" \
  2>/dev/null)" && [[ -n "$pw" ]]; then
  session="$(printf '%s' "$pw" | jq -Rc '{password: .}' |
    get -X POST -H 'content-type: application/json' --data @- "$URL/api/login" | jq -r '.token // empty')"
  mcp_token="$(get -X POST -H @<(printf 'Authorization: Bearer %s' "$session") "$URL/api/mcp/token" |
    jq -r '.token // empty')"
  [[ -n "$mcp_token" ]] || why="login or /api/mcp/token refused"
  unset pw session
  mcp() {  # one JSON-RPC call; the answer may be plain JSON or one SSE data line
    get -X POST -H @<(printf 'Authorization: Bearer %s' "$mcp_token") \
      -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
      --data "$1" "$URL/mcp" | sed -n 's/^data: //; /^{/p'
  }
  init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18",
    "capabilities":{},"clientInfo":{"name":"live-smoke","version":"1"}}}'
  if [[ -n "$mcp_token" ]] && mcp "$init" | jq -e '.result.serverInfo' >/dev/null; then
    tools="$(mcp '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | jq -r '.result.tools[].name')"
  fi
else
  why="cannot read the admin-password secret"
fi
missing="$(for t in xray_listing explain_finding get_place_graph; do
  grep -qx "$t" <<<"$tools" || echo "$t"; done)"
if [[ -n "$tools" && -z "$missing" ]]; then
  pass "mcp: initialize + tools/list ($(wc -l <<<"$tools") tools, all three X-ray tools)"
else
  got="${tools:+$(wc -l <<<"$tools") tools: $(tr '\n' ' ' <<<"$tools")}"
  fail "mcp: missing ${missing//$'\n'/ } (got ${got:-no tools list}${why:+: $why})"
fi

exit "$failed"
