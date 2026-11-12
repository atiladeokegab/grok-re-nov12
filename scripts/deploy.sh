#!/usr/bin/env bash
# Deploy the committed HEAD to Cloud Run and prove it answers.
#   PROJECT=<gcp-project-id> [REGION=europe-west1] [SERVICE=hackathon-starter] \
#     [STATE_BUCKET=<PROJECT>-state] [MIN_INSTANCES=0] [DEPLOY_AS_SELF=1] scripts/deploy.sh
# One-time GCP setup: scripts/bootstrap.sh. Rollback: docs/deploy.md.
set -euo pipefail

: "${PROJECT:?set PROJECT to the GCP project id}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-hackathon-starter}"
STATE_BUCKET="${STATE_BUCKET:-$PROJECT-state}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"  # the event playbook sets 1 on demo day: no cold start
# The one list of secrets: each mounts as its upper-cased name (anthropic-api-key is
# ANTHROPIC_API_KEY), and scripts/bootstrap.sh creates and grants exactly these.
SECRETS="anthropic-api-key admin-password"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "deploy: the working tree is dirty; commit first so the commit label names what ships" >&2
  exit 1
fi
COMMIT="$(git rev-parse --short=12 HEAD)"

# Every gcloud call below runs as the deployer scripts/bootstrap.sh made, never as you: its roles
# bound what a deploy can change. DEPLOY_AS_SELF=1 is the one opt-out, said out loud.
unset CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT  # only this script decides who deploys
if [[ "${DEPLOY_AS_SELF:-}" == 1 ]]; then
  echo "deploy: deploying as $(gcloud config get-value account), not the deployer"
else
  DEPLOYER="deployer@$PROJECT.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$DEPLOYER" --project "$PROJECT" >/dev/null 2>&1; then
    echo "deploy: no $DEPLOYER, or you cannot see it; run \`make bootstrap\` once for $PROJECT (scripts/bootstrap.sh)" >&2
    exit 1
  fi
  export CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT="$DEPLOYER"
fi
MOUNTS="$(for s in $SECRETS; do printf '%s=%s:latest,' "$(tr 'a-z-' 'A-Z_' <<<"$s")" "$s"; done)"

# State is one JSON object in GCS written with compare-and-swap (GcsStore), so it survives a
# redeploy and instances share it.
# ponytail: --max-instances 3 because GcsStore holds a few writes a second; raise it only with a
# sharded store.
gcloud run deploy "$SERVICE" --source . --region "$REGION" --project "$PROJECT" \
  --allow-unauthenticated \
  --set-secrets "${MOUNTS%,}" \
  --set-env-vars "MODE=cloud,DATA_PATH=gs://$STATE_BUCKET/store.json" \
  --labels "commit=$COMMIT" \
  --min-instances "$MIN_INSTANCES" \
  --max-instances 3 \
  --quiet

RELEASE="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format 'value(status.url,status.latestReadyRevisionName)')"
URL="${RELEASE%%$'\t'*}"
# The release record, one line: what is live, by commit, revision and URL. hub live forwards it.
echo "release: commit=$COMMIT revision=${RELEASE#*$'\t'} url=$URL"
curl -fsS --max-time 30 "$URL/health"
echo

# The live smoke: every GET answers below 500 and a request without the token is refused, on the
# real service (the tests marked live, tests/test_openapi_sweep.py).
# A plain assignment, so a failed read stops the deploy here instead of smoking with no password.
ADMIN_PASSWORD="$(gcloud secrets versions access latest --secret admin-password --project "$PROJECT")"
BASE_URL="$URL" ADMIN_PASSWORD="$ADMIN_PASSWORD" timeout 300 uv run pytest -q -m live -p no:cacheprovider
