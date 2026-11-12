import { test } from 'node:test';
import assert from 'node:assert/strict';
import { renterQuotes } from './renters.js';

test('renter quotes come only from tenant evidence, with a safe link', () => {
  const result = { evidence: [
    { field: 'tenant_reviews', value: 'Damp in every winter.', source_url: 'https://example.org/r/1', source_name: 'Forum' },
    { field: 'tenant_voices', value: { quote: 'Landlord fixed the boiler fast.' }, source_url: 'javascript:alert(1)' },
    { field: 'epc', value: 'D', source_url: 'https://epc.example' },
    { field: 'reviews', value: '  ' },
  ] };
  assert.deepEqual(renterQuotes(result).map(q => [q.text, q.url, q.source]), [
    ['Damp in every winter.', 'https://example.org/r/1', 'Forum'],
    ['Landlord fixed the boiler fast.', null, 'Source not named'],
  ]);
  assert.deepEqual(renterQuotes({}), []);
});
