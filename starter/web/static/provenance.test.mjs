import { test } from 'node:test';
import assert from 'node:assert/strict';
import { stamp, claimHistory } from './provenance.js';

test('stamp names the agents and the latest retrieval time', () => {
  assert.equal(stamp([{ agent: 'epc', fetched_at: '2026-11-12T19:16:00+00:00' }, { agent: 'epc', fetched_at: '2026-11-12T18:00:00+00:00' }]), 'EPC agent · retrieved 12 Nov 2026, 19:16 UTC');
  assert.equal(stamp([]), '');
});

test('claim history shows real edits before → after, unit conversions and repeats as such', () => {
  const rows = claimHistory([
    { field: 'floor_area', value: 81, previous_value: 872, source_name: 'Advert', fetched_at: '2026-11-12T20:16:46+00:00' },
    { field: 'floor_area', value: 872, previous_value: null, source_name: 'Crawl', fetched_at: '2026-10-24T20:43:26+00:00' },
    { field: 'price', value: 770000, previous_value: 750000, fetched_at: '2026-11-12T19:16:00+00:00' },
    { field: 'tenure', value: 'Freehold', previous_value: 'Freehold', fetched_at: '2026-11-12T19:16:00+00:00' },
  ], 'floor_area');
  assert.deepEqual(rows.map(r => [r.source, r.text, r.changed]), [['Crawl', '872', false], ['Advert', '872 sq ft = 81 m², same area in new units', false]]);
  assert.equal(claimHistory([{ field: 'price', value: 770000, previous_value: 750000 }], 'price')[0].changed, true);
  assert.match(claimHistory([{ field: 'tenure', value: 'Freehold', previous_value: 'Freehold' }], 'tenure')[0].text, /unchanged/);
});
