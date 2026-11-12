import { fieldName, valueText, safeUrl, sourcePresent, timestamp, unitFor } from './data.js';

export function timelineEntries(report) {
  return (Array.isArray(report?.history) ? report.history : [])
    .map((record, index) => {
      if (!sourcePresent(record)) return null;
      const eventDate = record.observed_at || record.event_at || record.captured_at;
      const rawDate = eventDate || record.fetched_at;
      const parsed = rawDate ? new Date(rawDate) : null;
      return { record, index, date: parsed && !Number.isNaN(parsed.getTime()) ? parsed : null, dateKind: eventDate ? 'event' : 'retrieval' };
    })
    .filter(Boolean)
    .sort((a, b) => (a.date?.getTime() ?? Infinity) - (b.date?.getTime() ?? Infinity) || a.index - b.index);
}

const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
};

function recordDetails(record, report) {
  const details = element('div', null, 'timeline-detail');
  if (record.previous_value !== undefined && record.previous_value !== null) {
    const comparison = element('dl', null, 'timeline-comparison');
    comparison.append(element('dt', 'Previous'), element('dd', valueText(record.previous_value, record.unit || unitFor(report, record.field, record.previous_value))));
    comparison.append(element('dt', 'Recorded'), element('dd', valueText(record.value, record.unit || unitFor(report, record.field, record.value))));
    details.append(comparison);
  }
  const source = element('p', record.source_name || record.source || (record.source_url ? 'Source record' : 'Cited document span'), 'timeline-source');
  if (typeof record.doc_span === 'string' && record.doc_span.trim()) source.append(element('span', record.doc_span.trim()));
  const href = safeUrl(record.source_url);
  if (href) {
    const link = element('a', 'Open source');
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    source.append(link);
  }
  details.append(source);
  details.append(element('p', `Retrieved on ${timestamp(record.fetched_at)}. ${record.agent ? `Retrieved by ${record.agent}.` : 'Agent not recorded.'}`, 'timeline-meta'));
  return details;
}

function renderEvent(entry, report) {
  const { record, date } = entry;
  const item = element('li', null, 'timeline-event');
  const button = element('button', null, 'timeline-event-toggle');
  button.type = 'button';
  button.setAttribute('aria-expanded', 'false');
  const currentValue = valueText(record.value, record.unit || unitFor(report, record.field, record.value));
  const dateLabel = date ? `${entry.dateKind === 'event' ? 'Source event' : 'Retrieved'} on ${timestamp(date.toISOString())}` : 'Date not recorded';
  const dateNode = element('time', dateLabel, 'timeline-date');
  if (date) dateNode.dateTime = date.toISOString();
  button.append(dateNode);
  button.append(element('span', fieldName(record.field), 'timeline-field'));
  button.append(element('span', currentValue, 'timeline-value'));
  const details = recordDetails(record, report);
  details.hidden = true;
  button.addEventListener('click', () => {
    details.hidden = !details.hidden;
    button.setAttribute('aria-expanded', String(!details.hidden));
  });
  item.append(button, details);
  return item;
}

export function renderTimeline(container, report) {
  const entries = timelineEntries(report);
  const root = element('section', null, 'timeline');
  root.setAttribute('aria-label', 'Property history timeline');
  root.append(element('p', 'Select a record to inspect its value and source. Event dates come from the source; when none is available, retrieval time is shown and does not date the underlying change.', 'timeline-intro'));
  if (!entries.length) {
    root.append(element('p', 'No sourced history is available for this listing.', 'empty'));
    container.replaceChildren(root);
    return;
  }

  const scroller = element('div', null, 'timeline-scroll');
  scroller.tabIndex = 0;
  scroller.setAttribute('role', 'region');
  scroller.setAttribute('aria-label', 'Timeline. Use the left and right arrow keys to scroll.');
  scroller.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      scroller.scrollBy({ left: (event.key === 'ArrowRight' ? 1 : -1) * scroller.clientWidth * 0.75, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    }
    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      scroller.scrollTo({ left: event.key === 'End' ? scroller.scrollWidth : 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    }
  });

  const track = element('div', null, 'timeline-track');
  const groups = new Map();
  for (const entry of entries) {
    const key = entry.date ? String(entry.date.getUTCFullYear()) : 'undated';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }
  for (const [year, records] of groups) {
    const group = element('section', null, 'timeline-year');
    const heading = year === 'undated' ? 'Date not recorded' : year;
    group.setAttribute('aria-label', heading);
    group.append(element('h3', heading));
    const list = element('ol', null, 'timeline-events');
    for (const entry of records) list.append(renderEvent(entry, report));
    group.append(list);
    track.append(group);
  }
  scroller.append(track);
  root.append(scroller);
  container.replaceChildren(root);
}
