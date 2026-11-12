"""Settings from the environment. Local mode runs offline with no keys; cloud mode refuses to
start without its secrets, so a missing key is a failed deploy, never a silent fake."""

import os
from dataclasses import dataclass

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_MAX_RETRIES = 1  # the SDK retries a timed-out call; each try gets the model timeout
EFFORTS = ("low", "medium", "high", "xhigh", "max")
REMOTE = ("ws://", "wss://", "http://", "https://")  # a SurrealDB server, not mem:// or a file
SURREAL_ENV = ("SURREAL_URL", "SURREAL_NS", "SURREAL_DB", "SURREAL_USER", "SURREAL_PASS")


@dataclass(frozen=True)
class Settings:
    mode: str = "local"
    data_path: str = "data/store.json"  # a file path, or gs://bucket/object for GcsStore
    store: str = "json"  # "json" is data_path above; "surreal" is SurrealStore on surreal_*
    surreal_url: str = "mem://"  # embedded in-process; ws(s)://host/rpc for a server
    surreal_namespace: str = "starter"
    surreal_database: str = "starter"
    surreal_user: str | None = None
    surreal_password: str | None = None
    admin_password: str = "admin"
    anthropic_api_key: str | None = None
    model: str = DEFAULT_MODEL
    mode_effects: str = "simulate"  # "live" lets effect tools act; anything else simulates
    case_timeout_s: float = 120
    model_timeout_s: float = 50
    max_iterations: int = 8  # model calls per case
    effort: str = "medium"
    resend_api_key: str | None = None  # send_email; live effects need it and email_from
    email_from: str | None = None  # "Name <you@your-verified-domain>"
    elevenlabs_api_key: str | None = None  # place_call; live effects need it and both ids
    elevenlabs_agent_id: str | None = None
    elevenlabs_phone_number_id: str | None = None
    demo_latency: tuple[float, float] | None = None  # (low, high) s; only the demo recorder sets it

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        mode = env.get("MODE", "local")
        if mode not in ("local", "cloud"):
            raise ValueError(f"MODE must be local or cloud, got {mode!r}")
        if mode == "cloud":
            missing = [k for k in ("ANTHROPIC_API_KEY", "ADMIN_PASSWORD") if not env.get(k)]
            if missing:
                raise RuntimeError(f"cloud mode refuses to start without {', '.join(missing)}")
        store = env.get("STORE", "json")
        if store not in ("json", "surreal"):
            raise ValueError(f"STORE must be json or surreal, got {store!r}")
        if mode == "cloud" and store == "surreal":
            missing = [k for k in SURREAL_ENV if not env.get(k)]
            if missing:
                raise RuntimeError(f"STORE=surreal refuses to start without {', '.join(missing)}")
        # A Cloud Run disk is wiped on restart and not shared between instances: cloud state lives
        # off the box, or the deploy fails here instead of losing data later.
        if mode == "cloud" and store == "json" and not env.get("DATA_PATH", "").startswith("gs://"):
            raise RuntimeError("cloud mode refuses a JSON store off GCS: set DATA_PATH=gs://...")
        if mode == "cloud" and store == "surreal" and not env["SURREAL_URL"].startswith(REMOTE):
            raise RuntimeError("cloud mode refuses an in-process SurrealDB: SURREAL_URL=wss://...")
        effects = env.get("EFFECTS", "simulate")
        if effects not in ("simulate", "live"):
            raise ValueError(f"EFFECTS must be simulate or live, got {effects!r}")
        effort = env.get("EFFORT", "medium")
        if effort not in EFFORTS:
            raise ValueError(f"EFFORT must be one of {', '.join(EFFORTS)}, got {effort!r}")
        demo_latency = None
        if latency := env.get("DEMO_LATENCY"):
            low, _, high = latency.partition("-")
            demo_latency = (float(low), float(high or low))
            if not 0 <= demo_latency[0] <= demo_latency[1]:
                raise ValueError(f"DEMO_LATENCY must be low-high seconds, got {latency!r}")
        case_timeout_s = float(env.get("CASE_TIMEOUT_S", 120))
        model_timeout_s = float(env.get("MODEL_TIMEOUT_S", 50))
        if (1 + MODEL_MAX_RETRIES) * model_timeout_s >= case_timeout_s:
            raise ValueError("inner timeouts must be shorter than the case timeout")
        return cls(
            mode=mode,
            data_path=env.get("DATA_PATH", "data/store.json"),
            store=store,
            surreal_url=env.get("SURREAL_URL", "mem://"),
            surreal_namespace=env.get("SURREAL_NS", "starter"),
            surreal_database=env.get("SURREAL_DB", "starter"),
            surreal_user=env.get("SURREAL_USER") or None,
            surreal_password=env.get("SURREAL_PASS") or None,
            admin_password=env.get("ADMIN_PASSWORD", "admin"),
            anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
            model=env.get("MODEL", DEFAULT_MODEL),
            mode_effects=effects,
            case_timeout_s=case_timeout_s,
            model_timeout_s=model_timeout_s,
            max_iterations=int(env.get("MAX_ITERATIONS", 8)),
            effort=effort,
            resend_api_key=env.get("RESEND_API_KEY") or None,
            email_from=env.get("EMAIL_FROM") or None,
            elevenlabs_api_key=env.get("ELEVENLABS_API_KEY") or None,
            elevenlabs_agent_id=env.get("ELEVENLABS_AGENT_ID") or None,
            elevenlabs_phone_number_id=env.get("ELEVENLABS_PHONE_NUMBER_ID") or None,
            demo_latency=demo_latency,
        )

    def public(self) -> dict:
        """What is configured, safe to show anyone: never a secret."""
        return {
            "mode": self.mode,
            "model": self.model,
            "effects": self.mode_effects,
            "providers": {"anthropic": "configured" if self.anthropic_api_key else "fake"},
        }
