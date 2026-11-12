// "Area comments": tenant quotes from the tenant_voices source, each linked to where it was said.
import { safeUrl, timestamp } from './data.js';

const FIELDS = new Set(['tenant_reviews', 'tenant_voices', 'reviews']);

/** [{ text, url, source, at }] for every renter quote in a run's evidence; the text is never invented. */
export function renterQuotes(result) {
  return (result?.evidence || []).filter(e => FIELDS.has(e.field)).map(e => {
    const v = e.value;
    const text = typeof v === 'string' ? v : v?.quote || v?.text || (typeof e.doc_span === 'string' ? e.doc_span : '');
    return { text: String(text || '').trim(), url: safeUrl(e.source_url), source: e.source_name || 'Source not named', at: e.fetched_at };
  }).filter(q => q.text);
}

/** Fill `section` (with a <div class="renter-quotes">) or hide it when the run has no quotes. */
export function renderRenters(section, result) {
  const quotes = renterQuotes(result);
  section.hidden = !quotes.length;
  const list = section.querySelector('.renter-quotes');
  list.replaceChildren(...quotes.map(q => {
    const figure = document.createElement('figure');
    const quote = document.createElement('blockquote');
    quote.textContent = q.text;
    if (q.url) quote.cite = q.url;
    const caption = document.createElement('figcaption');
    if (q.url) {
      const a = document.createElement('a');
      a.href = q.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = q.source;
      caption.append(a);
    } else caption.append(q.source);
    if (q.at) caption.append(` · ${timestamp(q.at)}`);
    figure.append(quote, caption);
    return figure;
  }));
}
