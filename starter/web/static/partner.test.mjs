import { test } from 'node:test';
import assert from 'node:assert/strict';
import { countPartnerTotals, filterFlags, validateScan } from './partner.js';

const rows = [
  { listing_id: 'one', check: 'tenure', address: '1 Example Road', advert_value: 'freehold', record_label: 'Leasehold', record_address: 'Flat D, 1 EXAMPLE ROAD' },
  { listing_id: 'two', check: 'property_type', address: '2 Other Street', advert_value: 'flat', record_label: 'Terraced', record_address: '2 OTHER STREET' },
];

test('filters cover all flags by check, address, ID and joined unit without changing the data', () => {
  assert.deepEqual(filterFlags(rows, '', ''), rows);
  assert.deepEqual(filterFlags(rows, 'tenure', '  EXAMPLE '), [rows[0]]);
  assert.deepEqual(filterFlags(rows, '', 'flat d'), [rows[0]]);
  assert.deepEqual(filterFlags(rows, '', 'two'), [rows[1]]);
  assert.deepEqual(filterFlags(rows, 'property_type', 'example'), []);
});

test('an incomplete recorded scan is rejected rather than presenting misleading totals', () => {
  const data = { schema_version: 1, rows_scanned: 3, flagged_listings: 2, flagged_comparisons: 2, flags: rows };
  assert.equal(validateScan(data), data);
  assert.throws(() => validateScan({ ...data, flagged_listings: 1 }), /incomplete/);
  assert.throws(() => validateScan({ ...data, flags: [] }), /incomplete/);
  assert.throws(() => validateScan(null), /incomplete/);
});


test('partner count-up owns its spans, ends on the exact text, and honors reduced motion', () => {
  const original = { matchMedia: globalThis.matchMedia, requestAnimationFrame: globalThis.requestAnimationFrame, performance: globalThis.performance };
  try {
    const frames = [];
    globalThis.matchMedia = () => ({ matches: true });
    globalThis.requestAnimationFrame = callback => frames.push(callback);
    globalThis.performance = { now: () => 100 };
    const total = { textContent: '7,251', dataset: { count: '7251' } };
    countPartnerTotals([total]);
    assert.equal(total.dataset.countAnimated, 'true');
    assert.equal(total.textContent, '0');
    frames.shift()(600);
    assert.equal(total.textContent, '6,345');
    frames.shift()(1100);
    assert.equal(total.textContent, '7,251');
    assert.equal(frames.length, 0);
    globalThis.matchMedia = () => ({ matches: false });
    const flagged = { textContent: '350', dataset: { count: '350' } };
    countPartnerTotals([flagged]);
    assert.equal(flagged.textContent, '350');
    assert.equal(frames.length, 0);
  } finally {
    Object.assign(globalThis, original);
  }
});
