from copy import deepcopy

import pytest

from starter.verticals.sources.photo_diff import compare_adverts
from starter.verticals.sources.reverse_image import web_matches
from starter.verticals.sources.reviews_parallel import review_excerpts


def test_reverse_image_ignores_similar_images_without_indexed_page_match():
    assert (
        web_matches(
            {
                "responses": [
                    {
                        "webDetection": {
                            "visuallySimilarImages": [
                                {"url": "https://images.example/similar.jpg"}
                            ],
                        }
                    }
                ]
            }
        )
        == []
    )


def test_reverse_image_retains_match_kind_and_citation_once():
    page = {
        "url": "https://listing.example/one",
        "pageTitle": "Same building",
        "fullMatchingImages": [{"url": "https://images.example/photo.jpg"}],
    }
    result = web_matches(
        {
            "responses": [
                {
                    "webDetection": {
                        "pagesWithMatchingImages": [page, page, {"url": "javascript:alert(1)"}],
                    }
                }
            ]
        }
    )
    assert result == [{"url": page["url"], "title": "Same building", "match_type": "full"}]


def test_reverse_image_provider_error_is_not_empty_success():
    with pytest.raises(ValueError, match="could not inspect"):
        web_matches({"responses": [{"error": {"code": 7}}]})


def test_reviews_require_citation_and_excerpt_and_limit_quotation():
    rows = review_excerpts(
        {
            "results": [
                {"url": "https://reviews.example/building", "excerpts": ["word " * 50]},
                {"url": "https://reviews.example/empty", "excerpts": []},
                {"url": "javascript:alert(1)", "excerpts": ["false attribution"]},
            ]
        }
    )
    assert len(rows) == 1
    assert len(rows[0]["excerpt"].split()) == 25
    assert "require verification" in rows[0]["scope"]


def adverts():
    return [
        {
            "advert_id": "old",
            "captured_at": "2026-10-01T12:00:00Z",
            "url": "https://listing.example/old",
            "photos": [
                {"url": "https://images.example/a", "phash": "0123456789abcdef"},
                {"url": "https://images.example/b", "phash": "fedcba9876543210"},
            ],
        },
        {
            "advert_id": "new",
            "captured_at": "2026-10-02T12:00:00Z",
            "url": "https://listing.example/new",
            "photos": [
                {"url": "https://images.example/cdn-b", "phash": "fedcba9876543210"},
                {"url": "https://images.example/cdn-a", "phash": "0123456789abcdef"},
            ],
        },
    ]


def test_photo_reordering_and_cdn_url_change_are_not_photo_swaps():
    assert compare_adverts(adverts()) == []


def test_photo_change_is_dated_and_source_linked():
    records = adverts()
    records[1]["photos"][0]["phash"] = "0000000000000000"
    changes = compare_adverts(records[::-1])
    assert len(changes) == 1
    assert changes[0]["added"] == ["https://images.example/cdn-b"]
    assert changes[0]["removed"] == ["https://images.example/b"]
    assert changes[0]["source_url"] == "https://listing.example/new"


@pytest.mark.parametrize("missing", ["phash", "url"])
def test_incomplete_photo_snapshot_is_unverifiable_not_a_swap(missing):
    records = adverts()
    del records[1]["photos"][0][missing]
    assert compare_adverts(records) == []


def test_equal_observation_times_cannot_establish_photo_history():
    records = adverts()
    records[1]["captured_at"] = records[0]["captured_at"]
    records[1]["photos"] = deepcopy(records[0]["photos"])
    records[1]["photos"][0]["phash"] = "0000000000000000"
    assert compare_adverts(records) == []
