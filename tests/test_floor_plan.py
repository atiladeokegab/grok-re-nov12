import pytest

from starter.core.errors import SourceOff
from starter.verticals.sources import floor_plan, listing_history, load_listing


def test_reads_the_kimberley_road_room_schedule_offline():
    place, listing = load_listing("kimberley-road", offline=True)
    listing_history.ingest(place, listing)
    (ev,) = floor_plan.ingest(place, listing)[1]
    rooms = {r["name"]: r["area_m2"] for r in ev.value["rooms"]}
    assert rooms["Living Room"] == pytest.approx(26.91) and len(rooms) == 7
    assert ev.value["rooms_m2"] == pytest.approx(63.1) and ev.value["stated_m2"] == 81
    assert "78%" in ev.doc_span


def test_no_schedule_is_off_not_a_finding():
    assert floor_plan.read_schedule("A lovely 2 bed flat, 3 x 2 metre balcony.") is None
    place, listing = load_listing("demo", offline=True)
    listing_history.ingest(place, listing)
    with pytest.raises(SourceOff):
        floor_plan.ingest(place, listing)


def test_kimberley_run_has_the_room_schedule_and_exports_it_as_csv(tmp_path):
    import csv
    import io

    from fastapi.testclient import TestClient

    from starter.core.gateway import build_gateway
    from starter.core.store import Store
    from starter.runtime.config import Settings
    from starter.runtime.factory import create_app
    from starter.verticals.xray import run_xray

    path = tmp_path / "s.json"
    r = run_xray(build_gateway(Store(path)), "kimberley-road", offline=True)
    assert any(f.field == "room_schedule" for f in r.findings)
    with TestClient(create_app(Settings(data_path=str(path)))) as client:
        resp = client.get(f"/api/xray/{r.run_id}/export.csv")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    kinds = {row["kind"] for row in rows}
    assert kinds == {"claim", "evidence", "finding"}
    assert any(row["field"] == "room_schedule" and "63.1" in row["value"] for row in rows)
