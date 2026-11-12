# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML, CSS and JavaScript served by the project’s FastAPI application. The shared API contract is in `docs/CONTRACT.md`.

## Users

Renters checking a residential listing before deciding whether to view or apply. Office property evaluators are a secondary audience.

## Product Purpose

X-ray compares claims in a property listing with independent records and shows the evidence and provenance behind each finding.

## Positioning

Every displayed finding points to the source record or document span, its retrieval time, and the agent that gathered it. Users can inspect why claims agree, differ, or remain unverifiable.

## Operating Context

The user supplies a listing URL or crawl listing ID, chooses Residential or Office, and reviews source coverage, findings, history, and cited records on desktop or phone. Residential is the main demonstration; Office is a secondary path through the same workflow.

## Capabilities and Constraints

- The approved residential demonstration may show listing history, EPC records, photo matches, and cited tenant reviews only when each check has actually run and has evidence.
- Office checks may include non-domestic EPC and MEES, floor area, HMLR, Companies House occupier records, and agent-page history; the demo must show only checks actually run.
- The Trust Score excludes unverifiable claims, which remain visible separately.
- Grok Bot drives the product through MCP. The product agent uses the configured platform model; do not describe it as a Grok API call. Cursor SDK and MCP counts are shown only when provided by the run.
- Missing evidence is not a match. Findings without a source remain unverifiable.
- Describe discrepancies in terms of the records. A discrepancy alone does not establish fraud or AI-generated imagery.
- Sample values may appear only with the visible label: **Illustrative prototype. These values demonstrate the interface; they are not a real property assessment.**
- Do not place API keys, licensed MSCI data, or personal data in the public project.

## Brand Commitments

The product name is X-ray. Use plain language about claims and records; make no promise that a property or image is truthful beyond the checks actually run.

## Evidence on Hand

- Approved demonstration listing: [24 Macquarie Way, Isle of Dogs, Auction House](https://www.auctionhouse.co.uk/london/auction/lot/152478).
- The opening image is the listing’s [930671 exterior photograph](https://www.auctionhouse.co.uk/lot-image/930671?w=1200). It is self-hosted unchanged, linked to its source, and used for location context rather than evidence for prototype findings. Copyright remains with the source photographer; see `starter/web/static/images/SOURCES.md`.
- The saved listing page records a sold price of £770,000 and EPC D. The crawl record is dated 24 October 2026. No historical price change has been established; a sold price and guide or asking price have different bases.
- The organiser’s crawl has 7,251 listing rows. This count is not an error-detection or accuracy measure; such claims require a measured held-out evaluation.
- No historical rent or photo change is approved for this property without an independent source.

## Product Principles

- Put the property evidence beside the listing claim.
- Give each displayed value its source and retrieval context.
- Preserve uncertainty when evidence is absent.
- Count real agent calls; never invent demo activity.

## Accessibility & Inclusion

Support keyboard use and visible focus, readable contrast, touch targets of at least 44px, and reduced-motion preferences. The fly-in is optional and skippable.
