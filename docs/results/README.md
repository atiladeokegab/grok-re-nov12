# Measured listing checks

[eval-20.json](eval-20.json) records a frozen, deterministic sample of 20 organiser listings across England, Wales and Scotland. All 20 were independently reviewed; seven had at least one definitive field comparison. Labels were prepared without seeing the pipeline predictions.

| Measure | Result |
| --- | ---: |
| Completed pipeline runs | 20 / 20 |
| Independently reviewed listings | 20 / 20 |
| Listings with definitive evidence | 7 / 20 |
| Independently labelled field comparisons | 51 |
| Definitive comparisons | 14 |
| Confirmed discrepancies caught | 2 / 2 |
| False flags among scored negative comparisons | 0 / 2 |
| Matching labels on which the engine abstained | 10 |
| Unverifiable comparisons, excluded from scoring | 37 |
| Other emitted flags awaiting adjudication | 6 |

**Demo wording:** “We reviewed 20 listings. Seven had definitive evidence. The pinned run caught both confirmed discrepancies, with no false flags in two scored negative comparisons.”

This small, partially adjudicated sample does not establish population accuracy. The 13 listings with only unresolved judgments are not clean results. Ten matching labels without matching predictions are abstentions, not true negatives. Unit-specific fields retain their scope. Vision and Parallel had no evidence in this run.

The engine is pinned to `68f1c5be5336ff9a55285903d81d2b71b46e779a`; these numbers do not measure subsequent engine changes. The artifact embeds selection metadata, all labels, source URLs, provenance hashes, source coverage and confusion counts. Original reports are identified by SHA256 `e8e024a54121b5090d1e38270d1f9d3f1f758d9fe5b6be29c58193aac3362a86`.

Re-score saved reports without API calls using the embedded selection and labels from the artifact:

```python
import json
from pathlib import Path
from scripts.eval_listings import score_reports

artifact = json.loads(Path("docs/results/eval-20.json").read_text())
reports = json.loads(Path("reports.json").read_text())
assert score_reports(artifact["selection"], reports, artifact["labels"]) == artifact["metrics"]
```

The raw reports are retained in the team evidence cache. The script's `score` command is offline; its separate `run` command consumes provider quota and is not needed to reproduce the scoring.
