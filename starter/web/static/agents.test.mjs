import { test } from 'node:test';
import assert from 'node:assert/strict';
import { agentChips, agentName } from './agents.js';

test('one compact chip per agent from the run, then the reconciler', () => {
  const result = {
    sources: [
      { name: 'epc', status: 'ok' }, { name: 'companies_house', status: 'off' }, { name: 'tenant_voices', status: 'off' },
      { name: 'floor_plan', status: 'error', detail: 'timed out after 10 s' }, { name: 'listing_history', status: 'ok' },
      { name: 'photo_reuse', status: 'ok' },
    ],
    evidence: [
      { agent: 'epc', field: 'energy_rating', value: 'D' },
      { agent: 'epc', field: 'property_type', value: 'End-terrace house' },
      { agent: 'epc', field: 'floor_area', value: 84, unit: 'm2' },
      { agent: 'epc', field: 'epc_valid_until', value: '2 March 2030' },
      { agent: 'photo_reuse', field: 'photo_reuse', value: 7 },
    ],
    findings: [{}], counts: { matches: 1, disagrees: 1, unverifiable: 1, flag: 0 }, trust_score: 67,
  };
  const { chips, off } = agentChips(result);
  assert.deepEqual(chips.map(c => `${c.agent} · ${c.text}`), [
    'EPC · D, End-terrace house, 84 m²',
    'Floor plan · could not finish',
    'Listing · no record',
    'Photos · 7 photos reused',
    'Reconciler · 1 match, 1 mismatch, 1 unverified, score 67',
  ]);
  assert.deepEqual(off, ['Companies House']);
  assert.equal(agentName('new_source'), 'New source');
});
