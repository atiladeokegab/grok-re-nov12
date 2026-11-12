// Who found a fact and when, and how one claim changed across the listing's history: from the run only.
import { valueText, timestamp } from './data.js';
import { agentName } from './agents.js';

const SQFT_PER_M2 = 10.7639;

/** "EPC agent · retrieved 12 Nov 2026, 19:16 UTC" for the cited records ('' when none). */
export function stamp(records) {
  const list = (records || []).filter(Boolean);
  if (!list.length) return '';
  const agents = [...new Set(list.map(r => r.agent).filter(Boolean).map(a => `${agentName(a)} agent`))];
  const times = list.map(r => r.fetched_at).filter(Boolean).sort();
  return [agents.join(', '), times.length ? `retrieved ${timestamp(times[times.length - 1])}` : ''].filter(Boolean).join(' · ');
}

/** The claim's own history rows, oldest first: [{ when, source, text, changed }]. Never invents a change. */
export function claimHistory(history, field) {
  return (history || [])
    .filter(r => r.field === field)
    .sort((a, b) => String(a.fetched_at).localeCompare(String(b.fetched_at)))
    .map(r => {
      const prev = r.previous_value;
      const now = valueText(r.value);
      let text = now;
      let changed = false;
      if (prev !== undefined && prev !== null && !Object.is(prev, r.value)) {
        // shortcut: the crawl kept floor area in sq ft without a unit, the advert in m²; same area is not an edit
        const sameArea = field === 'floor_area' && Math.abs(Number(prev) / SQFT_PER_M2 - Number(r.value)) < 1;
        text = sameArea ? `${valueText(prev)} sq ft = ${now} m², same area in new units` : `${valueText(prev)} → ${now}`;
        changed = !sameArea;
      } else if (prev !== undefined && prev !== null) text = `${now}, unchanged`;
      return { when: timestamp(r.fetched_at), source: r.source_name || 'Source record', text, changed };
    });
}
