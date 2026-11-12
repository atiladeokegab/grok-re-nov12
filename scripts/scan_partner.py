"""Offline review of the supplied crawl columns; no independent record lookup or valuation."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

TYPE_LABELS = {
    "D": "Detached",
    "S": "Semi-detached",
    "T": "Terraced",
    "F": "Flat/maisonette",
    "O": "Other",
}
TYPE_CODES = {
    "house": "DST",
    "cottage": "DST",
    "residential house": "DST",
    "flat": "F",
    "apartment": "F",
    **dict.fromkeys(
        (
            "retail",
            "shop",
            "office",
            "industrial",
            "warehouse",
            "logistics",
            "hotel",
            "leisure",
            "pub",
            "restaurant",
            "garage",
            "land",
        ),
        "O",
    ),
}
TENURE_CODES = {"freehold": "F", "leasehold": "L", "long leasehold": "L"}
TENURE_LABELS = {"F": "Freehold", "L": "Leasehold"}
REQUIRED = {
    "listing_id",
    "url",
    "address",
    "property_type",
    "tenure",
    "match_confidence",
    "hmlr_property_type",
    "hmlr_tenure",
    "price_gbp",
    "size_sqft",
    "hmlr_price_gbp",
    "hmlr_date",
    "sale_or_let",
    "price_basis",
    "lat",
    "lon",
}


def positive(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None


def normal(raw: str) -> str:
    return " ".join(raw.casefold().split())


def coordinates(row: dict) -> list[float | None]:
    try:
        lat, lon = Decimal(row["lat"]), Decimal(row["lon"])
        if lat.is_finite() and lon.is_finite() and -90 <= lat <= 90 and -180 <= lon <= 180:
            return [round(float(lat), 3), round(float(lon), 3)]
    except (InvalidOperation, TypeError, ValueError):
        pass
    return [None, None]


def scan(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if missing := REQUIRED - set(reader.fieldnames or []):
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    checks = {
        name: dict(comparable=0, consistent=0, flagged=0, unverifiable=0)
        for name in ("property_type", "tenure")
    }
    flags = []
    confidence = Counter()
    missing_values = Counter(price=0, size=0)
    prices = dict(context=0, above=0, below=0, same=0, unverifiable=0, not_applicable=0)
    for index, row in enumerate(rows, 2):
        if not row.get("listing_id"):
            raise ValueError(f"CSV row {index} has no listing_id")
        high = normal(row["match_confidence"]) == "high"
        confidence[normal(row["match_confidence"]) or "missing"] += 1
        advert_type = normal(row["property_type"]).removeprefix("commercial ")
        comparisons = (
            ("property_type", TYPE_CODES.get(advert_type), TYPE_LABELS),
            ("tenure", TENURE_CODES.get(normal(row["tenure"])), TENURE_LABELS),
        )
        for field, expected, labels in comparisons:
            record = row[f"hmlr_{field}"].strip().upper()
            if not high or expected is None or record not in labels:
                checks[field]["unverifiable"] += 1
                continue
            checks[field]["comparable"] += 1
            if record in expected:
                checks[field]["consistent"] += 1
                continue
            checks[field]["flagged"] += 1
            flags.append(
                {
                    "listing_id": row["listing_id"],
                    "url": row["url"],
                    "address": row["address"],
                    "check": field,
                    "advert_value": row[field],
                    "record_value": record,
                    "record_label": labels[record],
                    "record_date": row["hmlr_date"],
                    "record_address": ", ".join(
                        filter(
                            None,
                            (
                                row.get("hmlr_saon", ""),
                                row.get("hmlr_paon", ""),
                                row.get("hmlr_street", ""),
                            ),
                        )
                    ),
                }
            )
        asking, size = positive(row["price_gbp"]), positive(row["size_sqft"])
        missing_values["price"] += asking is None
        missing_values["size"] += size is None
        if normal(row["sale_or_let"]) != "sale" or normal(row["price_basis"]) not in {
            "guide/asking",
            "guide (auction)",
        }:
            prices["not_applicable"] += 1
            continue
        sale = positive(row["hmlr_price_gbp"])
        try:
            date.fromisoformat(row["hmlr_date"])
        except ValueError:
            prices["unverifiable"] += 1
            continue
        if not high or asking is None or sale is None:
            prices["unverifiable"] += 1
            continue
        prices["context"] += 1
        prices["above" if asking > sale else "below" if asking < sale else "same"] += 1
    return {
        "schema_version": 1,
        "source": {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        "rows_scanned": len(rows),
        "unique_listing_ids": len({row["listing_id"] for row in rows}),
        "flagged_listings": len({row["listing_id"] for row in flags}),
        "flagged_comparisons": len(flags),
        "confidence_rows": dict(sorted(confidence.items())),
        "checks": checks,
        "unverifiable_missing_values": dict(missing_values),
        "price_context": prices,
        "method": {
            "record_filter": (
                "Only rows labelled match_confidence=high are compared with the supplied "
                "hmlr_* columns."
            ),
            "property_type": (
                "House/cottage allow D/S/T; flat/apartment allow F; single commercial categories "
                "and land allow O. Broad or unsupported categories are unverifiable."
            ),
            "tenure": (
                "Freehold -> F; leasehold and long leasehold -> L. Other labels are unverifiable."
            ),
            "price_context": (
                "Positive sale-row guide/asking price vs positive, dated HMLR price on "
                "high-labelled rows. Context only: never a flag or valuation. Rent is excluded."
            ),
            "missing_values": (
                "Missing, nonpositive or malformed price_gbp and size_sqft are unverifiable, "
                "never imputed."
            ),
            "flag_definition": (
                "A distinct listing is flagged if at least one comparable property-type or "
                "tenure column differs from its supplied HMLR category."
            ),
            "limitation": (
                "These are CSV column checks, not full X-ray audits. Supplied joins are not "
                "independently verified and may refer to a different unit. HMLR values describe "
                "historical sales; differences require review."
            ),
            "property_type_codes": TYPE_CODES,
            "tenure_codes": TENURE_CODES,
        },
        "flags": flags,
        "map_points": [[row["listing_id"], *coordinates(row)] for row in rows],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = scan(args.csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(
        f"Scanned {result['rows_scanned']:,} rows; {result['flagged_listings']:,} listings "
        f"with {result['flagged_comparisons']:,} supplied-column differences. No network calls."
    )


if __name__ == "__main__":
    main()
