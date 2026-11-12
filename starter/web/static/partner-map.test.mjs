import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mapPoints } from './partner-map.js';

test('all listings stay represented, duplicate checks share one dot, missing locations stay separate', () => {
  const flags = [{ listing_id: 'one', check: 'tenure' }, { listing_id: 'one', check: 'property_type' }];
  const points = mapPoints({ flags, map_points: [['one', 51.5, -.12], ['two', null, null], ['three', null, null]] });
  assert.equal(points.length, 3);
  assert.equal(points.filter(p => p.flags.length).length, 1);
  assert.equal(points[0].flags.length, 2);
  assert.equal(points[0].located, true);
  assert.equal(points[1].located, false);
  assert.equal(points[1].region, 5);
  assert.ok(points[1].y > points[0].y);
  assert.notEqual(points[1].x, points[2].x);
});
