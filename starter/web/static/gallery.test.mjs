import { test } from 'node:test';
import assert from 'node:assert/strict';
import { discrepancyLabel, galleryItems, savedGalleryItems } from './gallery.js';

test('each discrepancy type reads in plain words', () => {
  assert.equal(discrepancyLabel('price_history'), 'Price changed since the crawl');
  assert.equal(discrepancyLabel('photo_reuse'), 'Photos reused from another advert');
  assert.equal(discrepancyLabel('area_type'), 'Floor area disagrees with the EPC');
  assert.equal(discrepancyLabel('new_kind'), 'new kind');
});

test('gallery and analyst share the canonical saved runs without starting new checks', () => {
  const items = savedGalleryItems([
    { name: 'kimberley-road', title: 'Kimberley', listing_id: 'one', run_id: 'xr-old' },
    { name: 'charlemont-road', title: 'Charlemont', listing_id: 'two' },
    { name: 'sleaford-house', title: 'Sleaford', listing_id: 'three' },
  ]);
  assert.equal(items[0].name, 'macquarie-way');
  assert.deepEqual(items.map(item => item.run_id), ['xr-6f65393159', 'xr-131a92ee3b', 'xr-f20b9504d5', undefined]);
  assert.equal(savedGalleryItems(items).length, 4);
});

test('only items with a name and title are offered', () => {
  const ok = { name: 'kimberley-road', title: '24 Kimberley Road', discrepancy: 'area_type' };
  assert.deepEqual(galleryItems([ok, { title: 'no name' }, null, { name: 'x' }]), [ok]);
  assert.deepEqual(galleryItems({ detail: 'nope' }), []);
});
