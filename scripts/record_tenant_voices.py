"""The one live Parallel search per demo listing, saved for every later run (cost rule).

    PARALLEL_API_KEY=... uv run python scripts/record_tenant_voices.py demo kimberley-road ...

A listing already recorded is skipped, never re-called."""

import os
import sys

from starter.verticals.sources import load_listing, tenant_voices


def main(ids: list[str]) -> None:
    key = os.environ.get("PARALLEL_API_KEY") or sys.exit("set PARALLEL_API_KEY")
    for lid in ids:
        place, listing = load_listing(lid, offline=True)
        try:
            path = tenant_voices.record(place, listing["listing_id"], key)
        except FileExistsError as e:
            print(f"skip {lid}: {e}")
            continue
        try:
            n = len(tenant_voices.ingest(place, listing)[1])
        except Exception as e:  # SourceOff: recorded, but nothing a renter said
            n = f"0 ({e})"
        print(f"{lid}: {path} quotes={n}")


if __name__ == "__main__":
    main(sys.argv[1:])
