import { test } from 'node:test';
import assert from 'node:assert/strict';
import { exactSpan } from './trace.js';

test('server-attested span offsets match exact source text in Unicode code points', () => {
  assert.deepEqual(exactSpan('🏠 area 52 m²', { start: 7, end: 12, quote: '52 m²' }), { start: 7, end: 12 });
  const repeated = '🏠 quote / quote';
  assert.deepEqual(exactSpan(repeated, { start: 10, end: 15, quote: 'quote' }), { start: 10, end: 15 });
  assert.equal(exactSpan(repeated, { start: 3, end: 8, quote: 'quote' }), null);
  assert.deepEqual(exactSpan('text <script>alert(1)</script>', { start: 5, end: 30, quote: '<script>alert(1)</script>' }), { start: 5, end: 30 });
  assert.equal(exactSpan('source text', { start: 0, end: 0, quote: '' }), null);
});
