// What each source agent did, as compact chips: the agent's short name and its facts, from the run only.
import { valueText } from './data.js';

const NAMES = { listing_history: 'Listing', epc: 'EPC', companies_house: 'Companies House', photo_reuse: 'Photos', floor_plan: 'Floor plan', tenant_voices: 'Area comments', similar_listings: 'Comparables' };
const PARKED = new Set(['tenant_voices']); // an off source we don't pitch
const MAX_FACTS = 3;
const MAX_CHARS = 28;

export function agentName(source) {
  return NAMES[source] || String(source).replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
}

function fact(e) {
  if (e.field === 'photo_reuse') return `${e.value} photos reused`;
  const text = valueText(e.value, e.unit === 'm2' ? 'm²' : e.unit === 'GBP' ? 'GBP' : e.unit);
  return text.length > MAX_CHARS ? `${text.slice(0, MAX_CHARS - 1)}…` : text;
}

/** { chips: [{ agent, status, text }], off: [names] }: one chip per source that ran, then the reconciler. */
export function agentChips(result) {
  const evidence = result?.evidence || [];
  const chips = [];
  const off = [];
  for (const s of result?.sources || []) {
    if (s.status === 'off') { if (!PARKED.has(s.name)) off.push(agentName(s.name)); continue; }
    const mine = evidence.filter(e => e.agent === s.name);
    const text = s.status === 'error' ? 'could not finish' : mine.length ? [...new Set(mine.map(fact))].slice(0, MAX_FACTS).join(', ') : 'no record';
    chips.push({ agent: agentName(s.name), status: s.status, text });
  }
  const c = result?.counts;
  if (c && (result.findings || []).length) {
    const parts = [[c.matches, 'match'], [c.disagrees, 'mismatch'], [c.unverifiable, 'unverified'], [c.flag, 'to look at']].filter(([n]) => n).map(([n, w]) => `${n} ${w}`);
    if (Number.isFinite(result.trust_score)) parts.push(`score ${result.trust_score}`);
    chips.push({ agent: 'Reconciler', status: 'ok', text: parts.join(', ') });
  }
  return { chips, off };
}
