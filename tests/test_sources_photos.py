import struct
import zlib

import pytest

from starter.verticals.sources.photo_diff import compare_adverts, perceptual_hash


def png(rows):
    """Make a small grayscale PNG without an image-generation dependency."""

    def chunk(name, data):
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    height, width = len(rows), len(rows[0])
    pixels = b"".join(b"\0" + bytes(row) for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def records(old_hash="0123456789abcdef", new_hash="0123456789abcdef"):
    return [
        {
            "advert_id": "old",
            "captured_at": "2026-10-01T12:00:00+00:00",
            "url": "https://listing.example/old",
            "photos": [{"url": "https://images.example/a", "phash": old_hash}],
        },
        {
            "advert_id": "new",
            "captured_at": "2026-10-02T12:00:00Z",
            "url": "https://listing.example/new",
            "photos": [{"url": "https://images.example/b", "phash": new_hash}],
        },
    ]


def test_hash_is_deterministic_and_uses_image_structure():
    pytest.importorskip("PIL.Image")
    flat = [[0] * 9 for _ in range(8)]
    stripes = [[255 if col < 4 else 0 for col in range(9)] for _ in range(8)]
    assert perceptual_hash(png(flat)) == perceptual_hash(png(flat))
    assert perceptual_hash(png(stripes)) != perceptual_hash(png(flat))


def test_missing_or_naive_timestamp_does_not_create_history():
    before, after = records(new_hash="ffffffffffffffff")
    del before["captured_at"]
    after["captured_at"] = "2026-10-02"
    assert compare_adverts([before, after]) == []


def test_invalid_timestamp_and_incompatible_hash_are_unverifiable():
    before, after = records(new_hash="ffffffffffffffff")
    before["captured_at"] = "not-a-date"
    assert compare_adverts([before, after]) == []
    before, after = records(new_hash="ffffffffffffffff")
    after["photos"][0]["hash_algorithm"] = "phash"
    assert compare_adverts([before, after]) == []


@pytest.mark.parametrize("url", ["https:", "javascript:alert(1)", "//images.example/photo"])
def test_bad_photo_citation_does_not_create_history(url):
    before, after = records(new_hash="ffffffffffffffff")
    after["photos"][0]["url"] = url
    assert compare_adverts([before, after]) == []


def test_timezone_equivalent_observations_have_no_ordered_change():
    before, after = records(new_hash="ffffffffffffffff")
    after["captured_at"] = "2026-10-01T13:00:00+01:00"
    assert compare_adverts([before, after]) == []
