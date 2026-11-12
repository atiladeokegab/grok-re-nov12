import { test } from 'node:test';
import assert from 'node:assert/strict';
import { agentLines, agentName } from './agents.js';

test('one plain line per agent from the run, then the reconciler', () => {
  const result = {
    sources: [
      { name: 'epc', status: 'ok' }, { name: 'companies_house', status: 'off', detail: 'offline' }, { name: 'tenant_voices', status: 'off' },
      { name: 'floor_plan', status: 'error', detail: 'timed out after 10 s' }, { name: 'listing_history', status: 'ok' },
    ],
    evidence: [
      { agent: 'epc', field: 'energy_rating', value: 'D', source_name: 'EPC register' },
      { agent: 'epc', field: 'floor_area', value: 84, unit: 'm2', source_name: 'EPC register' },
    ],
    findings: [{}], counts: { matches: 1, disagrees: 1, unverifiable: 1, flag: 0 }, trust_score: 67,
  };
  const { lines, off } = agentLines(result);
  assert.deepEqual(lines.map(l => `${l.agent}: ${l.text}`), [
    'EPC agent: Read EPC register: energy rating D, floor area 84 m².',
    'Floor plan agent: Could not finish (timed out after 10 s).',
    'Listing history agent: Found no record.',
    'Reconciler: Compared the advert with the records: 1 matched, 1 disagreed, 1 could not be verified, Trust Score 67.',
  ]);
  assert.deepEqual(off, ['Companies House agent']);
  assert.equal(agentName('new_source'), 'New source agent');
});
