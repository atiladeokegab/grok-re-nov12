import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { tickerItems } from './landing.js';

test('ticker shows real flagged rows from the recorded scan, one per address, nothing invented', () => {
  const scan = JSON.parse(readFileSync(new URL('./partner-scan.json', import.meta.url)));
  const items = tickerItems(scan);
  assert.equal(items.length, 20);
  assert.equal(new Set(items.map(i => i.address)).size, 20);
  for (const item of items) {
    const row = scan.flags.find(r => String(r.address).endsWith(item.address) && item.text === `Advert: ${r.advert_value} → Land Registry: ${r.record_label}`);
    assert.ok(row, item.address);
  }
  assert.deepEqual(tickerItems({ flags: [{ listing_id: 'a', address: 'Property for Auction in X - 1 High St', advert_value: 'house', record_label: 'Flat/maisonette' }] }),
    [{ address: '1 High St', text: 'Advert: house → Land Registry: Flat/maisonette' }]);
  assert.deepEqual(tickerItems(null), []);
});
