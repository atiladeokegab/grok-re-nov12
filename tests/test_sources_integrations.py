import importlib.util
import sys
from pathlib import Path

import httpx2
import pytest

ROOT = Path(__file__).parents[1]


def load_source(name):
    spec = importlib.util.spec_from_file_location(
        f"atlas_{name}", ROOT / "starter/verticals/sources" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reverse = load_source("reverse_image")
reviews = load_source("reviews_parallel")


def test_web_detection_only_reports_attributed_exact_or_partial_matches():
    exact = "https://pages.example/exact"
    result = reverse.web_matches(
        {
            "responses": [
                {
                    "webDetection": {
                        "visuallySimilarImages": [{"url": "https://pages.example/similar"}],
                        "pagesWithMatchingImages": [
                            {
                                "url": exact,
                                "pageTitle": "Public advert",
                                "fullMatchingImages": [{"url": "https://images.example/full"}],
                            },
                            {
                                "url": "https://pages.example/partial",
                                "partialMatchingImages": [{"url": "https://images.example/crop"}],
                            },
                            {
                                "url": "https://user@pages.example/credential-url",
                                "fullMatchingImages": [{"url": "https://images.example/private"}],
                            },
                            {
                                "url": "http://127.0.0.1/private",
                                "fullMatchingImages": [{"url": "http://127.0.0.1/private"}],
                            },
                            {
                                "url": "javascript:alert(1)",
                                "fullMatchingImages": [{"url": "javascript:alert(1)"}],
                            },
                        ],
                    }
                }
            ]
        }
    )
    assert result == [
        {"url": exact, "title": "Public advert", "match_type": "full"},
        {"url": "https://pages.example/partial", "title": "", "match_type": "partial"},
    ]


@pytest.mark.parametrize(
    "response",
    [
        {"error": {"message": "permission denied"}},
        {"errors": [{"message": "quota exceeded"}]},
        {"responses": [{"error": {"code": 7}}]},
    ],
)
def test_cloud_vision_errors_do_not_look_like_empty_success(response):
    with pytest.raises(ValueError, match="could not inspect"):
        reverse.web_matches(response)


def test_parallel_excerpt_is_public_source_attributed_and_word_bounded():
    response = {
        "results": [
            {
                "url": "https://reviews.example/flat",
                "title": "Resident forum",
                "excerpts": ["tenant " * 35],
            },
            {"url": "https://reviews.example/flat", "excerpts": ["duplicate"]},
            {"url": "https://reviews.example/not-requested", "excerpts": ["nearby place"]},
            {"url": "https://reviewer:secret@reviews.example/private", "excerpts": ["private"]},
            {"url": "javascript:alert(1)", "excerpts": ["unsafe"]},
        ]
    }
    found = reviews.review_excerpts(response, {"https://reviews.example/flat"})
    assert len(found) == 1
    assert found[0]["excerpt"] == " ".join(["tenant"] * 25)
    assert found[0]["scope"] == "Search result; building and author identity require verification"


@pytest.mark.parametrize(
    "response",
    [
        {"error": {"message": "permission denied"}},
        {"errors": [{"message": "fetch failed"}]},
    ],
)
def test_parallel_errors_do_not_look_like_empty_success(response):
    with pytest.raises(ValueError, match="could not extract"):
        reviews.review_excerpts(response)


def test_live_web_detection_uses_listing_photos_and_cited_provider_match(monkeypatch):
    sys.path.insert(0, "/home/atilade/work/grok-re-nov12/T-1131")
    from starter.core.xray import Place

    image_url = "https://cdn.example/listing.jpg"
    page_url = "https://another.example/old-listing"
    requests = []

    def post(url, **kwargs):
        requests.append((url, kwargs))
        return httpx2.Response(
            200,
            request=httpx2.Request("POST", url),
            json={
                "responses": [
                    {
                        "webDetection": {
                            "pagesWithMatchingImages": [
                                {
                                    "url": page_url,
                                    "fullMatchingImages": [
                                        {
                                            "url": "https://cdn.example/reused.jpg",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ]
            },
        )

    monkeypatch.setenv("GOOGLE_CLOUD_VISION_API_KEY", "test-only")
    monkeypatch.setattr(httpx2, "post", post)
    place = Place(id="place-one", address="1 Example Road", postcode="E1 1AA")
    claims, evidence = reverse.ingest(
        place,
        {
            "offline": False,
            "page": {"photos": [image_url]},
            "listing_id": "one",
        },
    )
    assert claims == []
    assert [item.source_url for item in evidence] == [page_url]
    assert evidence[0].value["image_url"] == image_url
    assert "unverified" in evidence[0].value["interpretation"]
    assert evidence[0].doc_span and "ownership, consent" in evidence[0].doc_span
    assert evidence[0].id == "ev-reverse_image-one-photo_reuse-0-0"
    assert requests[0][0] == "https://vision.googleapis.com/v1/images:annotate"
    assert requests[0][1]["timeout"] == 15
    assert requests[0][1]["json"]["requests"][0]["image"]["source"]["imageUri"] == image_url
    assert requests[0][1]["json"]["requests"][0]["features"][0]["type"] == "WEB_DETECTION"


def test_parallel_live_search_and_extract_are_bounded_and_only_cited_for_search_hits(monkeypatch):
    sys.path.insert(0, "/home/atilade/work/grok-re-nov12/T-1131")
    from starter.core.xray import Place

    source_url = "https://reviews.example/building"
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/search"):
            return httpx2.Response(
                200, request=httpx2.Request("POST", url), json={"results": [{"url": source_url}]}
            )
        return httpx2.Response(
            200,
            request=httpx2.Request("POST", url),
            json={
                "results": [
                    {
                        "url": source_url,
                        "title": "Resident reviews",
                        "excerpts": ["Damp in winter"],
                    },
                    {
                        "url": "https://reviews.example/other-building",
                        "excerpts": ["Wrong building"],
                    },
                ]
            },
        )

    monkeypatch.setenv("PARALLEL_API_KEY", "test-only")
    monkeypatch.setattr(httpx2, "post", post)
    place = Place(id="place-one", address="1 Example Road", postcode="E1 1AA")
    claims, evidence = reviews.ingest(place, {"offline": False, "listing_id": "one"})
    assert claims == []
    assert len(calls) == 2
    assert calls[0][0] == "https://api.parallel.ai/v1/search"
    assert calls[0][1]["timeout"] == 15
    assert calls[0][1]["json"]["search_queries"]
    assert calls[1][0] == "https://api.parallel.ai/v1/extract"
    assert calls[1][1]["json"]["urls"] == [source_url]
    assert [item.source_url for item in evidence] == [source_url]
    assert evidence[0].value["excerpt"] == "Damp in winter"
    assert evidence[0].doc_span and "author identity are unverified" in evidence[0].doc_span
    assert evidence[0].id == "ev-reviews_parallel-one-tenant_reviews-0"
    assert "identity require verification" in evidence[0].value["scope"]


def test_missing_live_keys_return_no_fake_evidence(monkeypatch):
    sys.path.insert(0, "/home/atilade/work/grok-re-nov12/T-1131")
    from starter.core.xray import Place

    monkeypatch.delenv("GOOGLE_CLOUD_VISION_API_KEY", raising=False)
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    place = Place(id="place-one", address="1 Example Road", postcode="E1 1AA")
    assert reverse.ingest(
        place,
        {
            "offline": False,
            "page": {
                "photos": [
                    "https://cdn.example/photo.jpg",
                ]
            },
        },
    ) == ([], [])
    assert reviews.ingest(place, {"offline": False}) == ([], [])
