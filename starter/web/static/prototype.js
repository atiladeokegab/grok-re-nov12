// These values are intentionally illustrative; this module is imported only with ?mockup=1.
export const prototype = {
  run_id: 'illustrative-prototype', listing_id: 'illustrative-listing', place_id: 'illustrative-place', trust_score: 33,
  place: { id: 'illustrative-place', title: 'Example property assessment', address: 'Illustrative London listing', postcode: 'E14', photos: [{ url: new URL('/static/images/macquarie-exterior.jpg', location.origin).href, source_url: 'https://www.auctionhouse.co.uk/london/auction/lot/152478', caption: 'Reference photograph from an actual source; all check values below are illustrative.' }] },
  counts: { matches: 1, disagrees: 2, unverifiable: 1, flag: 0 },
  claims: [
    { id: 'size-claim', field: 'floor_area', value: 70, unit: 'm²', source: 'listing', doc_span: 'Illustrative listing fixture: advertised floor area' },
    { id: 'epc-claim', field: 'epc_rating', value: 'C', source: 'listing', doc_span: 'Illustrative listing fixture: advertised energy rating' },
    { id: 'postcode-claim', field: 'postcode', value: 'E14', source: 'listing', doc_span: 'Illustrative listing fixture: postcode' },
  ],
  evidence: [
    { id: 'size-record', field: 'floor_area', value: 52, unit: 'm²', source_name: 'Illustrative EPC record', doc_span: 'Illustrative fixture, floor area field. Not a real certificate.', fetched_at: '2026-11-12T19:00:00Z', agent: 'EPC source' },
    { id: 'epc-record', field: 'epc_rating', value: 'E', source_name: 'Illustrative EPC record', doc_span: 'Illustrative fixture, energy rating field. Not a real certificate.', fetched_at: '2026-11-12T19:00:00Z', agent: 'EPC source' },
    { id: 'postcode-record', field: 'postcode', value: 'E14', source_name: 'Illustrative listing record', doc_span: 'Illustrative fixture, postcode field.', fetched_at: '2026-11-12T19:00:00Z', agent: 'Listing source' },
  ],
  findings: [
    { id: 'floor-area', field: 'floor_area', verdict: 'disagrees', claim_id: 'size-claim', evidence_ids: ['size-record'], reasoning: 'The advertised floor area is 70 m². This illustrative register entry records 52 m². Check that both records refer to the same unit.', model: 'Illustrative reasoning' },
    { id: 'energy-rating', field: 'epc_rating', verdict: 'disagrees', claim_id: 'epc-claim', evidence_ids: ['epc-record'], reasoning: 'The advert gives energy rating C; the illustrative certificate gives E.', model: 'Illustrative reasoning' },
    { id: 'postcode', field: 'postcode', verdict: 'matches', claim_id: 'postcode-claim', evidence_ids: ['postcode-record'], reasoning: 'The postcode matches in the two illustrative records.', model: 'Illustrative reasoning' },
    { id: 'review', field: 'reviews', verdict: 'unverifiable', evidence_ids: [], reasoning: 'No attributable tenant review has been retrieved. This is not evidence that reviews are positive.', model: 'Illustrative reasoning' },
  ],
  history: [
    { field: 'rent', previous_value: '£2,100 / month', value: '£2,450 / month', source_name: 'Illustrative advert history', doc_span: 'Illustrative fixture, advert snapshots A and B.', fetched_at: '2026-11-12T19:00:00Z', agent: 'Listing history', advert_id: 'example-B' },
  ],
  sources: [{ name: 'Listing history', status: 'ok', n_evidence: 1 }, { name: 'EPC records', status: 'ok', n_evidence: 2 }, { name: 'Photo matches', status: 'empty', n_evidence: 0 }, { name: 'Tenant reviews', status: 'error', n_evidence: 0 }],
  grok_calls: 0, client_calls: { grok: 0, cursor_sdk: 0, mcp: { grok_bot: 0, cursor: 0, other: 0 } },
};
