import assert from 'node:assert/strict';
import test from 'node:test';
import { packRooms, splitFloors, advertMoney, isoScene, insideStats } from './inside.js';

const kimberley = [
  ['Living Room', 6.9, 3.9], ['Kitchen', 2.9, 1.8], ['Bathroom', 1.8, 1.3], ['Bedroom 1', 3.9, 2.9],
  ['Bedroom 2', 3.5, 2.9], ['Dressing Room', 2.5, 1.8], ['Ensuite', 1.8, 1.5],
].map(([name, width_m, length_m]) => ({ name, width_m, length_m, area_m2: width_m * length_m }));

test('packRooms keeps every room to scale, inside the footprint, with no overlaps', () => {
  const pack = packRooms(kimberley);
  assert.equal(pack.rooms.length, 7);
  for (const r of pack.rooms) {
    assert.ok(Math.abs(r.w * r.h - r.width_m * r.length_m) < 1e-9);
    assert.ok(r.x >= 0 && r.y >= 0 && r.x + r.w <= pack.width + 1e-9 && r.y + r.h <= pack.height + 1e-9);
  }
  for (const a of pack.rooms) for (const b of pack.rooms) {
    if (a === b) continue;
    const overlap = a.x < b.x + b.w - 1e-9 && b.x < a.x + a.w - 1e-9 && a.y < b.y + b.h - 1e-9 && b.y < a.y + a.h - 1e-9;
    assert.ok(!overlap, `${a.name} overlaps ${b.name}`);
  }
  assert.ok(pack.width / pack.height < 4 && pack.height / pack.width < 4, 'roughly square');
  assert.deepEqual(packRooms([{ name: 'Nothing', width_m: 0, length_m: 3 }]).rooms, []);
});

test('splitFloors puts bedrooms upstairs only when the advert names an upper floor', () => {
  assert.deepEqual(splitFloors(kimberley, 'To the first floor are 2 x bedrooms').map(f => f.rooms.length), [3, 4]);
  assert.equal(splitFloors(kimberley, 'a flat').length, 1);
});

test('advertMoney reads rent, deposit and fees from the advert words', () => {
  const m = advertMoney('Administration Charge - Purchasers will pay an Administration fee of 1% (inc VAT) of the sale price, subject to a minimum of £1,750 (inc VAT) Disbursements. Rent £1,200 pcm. A deposit of £1,384 is payable.');
  assert.match(m.fees[0], /Administration fee of 1%.*£1,750 \(inc VAT\)/);
  assert.match(m.rent, /£1,200 pcm/);
  assert.match(m.deposit, /deposit of £1,384/);
  assert.deepEqual(advertMoney('Guide price £770,000'), { rent: null, deposit: null, fees: [] });
});

test('isoScene stacks the first floor above the ground floor and draws every room as a floor and four walls', () => {
  const floors = splitFloors(kimberley, 'To the first floor are 2 x bedrooms');
  for (const angle of [0, 1.3, 4]) {
    const levels = isoScene(floors, angle);
    assert.equal(levels.length, 2);
    assert.ok(levels[1].z > levels[0].z + 2.4, 'first floor sits above the walls of the ground floor');
    assert.deepEqual(levels.map(l => l.faces.length), [3 * 5, 4 * 5]);
    for (const l of levels) {
      assert.equal(l.labels.length, l.faces.length / 5);
      assert.equal(l.faces.filter(f => f.kind === 'near').length + l.faces.filter(f => f.kind === 'far').length, l.labels.length * 4);
      assert.ok(l.faces.filter(f => f.kind === 'near').length >= l.labels.length, 'each room shows at least one wall to the viewer');
    }
  }
});

test('insideStats turns the run into big figures with their sources', () => {
  const result = {
    claims: [{ field: 'floor_area', value: 81, source: 'listing', source_url: 'https://a.example/1' }],
    evidence: [{ field: 'floor_area', agent: 'epc', value: 72, source_url: 'https://epc.example' }, { field: 'energy_rating', agent: 'epc', value: 'D', source_url: 'https://epc.example' }],
  };
  const stats = insideStats(result, 'Administration fee of 1% (inc VAT), minimum of £1,750 (inc VAT). Council Tax - Band E', { rooms_m2: 63.1 });
  const by = Object.fromEntries(stats.map(s => [s.label, s]));
  assert.equal(by['m² advert'].big, '81');
  assert.equal(by['m² rooms'].big, '63.1');
  assert.equal(by['m² register'].big, '72');
  assert.equal(by['energy rating'].big, 'D');
  assert.equal(by.fees.big, '1% · £1,750');
  assert.equal(by['council tax band'].big, 'E');
  assert.equal(by['m² register'].url, 'https://epc.example');
});
