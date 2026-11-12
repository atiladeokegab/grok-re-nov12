"""scripts/bootstrap.sh, the real shell, against a fake gcloud (tests/fake_gcloud.py): a first run
creates every resource, a rerun on a project that has them creates and overwrites nothing."""

import re
import shutil

from tests.fake_gcloud import ROOT, run

APIS = """run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com
iamcredentials.googleapis.com"""
ENV = {
    "PROJECT": "demo-proj",
    "ANTHROPIC_API_KEY": "sk-test",
    "ADMIN_PASSWORD": "pw-test",
    "FAKE_APIS": APIS,
}
DEPLOYER = "serviceAccount:deployer@demo-proj.iam.gserviceaccount.com"
RUNTIME = "serviceAccount:123456-compute@developer.gserviceaccount.com"


def changes(calls):
    """The args of each gcloud call that creates or changes something."""
    verbs = ("create", "enable", "update", "add", "add-iam-policy-binding")
    return [c["args"] for c in calls if c["cmd"] == "gcloud" and set(c["args"]) & set(verbs)]


def grants(calls):
    return {
        (a[a.index("--member") + 1], a[a.index("--role") + 1])
        for a in changes(calls)
        if "add-iam-policy-binding" in a
    }


def test_a_new_project_gets_every_resource(tmp_path):
    proc, calls = run("bootstrap.sh", tmp_path, ENV)
    assert proc.returncode == 0, proc.stderr
    made = [a for a in changes(calls) if "add-iam-policy-binding" not in a]
    assert made[0] == ["services", "enable", *APIS.split(), "--project", "demo-proj"]
    assert [a[:3] for a in made[1:]] == [
        ["artifacts", "repositories", "create"],
        ["storage", "buckets", "create"],
        ["storage", "buckets", "update"],
        ["secrets", "create", "anthropic-api-key"],
        ["secrets", "create", "admin-password"],
        ["iam", "service-accounts", "create"],
    ]
    assert "gs://demo-proj-state" in made[2] and "--public-access-prevention" in made[2]
    stdin = {c["args"][2]: c["stdin"] for c in calls if c["args"][:2] == ["secrets", "create"]}
    assert stdin == {"anthropic-api-key": "sk-test", "admin-password": "pw-test"}
    assert grants(calls) == {
        (RUNTIME, "roles/run.builder"),
        (RUNTIME, "roles/storage.objectUser"),
        (RUNTIME, "roles/secretmanager.secretAccessor"),
        (DEPLOYER, "roles/run.admin"),
        (DEPLOYER, "roles/run.sourceDeveloper"),
        (DEPLOYER, "roles/serviceusage.serviceUsageConsumer"),
        (DEPLOYER, "roles/logging.viewer"),
        (DEPLOYER, "roles/iam.serviceAccountUser"),
        (DEPLOYER, "roles/secretmanager.secretAccessor"),
        ("user:me@example.com", "roles/iam.serviceAccountTokenCreator"),
    }


def test_a_rerun_creates_nothing_and_only_re_grants(tmp_path):
    proc, calls = run("bootstrap.sh", tmp_path, {**ENV, "FAKE_EXISTING": "1"})
    assert proc.returncode == 0, proc.stderr
    assert [a for a in changes(calls) if "add-iam-policy-binding" not in a] == []
    assert not any("stdin" in c for c in calls)  # no secret value is sent again
    assert "wait before the first deploy" in proc.stdout  # IAM grants take ~2 min to apply


def test_a_service_account_may_be_the_deployer(tmp_path):
    hub = "hub-vm@other.iam.gserviceaccount.com"
    proc, calls = run("bootstrap.sh", tmp_path, {**ENV, "DEPLOY_AS": hub})
    assert proc.returncode == 0, proc.stderr
    assert (f"serviceAccount:{hub}", "roles/iam.serviceAccountTokenCreator") in grants(calls)
    said = f"bootstrap: serviceAccount:{hub} may deploy as deployer@demo-proj"
    assert said in proc.stdout  # printed before the grant, so a wrong account is seen


def test_a_missing_secret_with_no_value_stops_before_it_is_created(tmp_path):
    proc, calls = run("bootstrap.sh", tmp_path, {**ENV, "ANTHROPIC_API_KEY": ""})
    assert proc.returncode == 1 and "ANTHROPIC_API_KEY" in proc.stderr
    assert not any(c["args"][:2] == ["secrets", "create"] for c in calls)


def test_the_admin_password_is_generated_when_none_is_given(tmp_path):
    proc, calls = run("bootstrap.sh", tmp_path, {**ENV, "ADMIN_PASSWORD": ""})
    assert proc.returncode == 0, proc.stderr
    [made] = [c for c in calls if c["args"][:3] == ["secrets", "create", "admin-password"]]
    assert re.fullmatch(r"[0-9a-f]{48}", made["stdin"])
    assert made["stdin"] not in proc.stdout  # says where to read it, never prints it


def test_the_secrets_are_the_list_in_deploy_sh(tmp_path):
    scripts = tmp_path / "scripts"
    shutil.copytree(ROOT / "scripts", scripts, ignore=shutil.ignore_patterns("__pycache__"))
    deploy = scripts / "deploy.sh"
    text = deploy.read_text().replace('SECRETS="', 'SECRETS="resend-api-key ', 1)
    deploy.write_text(text)
    env = {**ENV, "RESEND_API_KEY": "re-test"}
    proc, calls = run("bootstrap.sh", tmp_path, env, scripts=scripts)
    assert proc.returncode == 0, proc.stderr
    made = {c["args"][2]: c["stdin"] for c in calls if c["args"][:2] == ["secrets", "create"]}
    assert made == {
        "resend-api-key": "re-test",
        "anthropic-api-key": "sk-test",
        "admin-password": "pw-test",
    }
