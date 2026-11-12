# Lease abstraction: per-field accuracy

`scripts/eval_leases.py` (`make eval-leases`) over the 8 document-level rows
of the organisers' hand-labelled Model Commercial Lease gold set whose .docx we hold.
The extractor is `starter/verticals/lease.py`: deterministic heading and definition
rules over the Word paragraphs, no model.

| field | n | strict correct | strict | content correct | content |
|---|---|---|---|---|---|
| parties | 8 | 6 | 75% | 8 | 100% |
| premises | 8 | 6 | 75% | 8 | 100% |
| permitted_use | 8 | 5 | 62% | 8 | 100% |
| contractual_term | 8 | 7 | 88% | 7 | 88% |
| main_rent | 8 | 7 | 88% | 7 | 88% |
| rent_review | 8 | 7 | 88% | 8 | 100% |
| break_clause | 8 | 8 | 100% | 8 | 100% |
| alienation | 8 | 6 | 75% | 6 | 75% |
| insurance | 8 | 4 | 50% | 4 | 50% |
| lr_prescribed_clauses | 8 | 8 | 100% | 8 | 100% |
| **overall** | 80 | 64 | **80%** | 72 | **90%** |

## Scoring rule

- Gold is **placeholder** when the label starts with "Placeholder"; **absent** when it starts
  with "Not " or "No "; **optional** when it starts with "Optional"; **present** when it starts
  with "Yes".
- Absent gold is correct when the extractor finds nothing (or only an optional clause).
- Optional gold is correct when the extractor finds nothing or marks the clause optional
  (it was bracketed in the template).
- Present gold is correct when the extractor finds the clause.
- Otherwise, content words of the gold label (lower-case, 3+ letters, minus function words
  and template-describing words such as "placeholder", "optional", "present") must be
  ≥50% present in the extracted value plus the heading it came from.
- **Strict** also requires the placeholder flag to equal (gold is placeholder), as briefed.
  **Content** requires the flag only when gold is placeholder: the non-placeholder gold labels
  describe templates (for example parties "named in LR3") whose text still holds [LANDLORD]
  blanks, so a strict mismatch there says more about the label than the extractor.

## Skipped

- Rent-roll variance: the gold set holds unused templates with no real rent figures, so there is nothing to reconcile a rent roll against.
- Clause-level rows (MCL-LEASECLAUSE-*, licences, HMLR-LR1..LR14) are not scored here.

## Caveats

- In-sample: 8 documents, all MCL templates from one drafting group, and the
  rules were written while reading these same templates. There is no held-out set, so
  read this as a 15-template gold-set score, not accuracy on arbitrary executed leases.
- The Legal-lease_datasets zips (CUAD/DocLayNet) are not UK leases and are not used.
- Per-document results and short source spans: `docs/lease-eval.json`.
