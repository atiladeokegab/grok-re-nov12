# Deploying X-ray tonight

Project `hackathon-starter-ao`, region `europe-west1`, service `xray`. The project is already
bootstrapped (APIs, `deployer@` account, `hackathon-starter-ao-state` bucket, `admin-password`),
so no `make bootstrap` is needed. Deploys run from `main` only, by Zeus (day spec).

## Keys (optional, any subset)

The app runs with none of them. Each one that exists in Secret Manager is mounted on the next
deploy as its env var. Type a key without it touching a file or shell history, then store it:

```bash
! read -rs XAI_API_KEY && export XAI_API_KEY
PROJECT=hackathon-starter-ao scripts/secrets.sh XAI_API_KEY
```

| Env var | Secret |
|---|---|
| `XAI_API_KEY` | `xai-api-key` |
| `ANTHROPIC_API_KEY` | `anthropic-api-key` (exists) |
| `GOOGLE_MAPS_API_KEY` | `google-maps-api-key` |
| `GOOGLE_VISION_API_KEY` | `google-vision-api-key` |
| `PARALLEL_API_KEY` | `parallel-api-key` |
| `SURREALDB_URL` / `_USER` / `_PASS` | `surreal-url` / `surreal-user` / `surreal-pass` (the app reads `SURREAL_*`) |

`scripts/secrets.sh` creates the secret or adds a version, and grants the Cloud Run runtime
account (`<project-number>-compute@developer`) `secretAccessor`. It passes values on stdin only.
Rotate after the event: run it again with the new value.

## Deploy

`MODE`, `OPTIONAL_SECRETS`, the `xray` default and the per-service state path need the T-1136
patch to `scripts/deploy.sh` (owned by the spine, T-1131).

```bash
PROJECT=hackathon-starter-ao make deploy                 # MODE=cloud, every existing key mounted
PROJECT=hackathon-starter-ao MODE=local make deploy      # offline FakeProvider; /health says "fake"
PROJECT=hackathon-starter-ao MODE=local OPTIONAL_SECRETS= make deploy   # mounts no keys at all
```

`MODE=cloud` refuses to start without its model key, by design (scenario S8); use `MODE=local`
until the key exists. The service gets label `commit=<12-char sha>`, its state lives at
`gs://hackathon-starter-ao-state/<service>/store.json`, and the script curls `/health` and runs the
live smoke. Check what is live:

```bash
gcloud run services describe xray --region europe-west1 --project hackathon-starter-ao \
  --format 'value(status.url,metadata.labels.commit,status.latestReadyRevisionName)'
```

Demo day: `MIN_INSTANCES=1` so the judges never hit a cold start.
