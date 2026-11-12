#!/usr/bin/env bash
# One-time setup of a GCP project for scripts/deploy.sh, safe to rerun: each step describes first
# and creates only what is missing, so a second run creates nothing and never overwrites a secret
# (the IAM grants re-add a binding that is already there, which leaves the policy unchanged).
#   PROJECT=<gcp-project-id> [REGION=europe-west1] [STATE_BUCKET=<PROJECT>-state] \
#     [DEPLOY_AS=<account that will run deploy.sh; default: you>] \
#     ANTHROPIC_API_KEY=... [ADMIN_PASSWORD=...] scripts/bootstrap.sh
# The secrets are the SECRETS list in scripts/deploy.sh. A value is read only when its secret is
# created; rotate one as docs/deploy.md says.
set -euo pipefail

: "${PROJECT:?set PROJECT to the GCP project id}"
REGION="${REGION:-europe-west1}"
STATE_BUCKET="${STATE_BUCKET:-$PROJECT-state}"
DEPLOY_AS="${DEPLOY_AS:-$(gcloud config get-value account)}"
SECRETS="$(sed -n 's/^SECRETS="\(.*\)"$/\1/p' "$(dirname "$0")/deploy.sh")"
: "${SECRETS:?no SECRETS= line in scripts/deploy.sh}"
GENERATED="admin-password"  # made up when created without a value; nobody has to type one
APIS="run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
  secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com iamcredentials.googleapis.com"
DEPLOYER="deployer@$PROJECT.iam.gserviceaccount.com"  # deploy.sh impersonates this account
P=(--project "$PROJECT")

found() { "$@" >/dev/null 2>&1; }  # a describe that succeeds: the resource is already there
grant() { "$@" --quiet >/dev/null; }  # an add-iam-policy-binding, without its policy dump

enabled="$(gcloud services list --enabled "${P[@]}" --format 'value(config.name)')"
missing="$(for api in $APIS; do grep -qx "$api" <<<"$enabled" || echo "$api"; done)"
if [[ -n "$missing" ]]; then
  # shellcheck disable=SC2086  # one API name per word
  gcloud services enable $missing "${P[@]}"
fi

# Cloud Run runs, and Cloud Build builds, as the default compute service account.
RUNTIME="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')"
RUNTIME="$RUNTIME-compute@developer.gserviceaccount.com"
grant gcloud projects add-iam-policy-binding "$PROJECT" --condition None \
  --member "serviceAccount:$RUNTIME" --role roles/run.builder

# The repository `gcloud run deploy --source` pushes images to.
found gcloud artifacts repositories describe cloud-run-source-deploy --location "$REGION" "${P[@]}" ||
  gcloud artifacts repositories create cloud-run-source-deploy --repository-format docker \
    --location "$REGION" "${P[@]}"

# The store's bucket: private, versioned, writable by the service.
if ! found gcloud storage buckets describe "gs://$STATE_BUCKET" "${P[@]}"; then
  gcloud storage buckets create "gs://$STATE_BUCKET" "${P[@]}" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
  gcloud storage buckets update "gs://$STATE_BUCKET" "${P[@]}" --versioning
fi
grant gcloud storage buckets add-iam-policy-binding "gs://$STATE_BUCKET" "${P[@]}" \
  --member "serviceAccount:$RUNTIME" --role roles/storage.objectUser

# Secrets: the value comes from the env var named after the secret (anthropic-api-key reads
# ANTHROPIC_API_KEY), printf so no trailing newline lands in it; a GENERATED one with no value
# gets a random one.
for secret in $SECRETS; do
  var="$(tr 'a-z-' 'A-Z_' <<<"$secret")"
  if ! found gcloud secrets describe "$secret" "${P[@]}"; then
    value="${!var:-}"
    if [[ -z "$value" && " $GENERATED " == *" $secret "* ]]; then
      value="$(openssl rand -hex 24)"
      echo "bootstrap: generated $secret; read it with" \
        "gcloud secrets versions access latest --secret $secret --project $PROJECT"
    fi
    if [[ -z "$value" ]]; then
      echo "bootstrap: secret $secret does not exist yet; rerun with $var set to its value" >&2
      exit 1
    fi
    printf '%s' "$value" | gcloud secrets create "$secret" --data-file=- "${P[@]}"
  fi
  grant gcloud secrets add-iam-policy-binding "$secret" "${P[@]}" \
    --member "serviceAccount:$RUNTIME" --role roles/secretmanager.secretAccessor
done

# The deployer: deploys from source and acts as the runtime account, nothing else. It also reads
# the admin password, which the live smoke at the end of deploy.sh logs in with.
found gcloud iam service-accounts describe "$DEPLOYER" "${P[@]}" ||
  gcloud iam service-accounts create deployer --display-name "scripts/deploy.sh" "${P[@]}"
# run.admin, not run.developer: --allow-unauthenticated sets the service's IAM policy, which
# run.developer cannot.
for role in roles/run.admin roles/run.sourceDeveloper roles/serviceusage.serviceUsageConsumer \
  roles/logging.viewer; do
  grant gcloud projects add-iam-policy-binding "$PROJECT" --condition None \
    --member "serviceAccount:$DEPLOYER" --role "$role"
done
grant gcloud iam service-accounts add-iam-policy-binding "$RUNTIME" "${P[@]}" \
  --member "serviceAccount:$DEPLOYER" --role roles/iam.serviceAccountUser
grant gcloud secrets add-iam-policy-binding admin-password "${P[@]}" \
  --member "serviceAccount:$DEPLOYER" --role roles/secretmanager.secretAccessor

# Whoever runs deploy.sh (a person, or the hub VM's service account) may impersonate the deployer.
case "$DEPLOY_AS" in
  *.gserviceaccount.com) member="serviceAccount:$DEPLOY_AS" ;;
  *) member="user:$DEPLOY_AS" ;;
esac
echo "bootstrap: $member may deploy as $DEPLOYER (roles/iam.serviceAccountTokenCreator)"
grant gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" "${P[@]}" \
  --member "$member" --role roles/iam.serviceAccountTokenCreator

echo "bootstrapped $PROJECT"
echo "new IAM grants take up to ~2 min: wait before the first deploy"
