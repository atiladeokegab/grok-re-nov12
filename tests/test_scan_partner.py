import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts.scan_partner import REQUIRED, coordinates, positive, scan


def row(**changes):
    return {
        **dict.fromkeys(REQUIRED, ""),
        "listing_id": "one",
        "url": "https://advert.example/one",
        "address": "1 Example Road",
        "property_type": "house",
        "hmlr_property_type": "T",
        "tenure": "freehold",
        "hmlr_tenure": "F",
        "match_confidence": "high",
        "price_gbp": "200000",
        "size_sqft": "800",
        "sale_or_let": "sale",
        "price_basis": "guide/asking",
        "hmlr_price_gbp": "100000",
        "hmlr_date": "2020-01-01",
        **changes,
    }


def write_csv(tmp_path, rows):
    path = tmp_path / "listings.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(REQUIRED))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_every_row_is_scanned_and_unique_flags_keep_values_and_provenance(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row(),
            row(listing_id="two", property_type="flat", hmlr_tenure="L"),
            row(listing_id="three", property_type="flat", match_confidence="low"),
            row(listing_id="four", property_type="residential", tenure="virtual freehold"),
        ],
    )
    result = scan(path)
    assert result["rows_scanned"] == result["unique_listing_ids"] == 4
    assert result["flagged_listings"] == 1
    assert result["flagged_comparisons"] == 2
    assert {flag["check"] for flag in result["flags"]} == {"property_type", "tenure"}
    assert all(flag["listing_id"] == "two" for flag in result["flags"])
    assert result["flags"][0]["advert_value"] == "flat"
    assert result["flags"][0]["record_value"] == "T"
    assert result["flags"][0]["url"] == "https://advert.example/one"
    assert result["source"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    for check in result["checks"].values():
        assert check["comparable"] + check["unverifiable"] == 4


def test_historic_price_differences_are_context_never_flags_and_rent_is_excluded(tmp_path):
    result = scan(
        write_csv(
            tmp_path,
            [
                row(),
                row(listing_id="two", sale_or_let="let", price_basis="rent pa"),
                row(listing_id="three", price_gbp="50000"),
                row(listing_id="four", hmlr_date="not-a-date"),
            ],
        )
    )
    assert result["flagged_listings"] == 0
    assert result["price_context"] == {
        "context": 2,
        "above": 1,
        "below": 1,
        "same": 0,
        "not_applicable": 1,
        "unverifiable": 1,
    }


def test_missing_and_invalid_numbers_are_unverifiable_without_imputation(tmp_path):
    for value in ("", "0", "-1", "NaN", "Infinity", "not a price"):
        assert positive(value) is None
    result = scan(write_csv(tmp_path, [row(price_gbp="", size_sqft="0")]))
    assert result["unverifiable_missing_values"] == {"price": 1, "size": 1}
    assert not result["flags"]


def test_generic_house_subtypes_and_long_leasehold_are_not_false_flags(tmp_path):
    rows = [row(listing_id=code, hmlr_property_type=code) for code in "DST"]
    rows.append(row(listing_id="lease", tenure="long leasehold", hmlr_tenure="L"))
    assert scan(write_csv(tmp_path, rows))["flagged_listings"] == 0


def test_missing_schema_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("listing_id\none\n")
    with pytest.raises(ValueError, match="required columns"):
        scan(path)


def test_landing_headline_matches_committed_scan_counts():
    root = Path(__file__).resolve().parents[1]
    artifact = json.loads((root / "starter/web/static/partner-scan.json").read_text())
    landing = (root / "starter/web/static/index.html").read_text()
    headline = (
        f"Ran across all {artifact['rows_scanned']:,} partner listings · "
        f"{artifact['flagged_listings']:,} flagged for review"
    )
    assert headline in re.sub(r"<[^>]+>", "", landing)
    assert 'href="/analyst#partner-scan"' in landing


def test_coordinates_are_rounded_without_inventing_missing_or_invalid_positions():
    assert coordinates({"lat": "51.50745", "lon": "-0.12786"}) == [51.507, -0.128]
    for lat, lon in [("", ""), ("NaN", "1"), ("91", "1"), ("51", "181")]:
        assert coordinates({"lat": lat, "lon": lon}) == [None, None]
