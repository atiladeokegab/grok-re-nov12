import assert from 'node:assert/strict';
import test from 'node:test';
import { graphColor, graphSlice, nodeTitle } from './graph.js';

const graph = {
  place_id: 'p1', run_id: 'run-7',
  nodes: [
    { id: 'p1', kind: 'place', data: { title: '24 Macquarie Way' } },
    { id: 'c1', kind: 'claim', data: { field: 'floor_area', value: 70, unit: 'm²' } },
    { id: 'e1', kind: 'evidence', data: { field: 'floor_area', value: 52, unit: 'm²', source_url: 'https://example.test/epc' } },
    { id: 'f1', kind: 'finding', data: { field: 'floor_area', verdict: 'disagrees' } },
    { id: 'orphan', kind: 'document', data: { name: 'Unused document' } },
  ],
  edges: [
    { from: 'p1', to: 'c1', kind: 'has' },
    { from: 'c1', to: 'e1', kind: 'checked_by' },
    { from: 'f1', to: 'e1', kind: 'cites' },
    { from: 'missing', to: 'e1', kind: 'cites' },
  ],
};

test('all view renders only API nodes and edges with existing endpoints', () => {
  const view = graphSlice(graph);
  assert.deepEqual(view.nodes.map(node => node.id), ['p1', 'c1', 'e1', 'f1', 'orphan']);
  assert.deepEqual(view.edges.map(edge => edge.kind), ['has', 'checked_by', 'cites']);
  assert.ok(view.edges.every(edge => view.nodes.some(node => node.id === edge.from) && view.nodes.some(node => node.id === edge.to)));
});

test('source filter retains real source nodes and their direct claim/finding context', () => {
  const view = graphSlice(graph, 'source');
  assert.deepEqual(view.nodes.map(node => node.id), ['c1', 'e1', 'f1', 'orphan']);
  assert.deepEqual(view.edges.map(edge => edge.kind), ['checked_by', 'cites']);
  assert.ok(!view.nodes.some(node => node.kind === 'place'));
});

test('titles stay grounded in the record fields', () => {
  assert.equal(nodeTitle(graph.nodes[0]), '24 Macquarie Way');
  assert.equal(nodeTitle(graph.nodes[2]), 'Floor area: 52 m²');
  assert.equal(nodeTitle(graph.nodes[3]), 'Floor area: Doesn’t match the record');
});

test('bad or absent response becomes an empty graph', () => {
  assert.deepEqual(graphSlice(null), { nodes: [], edges: [] });
  assert.deepEqual(graphSlice({ nodes: [{ kind: 'place' }], edges: [{}] }), { nodes: [], edges: [] });
});

test('finding node colors follow exact verdict values', () => {
  assert.equal(graphColor({ kind: 'finding', data: { verdict: 'matches' } }), '#b8ed81');
  assert.equal(graphColor({ kind: 'finding', data: { verdict: 'disagrees' } }), '#ffb4a8');
  assert.notEqual(graphColor({ kind: 'finding', data: { verdict: 'disagrees' } }), '#b8ed81');
  assert.equal(graphColor({ kind: 'finding', data: { verdict: 'unverifiable' } }), '#efd18b');
  assert.equal(graphColor({ kind: 'finding', data: { verdict: 'flag' } }), '#efd18b');
});
