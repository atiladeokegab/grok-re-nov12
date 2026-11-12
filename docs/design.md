# X-ray design

X-ray compares a property claim with records the user can open. A renter starts with one listing and gets a Trust Score, findings, and a record of what changed. Its signature is the source trail beneath each value: previous value, new value, source, retrieval time, and agent.

The same check covers residential and office property. Residential is the primary demonstration. Office is a secondary path for a deeper question from a judge. Both go through the same X-ray workflow and evidence view.

## Direction contract

The screen reads like a property dossier: a listing photograph beside a clear, direct action, then the listing's evidence record. The photograph earns the first look; source links earn trust. Findings read as a list, not a set of equal feature cards. Selecting one brings the claim, cited record, reasoning and source together. History shows old and current values with their provenance. The opening map is a short route to the place and can always be skipped.

The use scene is a live demonstration on a projected screen, followed by phone use. Near black keeps evidence and property photography legible in a bright room; pale green marks the main action and positive records. Salmon marks disagreement, amber marks an unavailable source. Every verdict also has words and, where applicable, an icon. The green accent alone never means a verdict.

## References and source material

The page uses interaction references rather than copied screens: [HM Land Registry](https://www.gov.uk/search-property-information-land-registry) for traceable records, the [EPC register](https://find-energy-certificate.service.gov.uk/) for address-led evidence, and [The Modern House](https://www.themodernhouse.com/) for giving property photography room.

The approved demonstration listing is [24 Macquarie Way, Isle of Dogs](https://www.auctionhouse.co.uk/london/auction/lot/152478). Its opening photograph is the listing's own [exterior image](https://www.auctionhouse.co.uk/lot-image/930671?w=1200), credited beside the image and self-hosted unchanged. The organisers' crawl was collected on 24 October 2026. The saved source page records the property as sold for £770,000 and EPC D. No verified historical price change has been established; a sold price and guide or asking price have different bases. The image gives location context and is not evidence for prototype findings. Copyright remains with the source photographer; see `starter/web/static/images/SOURCES.md`.

The opening copy is **A listing tells half the story.** The first action is **X-ray this listing**. A prototype fixture is explicitly labelled illustrative and does not claim to assess a real home.

## Tokens and typography

`starter/web/static/tokens.css` owns the provisional visual tokens, and `styles.css` consumes them. The palette is `#080a09` page ground, `#141815` surface, `#f2f5ee` text, `#b4beb2` secondary text, `#b8ed81` accent, `#ffb4a8` disagreement and `#efd18b` unavailable. Status is always written out as well as colored. The display face is Jost Medium; IBM Plex Sans Regular and Semibold carry labels and evidence. Their SIL Open Font License notices are beside the self-hosted font files.

Typography uses 13, 16, 20, 28, 44 and 64px roles, with 16px body text and tabular numerals for results. Spacing uses 4, 8, 12, 16, 24, 32, 48 and 64px; controls use a 6px radius and image or evidence surfaces a 12px radius. A soft shadow token is available, though the current dossier uses dividers and spacing for hierarchy. Focus is visible, controls have at least 44px phone targets, keyboard selection is styled, and reduced-motion preferences are respected.

## Flow

1. Choose Residential or Office, paste a listing URL or crawl ID, and select **X-ray this listing**.
2. See source coverage and the Trust Score update as records arrive. An unavailable source stays unverifiable and is not counted as a match.
3. Select a finding to compare the claim with its cited evidence, reasoning and source.
4. Follow **What changed** to earlier values and their provenance; inspect the source and tool-call counts for this run.

On phone, the 168px source-photo panel sits above the headline and action; findings appear before history in the results. A finding opens in the page and the user can return to the list. The fly-in is optional; reduced motion skips it.

## Screens and states

| State | Content and action |
|---|---|
| Start | **A listing tells half the story.** One property type, one listing field, and **X-ray this listing**. The desktop hero places the action beside a full-panel photograph; phone moves its 168px crop above the headline. The photograph links to its listing. |
| Loading | **Checking the records.** Sources appear as they arrive. The action cannot start a duplicate request. |
| Results | Address, Trust Score, source coverage, findings, change history and this run's Grok Bot/Cursor counts. |
| Evidence | Listing claim, the evidence cited by that finding, reasoning, source URL or document span, retrieval time and agent. |
| Unavailable | **Could not verify.** The reason is shown; unavailable evidence never counts as a match. |
| Error | **The check did not finish.** Keep the input, explain the failed request, and offer a retry. |
| No findings | **No findings have arrived. This is not a verified match.** |
| Prototype | **Illustrative prototype. These values demonstrate the interface; they are not a real property assessment.** |

## Voice and evidence

Say **The listing says 70 m². The register records 52 m².** only when both source records exist. Say **The source is unavailable** when it is not. Never say an image is AI-generated or call a discrepancy fraud; describe the records and their limits. Every displayed claim, value, image, review and finding must retain its source link or document span. Only the prototype may show sample values, with its illustrative label visible.

## Fly-in

The map animates from a city view to the supplied location. The Trust Score remains above the map. A visible **Skip to findings** control and an 8.5-second ceiling keep the check available; reduced motion skips the opener. OpenFreeMap with MapLibre is the current keyless path. If location, WebGL or tiles are unavailable, keep the source photograph and findings. Postcode-centroid coordinates are low confidence and are not represented as the building entrance. Confirm the map and camera on the lead's laptop; software rendering on the VM is not GPU verification.

The map scene uses MapLibre GL JS and OpenFreeMap buildings with OpenStreetMap attribution (ODbL). Google tiles are an optional extension; if integrated, their attribution and promotional footage limits must be preserved.

## Connections, time and original documents

Results have three views: **Findings**, **Connections** and **Time machine**. Connections renders the actual graph returned for this run, with a keyboard-accessible record list beside the 3D view. Finding selection returns to its evidence. The renderer is disposed when its view closes.

Time machine uses sourced history only. Cards distinguish **Source event on** from **Retrieved on**, preserve order within each year and state **Date not recorded** when a date is absent. A retrieval timestamp does not establish when a property changed.

Finding details can show the chain back to an original captured document. The trace exposes the source URL, retrieval time, agent and server-supplied SHA-256. It highlights a quote only when the document ID, current run, original text and Unicode codepoint offsets match the attested span. Otherwise the source remains readable without a verified highlight. An unavailable document never becomes reconstructed evidence.
