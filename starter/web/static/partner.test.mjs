import { test } from 'node:test';
import assert from 'node:assert/strict';
import { filterFlags, validateScan } from './partner.js';

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
