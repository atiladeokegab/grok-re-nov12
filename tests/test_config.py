import json

import pytest

from starter.runtime.config import Settings


def test_local_defaults_need_no_keys():
    s = Settings.from_env({})
    assert (s.mode, s.model, s.anthropic_api_key) == ("local", "claude-opus-5-5", None)
    assert s.public()["providers"] == {"anthropic": "fake"}


def test_cloud_refuses_missing_secrets():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY, ADMIN_PASSWORD"):
        Settings.from_env({"MODE": "cloud"})


def test_cloud_with_secrets_starts_and_public_hides_them():
    env = {"MODE": "cloud", "ANTHROPIC_API_KEY": "sk-secret", "ADMIN_PASSWORD": "pw"}
    s = Settings.from_env({**env, "DATA_PATH": "gs://b/store.json"})
    assert s.mode == "cloud" and s.data_path == "gs://b/store.json"
    shown = json.dumps(s.public())
    assert "sk-secret" not in shown and "pw" not in shown
    assert s.public()["providers"] == {"anthropic": "configured"}


def test_cloud_refuses_a_store_that_does_not_survive_a_restart():
    cloud = {"MODE": "cloud", "ANTHROPIC_API_KEY": "k", "ADMIN_PASSWORD": "pw"}
    for path in (None, "/tmp/store.json", "data/store.json"):
        env = cloud if path is None else {**cloud, "DATA_PATH": path}
        with pytest.raises(RuntimeError, match="DATA_PATH=gs://"):
            Settings.from_env(env)
    surreal = {**cloud, "STORE": "surreal", "SURREAL_NS": "n", "SURREAL_DB": "d"}
    surreal |= {"SURREAL_USER": "u", "SURREAL_PASS": "p"}
    for url in ("mem://", "surrealkv://data/db"):
        with pytest.raises(RuntimeError, match="in-process SurrealDB"):
            Settings.from_env({**surreal, "SURREAL_URL": url})
    assert Settings.from_env({**surreal, "SURREAL_URL": "wss://db.example"}).store == "surreal"
    assert Settings.from_env({}).data_path == "data/store.json"  # local is unchanged


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        Settings.from_env({"MODE": "prod"})


def test_effects_default_to_simulate_everywhere_and_live_is_opt_in():
    cloud = {
        "MODE": "cloud",
        "ANTHROPIC_API_KEY": "k",
        "ADMIN_PASSWORD": "pw",
        "DATA_PATH": "gs://b/s",
    }
    assert Settings().mode_effects == "simulate"
    assert Settings.from_env({}).mode_effects == "simulate"
    assert Settings.from_env(cloud).mode_effects == "simulate"
    assert Settings.from_env({**cloud, "EFFECTS": "live"}).mode_effects == "live"
    with pytest.raises(ValueError, match="EFFECTS must be simulate or live"):
        Settings.from_env({"EFFECTS": "real"})


def test_the_app_gateway_follows_effects(store):
    from starter.runtime.factory import create_app

    assert create_app(Settings(), store).state.gateway.live is False
    assert create_app(Settings(mode_effects="live"), store).state.gateway.live is True


def test_demo_latency_is_off_unless_set_and_parses_low_high():
    assert Settings.from_env({}).demo_latency is None
    assert Settings.from_env({"DEMO_LATENCY": "0.35-1.0"}).demo_latency == (0.35, 1.0)
    for bad in ("1-0.5", "-1", "fast"):
        with pytest.raises(ValueError):
            Settings.from_env({"DEMO_LATENCY": bad})
