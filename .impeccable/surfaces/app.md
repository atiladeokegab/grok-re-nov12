# App surface: X-ray property check

Mode: Operate. The user checks a listing, inspects its evidence, and decides what to follow up.

## Audience and task

Renters are primary; office property evaluators are secondary. Accept a listing URL or crawl ID for Residential or Office.

## Success and proof

Success is a sourced result: Trust Score, source coverage, findings, history, and the cited record. The key proof is opening a finding and comparing the listing claim with its evidence. Keep uncertainty and direct source links visible.

## Action and journey

1. Choose Residential or Office and enter a listing URL or crawl ID.
2. Start **X-ray this listing**.
3. Review source coverage, score, findings, and available history as records arrive.
4. Open a finding; compare the claim with cited evidence and reasoning, then follow its source.
5. Review actual Grok Bot and Cursor counts for the run when supplied.

## Screens and states

- Start: photo-led desktop hero, direct headline and action, property-type choices, listing field, and source credit beside the approved photo. On phone, the 168px photo precedes the headline and action.
- Prototype: sample values appear only with **Illustrative prototype. These values demonstrate the interface; they are not a real property assessment.**
- Results: render the score only from the API result and show source status separately; absent findings are not matches.
- Finding detail: show the claim, only evidence cited by that finding, reasoning, source URL or document span, retrieval timestamp, and agent.
- History: show old and current values only with source provenance; do not infer price changes across different price bases.
- Unavailable: say **Could not verify**, explain why, and exclude the claim from matches.
- Error: identify the failed request, preserve input and any sourced results, and offer retry.
- No findings: state that no findings arrived; do not imply verification.
- Reduced motion: skip the fly-in automatically; provide a manual skip control.

## Constraints

Use only the approved listing and credited photograph. Do not use vetoed property addresses, imagery, or data. The no-key map path uses MapLibre/OpenFreeMap with attribution. Google 3D Tiles require a key, valid coordinates, WebGL, and visible attribution. A postcode centroid is low-confidence and must not be shown as the building entrance. Counts come from actual runs. Every value must link to evidence or remain under the explicit prototype label.

## Content

- Brand: X-ray.
- Headline: “A listing tells half the story.”
- Primary action: “X-ray this listing”.
- Source line: “24 Macquarie Way, via Auction House”.
- Unavailable status: “Could not verify”.
- Prototype label: “Illustrative prototype. These values demonstrate the interface; they are not a real property assessment.”
