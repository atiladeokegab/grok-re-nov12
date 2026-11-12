// One plain line per source agent saying what it did, built only from the run's sources and evidence.
import { fieldName, valueText } from './data.js';

const NAMES = { listing_history: 'Listing history agent', epc: 'EPC agent', companies_house: 'Companies House agent', photo_reuse: 'Photo agent', floor_plan: 'Floor plan agent', tenant_voices: 'Renters agent' };
const MAX_VALUES = 3;
const PARKED = new Set(['tenant_voices']); // no recordings yet: an off source we don't pitch

export function agentName(source) {
  return NAMES[source] || `${String(source).replaceAll('_', ' ').replace(/^./, c => c.toUpperCase())} agent`;
}

const shown = e => (e.field === 'room_schedule' || e.field === 'photo_reuse' ? fieldName(e.field).toLowerCase() : `${fieldName(e.field).toLowerCase()} ${valueText(e.value, e.unit === 'm2' ? 'm²' : e.unit)}`);

/** [{ agent, status, text }] for every source that ran, then the reconciler; sources that were off are listed by name. */
export function agentLines(result) {
  const evidence = result?.evidence || [];
  const lines = [];
  const off = [];
  for (const s of result?.sources || []) {
    if (s.status === 'off') { if (!PARKED.has(s.name)) off.push(agentName(s.name)); continue; }
    const mine = evidence.filter(e => e.agent === s.name || (!e.agent && e.id?.includes(s.name)));
    let text;
    if (s.status === 'error') text = `Could not finish${s.detail ? ` (${String(s.detail).slice(0, 120)})` : ''}.`;
    else if (!mine.length) text = s.detail ? `Found no record (${String(s.detail).slice(0, 120)}).` : 'Found no record.';
    else {
      const from = [...new Set(mine.map(e => e.source_name).filter(Boolean))].join(', ') || 'its source';
      const values = mine.slice(0, MAX_VALUES).map(shown).join(', ');
      const more = mine.length > MAX_VALUES ? ` and ${mine.length - MAX_VALUES} more` : '';
      text = `Read ${from}: ${values}${more}.`;
    }
    lines.push({ agent: agentName(s.name), status: s.status, text });
  }
  const c = result?.counts;
  if (c && (result.findings || []).length) {
    const parts = [[c.matches, 'matched'], [c.disagrees, 'disagreed'], [c.unverifiable, 'could not be verified'], [c.flag, 'worth a closer look']].filter(([n]) => n).map(([n, w]) => `${n} ${w}`);
    const score = Number.isFinite(result.trust_score) ? `, Trust Score ${result.trust_score}` : '';
    lines.push({ agent: 'Reconciler', status: 'ok', text: `Compared the advert with the records: ${parts.join(', ') || 'nothing to compare'}${score}.` });
  }
  return { lines, off };
}
