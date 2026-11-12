import { test } from 'node:test';
import assert from 'node:assert/strict';
import { score, facts, csvRows, combineCSV } from './analyst.js';

test('an absent score stays unscored; zero remains a real score', () => {
  for (const value of [null, undefined, '', '67', NaN, Infinity, -1, 101]) assert.equal(score(value), null);
  for (const value of [0, 67, 100]) assert.equal(score(value), value);
});

test('comparison uses current independent EPC facts and keeps room totals separate', () => {
  const advert = { field: 'floor_area', value: 81, source_url: 'https://advert.example' };
  const epc = { field: 'floor_area', value: 72, agent: 'epc', source_url: 'https://epc.example' };
  const rooms = { field: 'room_schedule', value: { rooms_m2: 61.9 }, agent: 'floor_plan', source_url: 'https://advert.example' };
  const result = facts({ claims: [advert], evidence: [
    { ...epc, value: 90, observed_at: '2020-01-01' },
    { ...epc, agent: 'listing_history', value: 81 }, epc, rooms,
  ] });
  assert.equal(result.advertArea, advert);
  assert.equal(result.epcArea, epc);
  assert.equal(result.rooms, rooms);
  assert.equal(result.price, undefined);
});

test('values without a source URL or recorded quote remain unavailable', () => {
  const result = facts({ claims: [{ field: 'price', value: 12, source_url: 'javascript:alert(1)' }], evidence: [{ agent: 'epc', field: 'floor_area', value: 90, source_name: 'EPC' }] });
  assert.equal(result.price, undefined);
  assert.equal(result.epcArea, undefined);
});

test('CSV parsing preserves quoted excerpts, commas, CRLF and escaped quotes', () => {
  assert.deepEqual(csvRows('kind,words\r\nevidence,"a, b\nsaid ""hello"""\r\n'), [
    ['kind', 'words'], ['evidence', 'a, b\nsaid "hello"'],
  ]);
  assert.throws(() => csvRows('kind,words\nevidence,"unfinished'), /incomplete/);
});

test('all exports retain their listing and run identity under one header', () => {
  const result = combineCSV([
    { listing: { title: 'One, Road' }, report: { listing_id: 'one', run_id: 'xr-one' }, text: 'kind,words\r\nevidence,"first\nline"\r\n' },
    { listing: { title: 'Two Road' }, report: { listing_id: 'two', run_id: 'xr-two' }, text: 'kind,words\r\nclaim,"said ""two"""\r\n' },
  ]);
  assert.deepEqual(csvRows(result), [
    ['listing', 'listing_id', 'run_id', 'kind', 'words'],
    ['One, Road', 'one', 'xr-one', 'evidence', 'first\nline'],
    ['Two Road', 'two', 'xr-two', 'claim', 'said "two"'],
  ]);
});

test('source text cannot execute a spreadsheet formula', () => {
  const result = csvRows(combineCSV([{ listing: { title: '=HYPERLINK("https://bad.example")' }, report: { listing_id: 'one', run_id: 'xr-one' }, text: 'kind,words\nevidence,   =1+1\n' }]));
  assert.equal(result[1][0], '\'=HYPERLINK("https://bad.example")');
  assert.equal(result[1][4], "'   =1+1");
});

test('incompatible or broken exports fail instead of producing a partial download', () => {
  const base = { listing: { title: 'One' }, report: { listing_id: 'one', run_id: 'xr-one' } };
  assert.throws(() => combineCSV([{ ...base, text: 'kind,words\nevidence,one\n' }, { ...base, text: 'different\none\n' }]), /different columns/);
  assert.throws(() => combineCSV([{ ...base, text: 'kind,words\nevidence\n' }]), /incomplete row/);
});
