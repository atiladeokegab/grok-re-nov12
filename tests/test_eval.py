import csv

import pytest

from scripts.eval_listings import refuse_tuning_ids, score_reports, select_listings


def report(verdict="disagrees"):
    return {
        "listing_id": "one",
        "trust_score": 0,
        "sources": [{"name": "epc", "status": "ok", "n_evidence": 1}],
        "evidence": [
            {
                "id": "ev-one",
                "agent": "epc",
                "source_url": "https://register.example/certificate",
            }
        ],
        "findings": [{"field": "energy_rating", "verdict": verdict, "evidence_ids": ["ev-one"]}],
    }


def label(expected):
    return {
        "listing_id": "one",
        "source": "epc",
        "field": "energy_rating",
        "expected": expected,
        "source_url": "https://register.example/certificate",
        "reason": "Independently checked exact dwelling and certificate dates",
    }


def test_sample_is_deterministic_and_independent_of_csv_row_order(tmp_path):
    path = tmp_path / "crawl.csv"

    def write(ids):
        with path.open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=["listing_id"])
            writer.writeheader()
            writer.writerows({"listing_id": lid} for lid in ids)

    write(["one", "two", "three", "one"])
    first = select_listings(path, 2)
    write(["three", "two", "one"])
    assert first["listing_ids"] == select_listings(path, 2)["listing_ids"]


def test_missing_label_cannot_turn_emitted_flag_into_true_or_false_positive():
    result = score_reports({"listing_ids": ["one"]}, [report()], [])
    assert result["unresolved_flags"] == 1
    assert result["detection_rate"] is None
    assert result["false_positive_rate"] is None


def test_unverifiable_without_evidence_is_not_an_ungrounded_assertion():
    row = report("unverifiable")
    row["findings"][0]["evidence_ids"] = []
    result = score_reports({"listing_ids": ["one"]}, [row], [])
    assert result["ungrounded_findings"] == 0
    assert result["unresolved_flags"] == 0


def test_false_flags_use_confirmed_claim_comparisons_as_denominator():
    result = score_reports({"listing_ids": ["one", "two"]}, [report()], [label("matches")])
    assert result["confusion_matrix"]["fp"] == 1
    assert result["false_positive_rate"] == 1
    assert result["confirmed_negative_comparisons"] == 1
    assert result["missing_reports"] == ["two"]


def test_abstention_on_known_discrepancy_is_a_missed_detection():
    result = score_reports({"listing_ids": ["one"]}, [report("unverifiable")], [label("disagrees")])
    assert result["confusion_matrix"]["fn"] == 1
    assert result["detection_rate"] == 0


def test_unknown_reference_evidence_is_not_a_negative():
    result = score_reports({"listing_ids": ["one"]}, [report()], [label("unverifiable")])
    assert result["unresolved_flags"] == 1
    assert result["confusion_matrix"]["fp"] == 0
    assert result["false_positive_rate"] is None


def test_unknown_evidence_citation_is_reported_as_ungrounded_not_scored():
    bad = report()
    bad["findings"][0]["evidence_ids"] = ["does-not-exist"]
    result = score_reports({"listing_ids": ["one"]}, [bad], [label("matches")])
    assert result["ungrounded_findings"] == 1
    assert result["unresolved_flags"] == 1
    assert result["confusion_matrix"]["fp"] == 0
    assert result["false_positive_rate"] is None


def test_tuning_rejects_frozen_sample_ids():
    with pytest.raises(ValueError, match="held-out"):
        refuse_tuning_ids(["one"], {"listing_ids": ["one"]})
    refuse_tuning_ids(["other"], {"listing_ids": ["one"]})


def test_label_must_be_independently_source_backed():
    invalid = label("matches")
    invalid.pop("source_url")
    with pytest.raises(ValueError, match="source URL"):
        score_reports({"listing_ids": ["one"]}, [report()], [invalid])


def test_duplicate_report_for_one_listing_is_rejected():
    with pytest.raises(ValueError, match="more than one report"):
        score_reports({"listing_ids": ["one"]}, [report(), report()], [])


def test_report_outside_frozen_sample_is_rejected():
    outside = report()
    outside["listing_id"] = "not-selected"
    with pytest.raises(ValueError, match="outside the frozen sample"):
        score_reports({"listing_ids": ["one"]}, [outside], [])
