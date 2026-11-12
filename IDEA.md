# X-ray: see through every property claim (working name)

Event: Grok Bot Real Estate Hackathon London, 12 Nov 2026. Project tag `grok-re-nov12`. Solo: the lead + hub agents.
Status: **draft for approval 1. Nothing is built.**
Pitch history: grew from the lead's own London renting story combined with Zeus's "Building X-ray"
(seller rent roll vs leases). Reddit pain research and the lead's ideas (reverse image search, listing history,
past tenants, crime, ingest everything, 3D + Street View) shaped it.

## Reshaped after the judge council (lead's decision, 19:15Z): this section wins over anything below

Council (8 role-played judges): as first written, ~5–10% for 1st; Ares judges read it as a consumer app, Grok use
weak, no measured number. Reshaped:
- **Track 3 (attribution & provenance).** Hero: a listing's **change history** from the organisers' crawl
  (rent £2,100 → £2,450, kitchen photo swapped, relisted 3 times); every figure shows source, fetched_at, agent and
  previous value.
- **Four checks only:** reverse image search, EPC register (size, rating), listing history diff, Parallel-cited
  past-tenant reviews.
- **A measured number by 30 s:** ~20 crawl listings we did not hand-pick; "caught N of M, K false flags".
- **Grok Bot drives it live** over our MCP: "X-ray 1 Example Street, E14" → markers light up; "why 41?" → cited answer.
  Cursor SDK used in the pipeline and shown.
- **Short 3D fly-in opener** (under 10 s). No Street View walk-in.
- **One real 25 s rent-roll beat for Ares:** a real lease PDF vs a rent roll, unit variance citing the clause;
  measured, or dropped.
- **Cut:** landlord view / passport, crime, flood, contract legality, Land Registry, the invented £84k / £1.4m.

## Problem

Every property document is now a sales document, and AI makes faking one free.

- **Renters** can't tell whether a listing is true. In Nov 2026 a BBC investigation found unlabelled AI-generated
  furnishings in UK listings ("housefishing"). Rightmove allows AI imagery only when labelled; UK law does not
  require disclosure. Checking a flat properly (photos, size, energy, landlord, contract, area) takes hours across
  a dozen sites, so most renters don't. The lead did it by hand when renting in London.
- **Landlords and agents** can't tell whether an applicant is true. Goodlord: 41 per 1,000 references flagged for
  suspected fraud (Jul 2025 to Jun 2026). Forged payslips and fake referees are growing fastest, and London is the
  hotspot. (Goodlord sells referencing; the £4.1bn figure is their projection.)
- **Buyers** of whole buildings face the same issue at scale. Acquisition analysts reconcile seller rent rolls
  against leases by hand (r/CommercialRealEstate: "a major part of the job, and pretty manual/tedious").

## The idea

One evidence engine and two views. **X-ray checks each claim against an independent source and shows that source.**
It never says "trust us": every verdict has a link, a page, a pixel or a register row behind it.

### Renter view: paste a listing link
Ingestion agents (one per source, Fergus's PropAdmin pattern) pull everything about that address into one evidence graph:

| Check | Source | What a lie looks like |
|---|---|---|
| Photos stolen or reused | Reverse image search (Google Cloud Vision web detection; we have GCP credits) | The same kitchen in another city's listing, or in a stock or AI-staging gallery |
| Photos AI-staged | Grok vision on each photo, plus EXIF | Furniture with no shadows, a sink-less bathroom, mismatched windows. Shown as "disagrees with the records", never "AI detected" |
| Outside matches inside | Google Street View at the address vs the listing's exterior shot | A different front door, or a different building |
| Listing history | The organisers' crawl (7,251 listings, 2,175 auctions, 24 Oct) plus earlier adverts | Photos changed between adverts, rent jumped, the same flat relisted every 3 months |
| Size and energy | EPC register (OGL) | Listing "70 m², EPC C"; register "52 m², EPC E", which falls below the planned 2030 lettings minimum |
| Sale history | Land Registry Price Paid (OGL) | Bought last year at a price that doesn't fit the story |
| Landlord or agent | Companies House API; GLA Rogue Landlord and Agent Checker | Dissolved company, struck-off director, agent on the rogue list |
| Past tenants | Parallel web search with citations: reviews of the building, agent and landlord | "Damp every winter", "deposit never returned", each quote linked |
| Fair rent | Organisers' listings crawl + ONS private rent index | 18% above the median for the same building and postcode |
| Area | police.uk street-level crime, EA flood risk, postcodes.io | Burglaries on the street in the last 12 months; flood zone 3 |
| Contract | The tenancy agreement PDF, clause by clause vs the Renters' Rights Act | An unlawful fee or no-fault-eviction clause, highlighted on the page |

Output: a **Trust Score** and a one-page X-ray. Every finding is clickable back to its source.

### Landlord view: the applicant's pack
Payslips, bank statements, references and ID. Checks: payslip maths (tax and NI vs gross); employer exists and
is old enough (Companies House); bank credits match stated pay; signs of document tampering or AI generation;
referee's company and domain are real. Output: a **verified tenant passport** the renter reuses for every
application, so landlords accept tenants faster.

### At scale (one 10 s beat, for the Ares judges)
The same engine on a whole building: seller rent roll vs lease PDFs, unit by unit. "NOI overstated £84k → £1.4m
overpaid at a 6% yield." (Planned example figure; unmeasured.)

## The spark: fly in, walk inside

The UI opens on Google's photorealistic 3D city. It flies to the building and drops to Street View at the
front door, then steps "inside" into the listing photos, where each lie is pinned as a red marker on the exact
pixel or wall. Clicking a marker shows its source. One continuous shot from city to sink.

## Architecture (Fergus's PropAdmin pattern, scaled to one night)

- **Ingestion agents**, one per source, write **claims** (what the listing or applicant says) and **evidence**
  (what the source says) into one evidence graph. Each node records source URL or document span, fetched_at and
  the agent that fetched it.
- **Reconciler (Grok)** pairs each claim with its evidence and writes a verdict: matches / disagrees / unverifiable,
  with its reasoning and citations.
- **Ingest everything, let the agents sort it** (the lead, 12 Nov): every source lands raw, then agents
  organise it into a graph that maps the place: address → building → flat → photos / adverts / registers /
  people / reviews / crimes, each edge carrying its evidence.
- **Store: SurrealDB** (graph + document + vector + full-text in one DB, as in Fergus's PropAdmin), so
  "everything about this place" is one graph query. Fergus shipped a JSON-file store first and moved to
  SurrealDB once measured; same fallback here. (Read "SQLite / sorting crazy" in dictation as SurrealDB;
  confirm.)
- **Live:** server-sent events, so markers light up as each agent reports.
- **MCP server** over the graph, so Grok Bot and Cursor can ask "X-ray this listing" or "why is the score 41?".
  This is the on-screen proof of the "Grok Bot and Cursor" criterion.
- **Front end:** 3D tiles + Street View + photo hotspots; a ledger panel with every agent call and source.

## Demo (2 minutes; storyboard)

| Time | On screen | Proof |
|---|---|---|
| 0–10 s | A real London listing. Fly in from the 3D city to the building. **"Trust Score 41/100: 4 claims don't match the records."** | Score computed live |
| 10–25 s | Street View at the door, then step inside the listing photos. Red markers on the photos. | — |
| 25–50 s | Click: the kitchen photo appears in a different listing (reverse image match). Click: 52 m² and EPC E on the register vs 70 m² and C in the advert. | Source links on screen |
| 50–65 s | Past tenants: three cited reviews ("damp every winter"). Street crime map. Rent 18% over the building median. | Parallel citations; police.uk |
| 65–80 s | Contract: clause 14 highlighted as unlawful. | Page + clause |
| 80–100 s | Landlord view: a payslip whose tax doesn't add up; the employer was incorporated last month. A clean applicant gets a passport in one click. | — |
| 100–110 s | At scale: rent roll vs leases, £1.4m overpaid. | — |
| 110–120 s | The Grok/Cursor card: agent calls, sources, verdicts from this run. End card: URL. | Real counts |

Film opener (lesson 3): the lead's own London flat hunt, in one line, over the fly-in.

## Strongest rival and where we'd lose

- **Likely rival:** a Track 2 team doing lease abstraction on V7 Go, with an accuracy score against the
  organisers' hand-labelled lease set. Or a Track 3 "click a figure to its source" team.
- **Where they beat us:** a measured accuracy number. **Missing evidence on our side:** a held-out test set,
  e.g. 20 listings (some real and clean, some with lies we did not plant ourselves, e.g. reused photos found in
  the crawl). Report the detection rate. Until then every number above is **unmeasured**.
- **Where we beat them:** a pain every judge has felt (renting in London), a both-sides twist, a picture nobody
  else will have, and real public evidence behind each verdict.
- **Risk with the Ares judges:** they may read it as a consumer app. The at-scale beat and "one evidence engine"
  framing answer that.

## Criterion → evidence

| Criterion (weight unpublished) | What the video shows | Proof / comparison | Owner |
|---|---|---|---|
| Relevance to a real estate problem | Housefishing + tenancy fraud + rent-roll reconciliation | BBC / Goodlord / Reddit citations in the deck | Zeus (deck) |
| Quality of execution | One continuous fly-in → photo-marker flow, live | Recorded on the demo laptop | builders |
| Effective use of Grok Bot and Cursor | Grok as reconciler and vision; MCP calls from Grok Bot and Cursor | Call counts from the real run | builders |
| Traceable data | Every marker clicks to its source | Ledger panel | builders |
| Practical usefulness | Detection rate on held-out listings; time vs manual checks | **Unmeasured**: needs the held-out set | Prometheus (tests) |

## What we don't build

Payments, real tenant onboarding, a purchased title register, legal advice (we flag clauses and cite the law;
we don't advise), any claim that an image "is AI". We say it disagrees with the records.

## Lessons check (headline; full `Lessons applied` table goes in the day spec)

- Agentic Web, 25, 37: visual first; the fly-in plus the score by 10 s.
- 38: the twist is both sides with one engine, every verdict sourced.
- 3: the user does it today (the lead; letting agents).
- 4, 6: one number (Trust Score / detection rate) and one hero comparison (advert vs register).
- 21: Grok/Cursor card with real counts.
- 2: ask the organisers which track and what earns full marks for "use of Grok Bot".
- 5: claim only what's true: "disagrees with the records", not "AI detected".
- 8: if it must shrink, the renter view is the product; the landlord view is one beat; at-scale is 10 s.
- 11, 17: a held-out test set of listings we didn't plant.
- 33: 3D tiles allow only 30 s of promotional video, and Street View has its own terms. Credit Google and
  keep map shots short.
- 27, 35: render checks on a real GPU (the lead's laptop); localhost test addresses on the Google key.
- 39, 40: deck from now, premium.
- Data: MSCI stays out of the repo.

## Needs UDP, a stable IP or a GPU?

A GPU for 3D-tile render checks (the VM's software GL can't draw them): check on the lead's laptop.
No UDP. A stable public URL for the demo (Cloud Run).

## Open questions for the organisers (Discord #help)

1. Which track would you score this under: Track 5, or Track 2/3?
2. What earns full marks for "effective use of Grok Bot": the Grok API inside the product, Grok Bot driving it
   via MCP, or both?
