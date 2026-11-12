import { test } from 'node:test';
import assert from 'node:assert/strict';
import { discrepancyLabel, galleryItems } from './gallery.js';

test('each discrepancy type reads in plain words', () => {
  assert.equal(discrepancyLabel('price_history'), 'Price changed since the crawl');
  assert.equal(discrepancyLabel('photo_reuse'), 'Photos reused from another advert');
  assert.equal(discrepancyLabel('area_type'), 'Floor area disagrees with the EPC');
  assert.equal(discrepancyLabel('new_kind'), 'new kind');
});

test('only items with a name and title are offered', () => {
  const ok = { name: 'kimberley-road', title: '24 Kimberley Road', discrepancy: 'area_type' };
  assert.deepEqual(galleryItems([ok, { title: 'no name' }, null, { name: 'x' }]), [ok]);
  assert.deepEqual(galleryItems({ detail: 'nope' }), []);
});
