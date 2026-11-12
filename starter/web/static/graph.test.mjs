import assert from 'node:assert/strict';
import test from 'node:test';
import { agentName, label, nodeTitle, plainValue, quoteOf, storyRows } from './graph.js';

const graph = {
  place_id: 'p1', run_id: 'run-7',
  nodes: [
    { id: 'p1', kind: 'place', data: { address: '24 Macquarie Way, Isle of Dogs' } },
    { id: 'c1', kind: 'claim', data: { field: 'property_type', value: 'Semi-Detached', doc_span: 'Semi-Detached House' } },
    { id: 'c2', kind: 'claim', data: { field: 'price', value: 770000, unit: 'GBP' } },
    { id: 'c3', kind: 'claim', data: { field: 'energy_rating', value: 'D' } },
    { id: 'e1', kind: 'evidence', data: { field: 'property_type', value: 'End-terrace house', source_name: 'EPC register', agent: 'epc', span: { quote: 'Property type End-terrace house' } } },
    { id: 'e2', kind: 'evidence', data: { field: 'floor_area', value: 84, unit: 'm2', source_name: 'EPC register' } },
    { id: 'e3', kind: 'evidence', data: { field: 'energy_rating', value: 'D', source_name: 'EPC register' } },
    { id: 'e4', kind: 'evidence', data: { field: 'tenure', value: 'Freehold', source_name: 'Listing history' } },
    { id: 'f-match', kind: 'finding', data: { field: 'energy_rating', verdict: 'matches', claim_id: 'c3', evidence_ids: ['e3'] } },
    { id: 'f-flag', kind: 'finding', data: { field: 'floor_area', verdict: 'flag', claim_id: null, evidence_ids: ['e2'] } },
    { id: 'f-bad', kind: 'finding', data: { field: 'property_type', verdict: 'disagrees', claim_id: 'c1', evidence_ids: ['e1'] } },
    { id: 'f-none', kind: 'finding', data: { field: 'tenure', verdict: 'unverifiable', claim_id: 'c9', evidence_ids: [] } },
    { id: 'd1', kind: 'document', data: { url: 'https://example.test/epc' } },
  ],
  edges: [
    { from: 'p1', to: 'c1', kind: 'has' },
    { from: 'f-bad', to: 'e1', kind: 'cites' },
    { from: 'f-flag', to: 'e2', kind: 'cites' },
    { from: 'f-match', to: 'e3', kind: 'cites' },
    { from: 'missing', to: 'e1', kind: 'cites' },
  ],
};

test('one row per finding, the disagreement first and the match last', () => {
  const story = storyRows(graph);
  assert.deepEqual(story.rows.map(row => row.verdict), ['disagrees', 'flag', 'unverifiable', 'matches']);
  const bad = story.rows[0];
  assert.equal(bad.claim.id, 'c1');
  assert.deepEqual(bad.evidence.map(node => node.id), ['e1']);
});

test('a finding with no advert claim or no evidence leaves that side empty, never invented', () => {
  const [, flag, none] = storyRows(graph).rows;
  assert.equal(flag.claim, null);
  assert.deepEqual(flag.evidence.map(node => node.id), ['e2']);
  assert.equal(none.claim, null);
  assert.deepEqual(none.evidence, []);
});

test('records no finding uses are kept aside, not dropped', () => {
  const story = storyRows(graph);
  assert.deepEqual(story.otherClaims.map(node => node.id), ['c2']);
  assert.deepEqual(story.otherEvidence.map(node => node.id), ['e4']);
  assert.equal(story.place.id, 'p1');
});

test('labels are plain English: field names, units, no raw keys or JSON', () => {
  assert.equal(label('property_type'), 'Property type');
  assert.equal(label('bedrooms'), 'Bedrooms');
  assert.equal(label('epc_valid_until'), 'Certificate valid until');
  assert.equal(plainValue({ value: 84, unit: 'm2' }), '84 m²');
  assert.equal(plainValue({ value: 770000, unit: 'GBP' }), '£770,000');
  assert.equal(plainValue({ value: { rooms: [{}, {}], rooms_m2: 63.14 }, unit: 'm2' }), '2 rooms, 63.1 m²');
  assert.equal(plainValue({ value: { advert_id: 'x' } }), '');
  assert.equal(nodeTitle(graph.nodes[0]), '24 Macquarie Way, Isle of Dogs');
  assert.equal(nodeTitle(graph.nodes[4]), 'Property type: End-terrace house');
  assert.equal(nodeTitle(graph.nodes.find(node => node.id === 'f-bad')), 'Property type: Doesn’t match the record');
  assert.equal(agentName('epc'), 'EPC agent');
  assert.equal(agentName('listing_history'), 'Listing history agent');
});

test('the quote prefers the exact span over the document excerpt', () => {
  assert.equal(quoteOf(graph.nodes[4].data), 'Property type End-terrace house');
  assert.equal(quoteOf(graph.nodes[1].data), 'Semi-Detached House');
  assert.equal(quoteOf({}), '');
});

test('bad or absent response becomes an empty story', () => {
  for (const bad of [null, {}, { nodes: [{ kind: 'place' }], edges: [{}] }]) {
    const story = storyRows(bad);
    assert.deepEqual([story.rows, story.otherClaims, story.otherEvidence, story.place], [[], [], [], null]);
  }
});
