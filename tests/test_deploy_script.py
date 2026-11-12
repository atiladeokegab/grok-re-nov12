"""scripts/deploy.sh, the real shell, against a fake gcloud (tests/fake_gcloud.py). Every project
ships through this one script, so a typo in it would break all of them at the worst moment."""

from tests.fake_gcloud import REVISION, URL, head, run

ENV = {"PROJECT": "demo-proj", "FAKE_EXISTING": "1"}  # bootstrapped: the deployer exists
DEPLOYER = "deployer@demo-proj.iam.gserviceaccount.com"  # made by scripts/bootstrap.sh
IMPERSONATE = "CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT"


def flag(args, name):
    return args[args.index(name) + 1]


def gcloud(calls, *words):  # the args of each gcloud call that starts with these words
    hits = [c["args"] for c in calls if c["cmd"] == "gcloud"]
    return [a for a in hits if a[: len(words)] == [*words]]


def test_deploys_the_commit_then_checks_health_and_runs_the_live_smoke(tmp_path):
    proc, calls = run("deploy.sh", tmp_path, ENV)
    assert proc.returncode == 0, proc.stderr
    [deploy] = gcloud(calls, "run", "deploy")
    assert deploy[:5] == ["run", "deploy", "hackathon-starter", "--source", "."]
    assert flag(deploy, "--region") == "europe-west1" and flag(deploy, "--project") == "demo-proj"
    assert flag(deploy, "--labels") == f"commit={head(tmp_path)}"
    env_vars = "MODE=cloud,DATA_PATH=gs://demo-proj-state/store.json"
    assert flag(deploy, "--set-env-vars") == env_vars
    assert flag(deploy, "--min-instances") == "0" and flag(deploy, "--max-instances") == "3"
    assert "--quiet" in deploy and "--allow-unauthenticated" in deploy
    mounts = "ANTHROPIC_API_KEY=anthropic-api-key:latest,ADMIN_PASSWORD=admin-password:latest"
    assert flag(deploy, "--set-secrets") == mounts  # from the one SECRETS list

    check, *rest = calls  # does the deployer exist, asked as the caller; then all as the deployer
    assert check["args"][:4] == ["iam", "service-accounts", "describe", DEPLOYER]
    assert IMPERSONATE not in check and {c.get(IMPERSONATE) for c in rest} == {DEPLOYER}

    steps = [c["cmd"] if c["cmd"] != "gcloud" else " ".join(c["args"][:2]) for c in rest]
    assert steps == ["run deploy", "run services", "curl", "secrets versions", "uv"]
    assert f"{URL}/health" in rest[2]["args"]
    release = f"release: commit={head(tmp_path)} revision={REVISION} url={URL}"
    assert release in proc.stdout.splitlines()
    smoke = calls[-1]
    assert smoke["args"][:3] == ["run", "pytest", "-q"] and "live" in smoke["args"]
    assert (smoke["BASE_URL"], smoke["ADMIN_PASSWORD"]) == (URL, "live-pw")


def test_a_dirty_tree_is_refused_before_any_cloud_call(tmp_path):
    proc, calls = run("deploy.sh", tmp_path, {**ENV, "OPTIONAL_SECRETS": "xai-api-key"}, dirty=True)
    assert proc.returncode == 1 and "dirty" in proc.stderr
    assert calls == []


def test_no_project_is_refused_before_any_cloud_call(tmp_path):
    proc, calls = run("deploy.sh", tmp_path, {})
    assert proc.returncode != 0 and "PROJECT" in proc.stderr
    assert calls == []


def test_a_failed_deploy_fails_the_script_and_smokes_nothing(tmp_path):
    proc, calls = run("deploy.sh", tmp_path, {**ENV, "FAKE_FAIL": "gcloud run deploy"})
    assert proc.returncode != 0
    assert [c["cmd"] for c in calls] == ["gcloud", "gcloud"]  # the deployer check, the deploy


def test_a_failed_live_smoke_fails_the_deploy(tmp_path):
    proc, _ = run("deploy.sh", tmp_path, {**ENV, "FAKE_FAIL": "uv run pytest"})
    assert proc.returncode != 0


def test_settings_reach_the_deploy(tmp_path):
    env = {**ENV, "REGION": "us-central1", "SERVICE": "svc", "MIN_INSTANCES": "1"}
    proc, calls = run("deploy.sh", tmp_path, {**env, "STATE_BUCKET": "bkt"})
    assert proc.returncode == 0, proc.stderr
    [deploy] = gcloud(calls, "run", "deploy")
    assert deploy[2] == "svc" and flag(deploy, "--region") == "us-central1"
    assert flag(deploy, "--min-instances") == "1"
    assert "DATA_PATH=gs://bkt/store.json" in flag(deploy, "--set-env-vars")


def test_a_project_without_the_deployer_is_told_to_bootstrap(tmp_path):
    proc, calls = run("deploy.sh", tmp_path, {**ENV, "FAKE_EXISTING": ""})
    assert proc.returncode == 1
    assert "run `make bootstrap` once for demo-proj (scripts/bootstrap.sh)" in proc.stderr
    assert [c["args"][:3] for c in calls] == [["iam", "service-accounts", "describe"]]


def test_deploy_as_self_is_the_one_opt_out_and_says_so(tmp_path):
    env = {**ENV, "FAKE_EXISTING": "", "DEPLOY_AS_SELF": "1", IMPERSONATE: "someone@else"}
    proc, calls = run("deploy.sh", tmp_path, env)
    assert proc.returncode == 0, proc.stderr
    assert "deploy: deploying as me@example.com, not the deployer" in proc.stdout
    assert not any(IMPERSONATE in c for c in calls)  # not even one inherited from the shell
    assert gcloud(calls, "run", "deploy") and not gcloud(calls, "iam")
