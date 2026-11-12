#!/usr/bin/env bash
# scripts/secrets.sh against a fake gcloud: the value reaches gcloud on stdin only, never argv or
# output; a new secret is created, an existing one gets a version; SURREALDB_ maps to surreal-.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/gcloud" <<'EOF'
#!/usr/bin/env bash
echo "ARGV $*" >>"$LOG"
[[ "$1 $2" == "projects describe" ]] && { echo 123; exit 0; }
[[ "$1 $2" == "secrets describe" ]] && { [[ "$3" == xai-api-key ]]; exit; }
[[ " $* " == *" --data-file=- "* ]] && echo "STDIN $(cat)" >>"$LOG"
exit 0
EOF
chmod +x "$tmp/gcloud"
export LOG="$tmp/log"
out="$(PATH="$tmp:$PATH" PROJECT=p XAI_API_KEY=sek-xai SURREALDB_URL=sek-url PARALLEL_API_KEY= \
  bash "$here/secrets.sh" XAI_API_KEY SURREALDB_URL PARALLEL_API_KEY 2>&1)"

fail() { echo "FAIL: $1"; echo "$out"; cat "$LOG"; exit 1; }
grep -q 'ARGV secrets versions add xai-api-key' "$LOG" || fail "existing secret gets a version"
grep -q 'ARGV secrets create surreal-url' "$LOG" || fail "SURREALDB_URL creates surreal-url"
grep -q 'STDIN sek-xai' "$LOG" && grep -q 'STDIN sek-url' "$LOG" || fail "values go on stdin"
grep 'ARGV' "$LOG" | grep -q 'sek-' && fail "a value reached argv"
grep -q 'sek-' <<<"$out" && fail "a value was printed"
grep -q 'PARALLEL_API_KEY is empty or unset; skipped' <<<"$out" || fail "empty var is skipped"
grep -q 'member serviceAccount:123-compute@developer.gserviceaccount.com' "$LOG" ||
  fail "runtime account is granted"
echo "test_secrets: ok"
