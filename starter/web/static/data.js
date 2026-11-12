export const FIELD_NAMES = { property_type: 'Property type', tenure: 'Tenure', floor_area: 'Floor area', size: 'Floor area', epc: 'Energy rating', epc_rating: 'Energy rating', energy_rating: 'Energy rating', price: 'Price', rent: 'Rent', photos: 'Listing photos', photo: 'Listing photo', photo_reuse: 'Photo match', photo_history: 'Photo history', tenant_reviews: 'Tenant reviews', reviews: 'Tenant reviews', price_basis: 'Price basis' };
export const VERDICTS = { matches: 'Matches the record', disagrees: 'Doesn’t match the record', unverifiable: 'Could not verify', flag: 'Worth a closer look' };

export function fieldName(field) {
  return FIELD_NAMES[field] || String(field || 'Property claim').replaceAll('_', ' ');
}

export function safeUrl(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

export function valueText(value, unit) {
  const text = value === null || value === undefined ? 'Not recorded' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  return unit ? `${text} ${unit}` : text;
}

export function sourcePresent(record) {
  return Boolean(record && (safeUrl(record.source_url) || (typeof record.doc_span === 'string' && record.doc_span.trim())));
}

export function safeImageUrl(value) {
  const url = safeUrl(value);
  return url?.startsWith('https:') ? url : null;
}

export function photoChange(record) {
  if (!record || record.field !== 'photo_history' || !record.value || typeof record.value !== 'object') return null;
  const { previous_advert_id, advert_id, removed, added } = record.value;
  const oldPhoto = Array.isArray(removed) ? removed.map(safeImageUrl).find(Boolean) : null;
  const newPhoto = Array.isArray(added) ? added.map(safeImageUrl).find(Boolean) : null;
  return oldPhoto && newPhoto && previous_advert_id && advert_id
    ? { oldPhoto, newPhoto, previous_advert_id, advert_id }
    : null;
}

export function unitFor(result, field, value) {
  return [...(result.claims || []), ...(result.evidence || [])]
    .find(record => record.field === field && Object.is(record.value, value) && record.unit)?.unit;
}

export function findingRecords(finding, result) {
  return {
    claim: (result.claims || []).find(item => item.id === finding.claim_id),
    evidence: (result.evidence || []).filter(item => (finding.evidence_ids || []).includes(item.id)),
  };
}

export function sourceLabel(record) {
  return record.source_name || record.source || 'Source record';
}

export function timestamp(value) {
  if (!value) return 'Time not recorded';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time not recorded' : `${date.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })} UTC`;
}
