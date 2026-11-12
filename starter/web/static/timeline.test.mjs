import { test } from 'node:test';
import assert from 'node:assert/strict';
import { timelineEntries } from './timeline.js';

test('timeline orders dated records and groups valid dates by actual UTC year', () => {
  const report = { history: [
    { id: 'new', source_url: 'https://records.test/new', fetched_at: '2027-01-01T00:00:00Z' },
    { id: 'old', source_url: 'https://records.test/old', fetched_at: '2025-12-31T23:59:00Z' },
    { id: 'same-time-stable', source_url: 'https://records.test/same', captured_at: '2027-01-01T00:00:00Z' },
  ] };
  const entries = timelineEntries(report);
  assert.deepEqual(entries.map(item => item.record.id), ['old', 'new', 'same-time-stable']);
  assert.deepEqual(entries.map(item => item.date?.getUTCFullYear()), [2025, 2027, 2027]);
  assert.deepEqual(entries.map(item => item.dateKind), ['retrieval', 'retrieval', 'event']);
});

test('missing or malformed dates remain explicitly undated after dated events', () => {
  const entries = timelineEntries({ history: [
    { id: 'missing', source_url: 'https://records.test/missing' },
    { id: 'bad', doc_span: 'Register page 2', fetched_at: 'not-a-date' },
    { id: 'dated', source_url: 'https://records.test/dated', fetched_at: '2026-10-24T10:00:00Z' },
  ] });
  assert.deepEqual(entries.map(item => [item.record.id, item.date]), [
    ['dated', new Date('2026-10-24T10:00:00Z')], ['missing', null], ['bad', null],
  ]);
  assert.equal(entries[0].dateKind, 'retrieval');
  assert.equal(timelineEntries({ history: [{ id: 'attested', source_url: 'https://records.test/attested', event_at: '2024-06-01T00:00:00Z', fetched_at: '2026-10-24T10:00:00Z' }] })[0].dateKind, 'event');
});

test('history without an allowed source or a report history array is not rendered', () => {
  assert.deepEqual(timelineEntries({ history: [
    { id: 'no-source', value: '£800,000', fetched_at: '2026-10-24T10:00:00Z' },
    { id: 'unsafe', source_url: 'javascript:alert(1)', fetched_at: '2026-10-24T10:00:00Z' },
  ] }), []);
  assert.deepEqual(timelineEntries({ history: null }), []);
  assert.deepEqual(timelineEntries(null), []);
});

test('event and retrieval dates remain chronological within the same year', () => {
  const entries = timelineEntries({ history: [
    { id: 'event-dec', source_url: 'https://records.test/dec', observed_at: '2024-12-01T00:00:00Z', fetched_at: '2026-10-24T10:00:00Z' },
    { id: 'retrieved-may', source_url: 'https://records.test/may', fetched_at: '2024-05-01T00:00:00Z' },
    { id: 'event-jan', source_url: 'https://records.test/jan', event_at: '2024-01-01T00:00:00Z', fetched_at: '2026-10-24T10:00:00Z' },
  ] });
  assert.deepEqual(entries.map(item => item.record.id), ['event-jan', 'retrieved-may', 'event-dec']);
  assert.deepEqual(entries.map(item => item.dateKind), ['event', 'retrieval', 'event']);
  assert.equal(entries[0].date.toISOString(), '2024-01-01T00:00:00.000Z');
});
