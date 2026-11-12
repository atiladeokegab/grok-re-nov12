"""The one app factory: health, login, the error map, request logging, seeding, and mounting
every vertical. A new part of the product is a module in starter/verticals/, not a new app."""

import hmac
import json
import os
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from starter import verticals
from starter.agent import routes
from starter.core.errors import ConflictError, NotFound, ProviderNotConfigured
from starter.core.gateway import build_gateway
from starter.core.store import Store, open_store
from starter.core.surreal_store import SurrealStore
from starter.core.tracing import EXPORTER, tracer
from starter.runtime import mcp_door
from starter.runtime.config import Settings
from starter.runtime.deps import require_token, session_token
from starter.web import pages

ERROR_STATUS = {ConflictError: 409, NotFound: 404, ProviderNotConfigured: 503, ValueError: 422}


class Login(BaseModel):
    password: str


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or _open_store(settings)
    gateway = build_gateway(store, settings.mode_effects, settings.demo_latency)
    mcp = mcp_door.build_mcp(gateway)
    mcp_app = mcp_door.asgi_app(mcp)
    app = FastAPI(title="starter", lifespan=lambda app: mcp.session_manager.run())
    app.state.settings = settings
    app.state.store = store
    app.state.gateway = gateway
    EXPORTER.echo = True  # a server prints every span: Cloud Run keeps stdout as its log

    for exc, status in ERROR_STATUS.items():
        app.add_exception_handler(exc, _error_handler(status))

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        name = f"{request.method} {request.url.path}"
        with tracer.start_as_current_span(name, attributes={"request_id": request_id}) as span:
            response = await call_next(request)
            span.set_attribute("status", response.status_code)
        response.headers["x-request-id"] = request_id
        line = {
            "request_id": request_id,
            "trace_id": format(span.get_span_context().trace_id, "032x"),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - start) * 1000, 1),
        }
        print(json.dumps(line), flush=True)  # Cloud Run reads stdout JSON as structured logs
        return response

    @app.get("/health")  # Cloud Run reserves paths ending in "z": /healthz is local only
    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", **settings.public()}

    @app.get("/api/config")
    def config() -> dict:
        # A browser Maps key is public by design (referrer-restricted); the fly-in reads it.
        return {"maps_key": os.environ.get("GOOGLE_MAPS_API_KEY") or None}

    @app.post("/api/login")
    def login(body: Login) -> dict:
        if not hmac.compare_digest(body.password, settings.admin_password):
            raise HTTPException(401, "wrong password")
        return {"token": session_token(settings.admin_password)}

    @app.post("/api/mcp/token", dependencies=[Depends(require_token)])
    def mcp_token() -> dict:
        return {"token": mcp_door.issue_token(settings.mcp_key)}

    app.add_route("/mcp", mcp_door.TokenGuard(mcp_app, settings.mcp_key))
    app.include_router(routes.router)
    app.include_router(pages.router)
    app.mount("/static", pages.static, name="static")

    for module in verticals.modules():
        if hasattr(module, "router"):
            app.include_router(module.router)
        if settings.mode == "local" and hasattr(module, "seed"):
            module.seed(store)
    return app


def _open_store(settings: Settings) -> Store:
    if settings.store == "surreal":
        s = settings
        creds = (s.surreal_user, s.surreal_password)
        return SurrealStore(s.surreal_url, s.surreal_namespace, s.surreal_database, *creds)
    return open_store(settings.data_path)


def _error_handler(status: int):
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=status)

    return handle
