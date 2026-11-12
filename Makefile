.PHONY: dev check smoke smoke-xray e2e demo eval bootstrap deploy mcp

MCP_URL ?= http://127.0.0.1:8000/mcp

dev:
	uv run uvicorn starter.main:app --reload

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q

# The merge gate: offline and deterministic even when .env holds a real key. Never calls a model.
smoke: check smoke-xray

smoke-xray:
	out="$${SMOKE_OUT:-$$(mktemp -d)}" && \
	ANTHROPIC_API_KEY= XAI_API_KEY= MODE=local EFFECTS=simulate DATA_PATH="$$out/store.json" \
	uv run python scripts/xray.py --fixture demo > "$$out/xray.json"

# The pages in Chromium against an offline, seeded app. Downloads the browser once; not in check.
e2e:
	uv run playwright install chromium
	out="$${E2E_OUT:-$$(mktemp -d)}" && \
	E2E_OUT="$$out" uv run pytest -q -m e2e tests/e2e && echo "screenshots: $$out"

# The demo film from the offline, seeded app: docs/media/demo.mp4 and demo.gif. Needs ffmpeg.
demo:
	uv run playwright install chromium
	uv run scripts/demo/record.py

# The real model on the sample cases, for the reviewer on agent/core PRs. Costs money; never a gate.
eval:
	uv run python scripts/eval_listings.py

bootstrap:
	scripts/bootstrap.sh

deploy:
	scripts/deploy.sh

mcp:
	uv run python -m starter.runtime.mcp_door $(MCP_URL)
