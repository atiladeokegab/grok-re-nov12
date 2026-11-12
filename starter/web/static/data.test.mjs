import { test } from 'node:test';
import assert from 'node:assert/strict';
import { safeUrl, safeImageUrl, sourcePresent, findingRecords, valueText, photoChange, unitFor, hasChangedValue } from './data.js';

test('source links reject executable schemes, credentials and malformed URLs', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,test', 'https://user:password@example.com', '/missing', undefined]) assert.equal(safeUrl(value), null);
  assert.equal(safeUrl('https://example.com/certificate/123'), 'https://example.com/certificate/123');
});

test('a source name alone cannot support a displayed value', () => {
  assert.equal(sourcePresent({ source_name: 'Register', value: 52 }), false);
  assert.equal(sourcePresent({ doc_span: 'certificate.pdf page 2', value: 52 }), true);
  assert.equal(sourcePresent({ doc_span: '  ', source_name: 'Register', value: 52 }), false);
  assert.equal(sourcePresent({ source_url: 'javascript:alert(1)', value: 52 }), false);
});

test('only cited HTTPS photo evidence forms an old/new listing comparison', () => {
  assert.deepEqual(photoChange({ field: 'photo_history', value: {
    previous_advert_id: 'old', advert_id: 'new', removed: ['https://images.test/old.jpg'], added: ['https://images.test/new.jpg'],
  } }), {
    oldPhoto: 'https://images.test/old.jpg', newPhoto: 'https://images.test/new.jpg', previous_advert_id: 'old', advert_id: 'new',
  });
  assert.equal(photoChange({ field: 'photo_history', value: { previous_advert_id: 'old', advert_id: 'new', removed: ['http://images.test/old.jpg'], added: ['https://images.test/new.jpg'] } }), null);
  assert.equal(photoChange({ field: 'photo_history', value: { previous_advert_id: 'old', advert_id: 'new', removed: [], added: ['https://images.test/new.jpg'] } }), null);
  assert.equal(safeImageUrl('http://images.test/x.jpg'), null);
});

test('finding detail only joins the claim and evidence explicitly cited by the finding', () => {
  const claim = { id: 'claim' }, evidence = { id: 'cited' };
  assert.deepEqual(findingRecords({ claim_id: 'claim', evidence_ids: ['cited'] }, { claims: [claim], evidence: [{ id: 'unrelated' }, evidence] }), { claim, evidence: [evidence] });
  assert.equal(valueText(0, 'm²'), '0 m²');
  assert.equal(valueText(null), 'Not recorded');
  assert.equal(valueText(770000, 'GBP'), '£770,000');
  assert.equal(unitFor({ claims: [{ field: 'floor_area', value: 70, unit: 'm²' }], evidence: [] }, 'floor_area', 70), 'm²');
});

test('identical or initial values are records rather than changes', () => {
  assert.equal(hasChangedValue({ previous_value: 770000, value: 770000 }), false);
  assert.equal(hasChangedValue({ previous_value: 'Sold', value: 'Sold' }), false);
  assert.equal(hasChangedValue({ previous_value: 0, value: 0 }), false);
  assert.equal(hasChangedValue({ previous_value: null, value: 84 }), false);
  assert.equal(hasChangedValue({ value: 84 }), false);
  assert.equal(hasChangedValue({ previous_value: 0, value: 1 }), true);
});

test('a run link round-trips through the URL and keeps the other parameters', async () => {
  const { runFromSearch, withRun } = await import('./data.js');
  assert.equal(runFromSearch('?run=xr-abc123'), 'xr-abc123');
  assert.equal(runFromSearch('?run=%20xr-1%20&mockup=1'), 'xr-1');
  for (const search of ['', '?run=', '?run=%20', '?other=1']) assert.equal(runFromSearch(search), null);
  assert.equal(runFromSearch(`?run=${'a'.repeat(500)}`).length, 100);
  assert.equal(withRun('https://x.test/?mockup=1#top', 'xr-9'), '/?mockup=1&run=xr-9#top');
  assert.equal(withRun('https://x.test/?run=xr-9&a=b', null), '/?a=b');
  assert.equal(runFromSearch(withRun('https://x.test/', 'xr-a&b=c').split('/')[1]), 'xr-a&b=c');
});
