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
