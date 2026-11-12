import { test } from 'node:test';
import assert from 'node:assert/strict';
import { placeTiles, dateText } from './places.js';

const manifest = {
  listing_id: 'auctionhouse-0715ecf1', attribution: 'Imagery © Google',
  tiles: [
    { kind: 'satellite', file: 'satellite.jpg', label: 'From above', source: 'Google satellite', date: '2026-11-12', date_note: 'fetched', credit: 'Imagery ©2026 Airbus', focus: '40% 72%', url: 'https://www.google.com/maps/@?api=1' },
    { kind: 'streetview', file: 'streetview.jpg', label: 'The front', source: 'Google Street View', date: '2022-05', date_note: 'captured', url: 'https://www.google.com/maps/@?api=1&map_action=pano' },
    { kind: 'map', file: 'map.jpg', label: 'On the map', source: 'Google Maps', date: '2026-11-12', date_note: 'fetched', url: 'javascript:alert(1)' },
    { kind: 'bad', file: '../../secret.jpg' },
  ],
};
const result = { place: { photos: [{ url: 'https://www.auctionhouse.co.uk/lot-image/930671', advert_id: 'auctionhouse-0715ecf1' }, { url: 'nope' }] } };

test('Street View leads as the hero, saved files first, then the advert photos', () => {
  const tiles = placeTiles(manifest, result);
  assert.deepEqual(tiles.map(t => t.src), [
    '/static/images/places/auctionhouse-0715ecf1/streetview.jpg',
    '/static/images/places/auctionhouse-0715ecf1/satellite.jpg',
    '/static/images/places/auctionhouse-0715ecf1/map.jpg',
    'https://www.auctionhouse.co.uk/lot-image/930671',
  ]);
  assert.deepEqual(tiles.map(t => t.size), ['hero', '', '', 'wide']);
  assert.equal(tiles[0].date, 'Captured May 2022');
  assert.equal(tiles[1].date, 'Fetched 12 Nov 2026');
  assert.equal(tiles[2].url, null, 'an unsafe link is dropped');
  assert.equal(tiles[0].attribution, 'Imagery © Google');
  assert.equal(tiles[1].attribution, 'Imagery ©2026 Airbus', 'the session copyright is shown as given');
  assert.equal(tiles[1].focus, '40% 72%');
  assert.equal(tiles[3].attribution, '', 'the advert photo is not credited to Google');
});

test('no saved imagery hides the strip, even with advert photos', () => {
  assert.deepEqual(placeTiles(null, result), []);
  assert.deepEqual(placeTiles({ listing_id: 'x', tiles: [] }, result), []);
});

test('dates read in plain words', () => {
  assert.equal(dateText('2019-07'), 'Jul 2019');
  assert.equal(dateText(''), '');
});
