#!/usr/bin/env bash
# Put API keys in Secret Manager from env vars, never echoing a value, and let Cloud Run read them.
#   PROJECT=<gcp-project-id> XAI_API_KEY=... scripts/secrets.sh XAI_API_KEY [PARALLEL_API_KEY ...]
# Type keys with `! read -rs XAI_API_KEY && export XAI_API_KEY` so they never reach a file or history.
# Each VAR becomes secret var-name (XAI_API_KEY is xai-api-key); SURREALDB_URL is stored as
# surreal-url because the app reads SURREAL_URL. Creates the secret, or adds a version if it exists.
# scripts/deploy.sh mounts every listed key whose secret exists; redeploy to pick up a new one.
set -euo pipefail
set +x  # a value must never be traced

: "${PROJECT:?set PROJECT to the GCP project id}"
[[ $# -gt 0 ]] || { echo "usage: PROJECT=... VAR=value $0 VAR [VAR ...]" >&2; exit 2; }
P=(--project "$PROJECT")
RUNTIME="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')-compute@developer.gserviceaccount.com"

for var in "$@"; do
  [[ "$var" =~ ^[A-Z][A-Z0-9_]*$ ]] || { echo "secrets: $var is not an env var name" >&2; exit 2; }
  if [[ -z "${!var:-}" ]]; then
    echo "secrets: $var is empty or unset; skipped" >&2
    continue
  fi
  name="${var/#SURREALDB_/SURREAL_}"
  id="$(tr 'A-Z_' 'a-z-' <<<"$name")"
  # printf to stdin: the value is never an argument (ps would show it) and gets no trailing newline.
  if gcloud secrets describe "$id" "${P[@]}" >/dev/null 2>&1; then
    printf '%s' "${!var}" | gcloud secrets versions add "$id" --data-file=- "${P[@]}" >/dev/null
    echo "secrets: $id new version"
  else
    printf '%s' "${!var}" | gcloud secrets create "$id" --data-file=- "${P[@]}" >/dev/null
    echo "secrets: $id created"
  fi
  gcloud secrets add-iam-policy-binding "$id" "${P[@]}" --member "serviceAccount:$RUNTIME" \
    --role roles/secretmanager.secretAccessor --quiet >/dev/null
done
