import { safeUrl, sourceLabel, timestamp, valueText, fieldName } from './data.js';

const node = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined && text !== null) item.textContent = String(text);
  if (className) item.className = className;
  return item;
};

const asRecord = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const asArray = value => Array.isArray(value) ? value : value ? [value] : [];
const idOf = value => typeof value === 'string' || typeof value === 'number' ? String(value) : '';
const first = (...values) => values.find(value => value !== undefined && value !== null && value !== '');

export function exactSpan(text, span) {
  if (typeof text !== 'string' || !span || typeof span.quote !== 'string' || !span.quote || !Number.isInteger(span.start) || !Number.isInteger(span.end) || span.start < 0 || span.end <= span.start) return null;
  const characters = Array.from(text);
  return characters.slice(span.start, span.end).join('') === span.quote ? { start: span.start, end: span.end } : null;
}

async function getJson(path, signal) {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, signal });
  if (!response.ok) {
    let reason = '';
    try {
      const body = await response.json();
      reason = typeof body.detail === 'string' ? body.detail : typeof body.error === 'string' ? body.error : '';
    } catch { /* Use the HTTP status when no structured error is returned. */ }
    throw new Error(reason || `Trace request failed (${response.status}).`);
  }
  return response.json();
}

function state(container, message, kind = 'info') {
  const status = node('p', message, 'trace-state');
  status.dataset.kind = kind;
  status.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  container.append(status);
}

function metadata(documentRecord, evidence) {
  const wrap = node('dl', null, 'trace-meta');
  const values = [
    ['Source', first(documentRecord.source_name, evidence.source_name, safeUrl(first(documentRecord.source_url, evidence.source_url)) && new URL(first(documentRecord.source_url, evidence.source_url)).hostname, 'Source not recorded')],
    ['Fetched at', timestamp(first(documentRecord.fetched_at, evidence.fetched_at))],
    ['Agent', first(documentRecord.agent, evidence.agent, 'Agent not recorded')],
    ['SHA-256', first(documentRecord.sha256, documentRecord.content_sha256, evidence.document_sha256, 'Hash not supplied')],
    ['Content type', first(documentRecord.content_type, 'Not recorded')],
    ['Captured size', Number.isFinite(documentRecord.size) ? `${documentRecord.size.toLocaleString()} bytes` : 'Not recorded'],
  ];
  for (const [label, value] of values) {
    const cell = node('div');
    cell.append(node('dt', label));
    const dd = node('dd', null);
    dd.append(label === 'SHA-256' && value !== 'Hash not supplied' ? node('code', value) : node('span', value));
    wrap.append(cell);
    cell.append(dd);
  }
  return wrap;
}

function heading(container) {
  const top = node('div', null, 'trace-heading');
  const labels = node('div');
  labels.append(node('h4', 'From finding to source document'));
  top.append(labels);
  container.append(top);
}

function chain(container, trace) {
  const steps = node('div', null, 'trace-chain');
  for (const entry of [...asArray(trace.chain)].reverse()) {
    const { kind, id } = asRecord(entry);
    const step = node('div', null, 'trace-stage');
    step.dataset.kind = String(kind || 'record');
    step.append(node('span', kind || 'Record', 'trace-stage-label'), node('strong', id || 'Identifier not recorded')); steps.append(step);
  }
  if (steps.childElementCount) container.append(steps);
}

function sourceLink(documentRecord, evidence, section) {
  const href = safeUrl(first(documentRecord.url, documentRecord.source_url, evidence.source_url));
  if (!href) return;
  const link = node('a', href, 'trace-source');
  link.setAttribute('aria-label', 'Open original source URL');
  link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer';
  section.append(link);
}

function documentPanel(documentRecord, evidence, text, rawUrl, index, quoteVerified, title) {
  const section = node('section', null, 'trace-document-card');
  section.append(node('h5', first(title, documentRecord.title, documentRecord.name, evidence.source_name, `Source document ${index + 1}`)));
  section.append(metadata(documentRecord, evidence));
  const span = asRecord(evidence.span);
  const quote = typeof span.quote === 'string' ? span.quote : '';
  if (typeof text === 'string' && text) {
    const raw = node('pre', null, 'trace-document');
    const characters = Array.from(text);
    const location = exactSpan(text, span);
    const matches = quoteVerified && documentRecord.id === evidence.document_id && location?.start === span.start && location?.end === span.end;
    if (matches) {
      raw.append(document.createTextNode(characters.slice(0, span.start).join('')));
      const mark = node('mark', characters.slice(span.start, span.end).join(''));
      mark.id = `trace-highlight-${index}`;
      raw.append(mark, document.createTextNode(characters.slice(span.end).join('')));
      section.append(node('p', 'Exact cited text, highlighted in the fetched document.', 'trace-copy'));
    } else {
      raw.textContent = text;
      section.append(node('p', quote ? 'This evidence quote was not verified against the fetched text, so the document is shown without a highlight.' : 'The fetched document is shown without an attributed quote.', 'trace-copy'));
    }
    section.append(raw);
    if (matches) requestAnimationFrame(() => raw.scrollTo({ top: Math.max(0, raw.scrollTop + raw.querySelector('mark').getBoundingClientRect().top - raw.getBoundingClientRect().top - raw.clientHeight / 2), behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }));
  } else section.append(node('p', 'The document API did not return decoded text, so no quote is highlighted.', 'trace-copy'));
  sourceLink(documentRecord, evidence, section);
  if (typeof rawUrl === 'string') {
    try {
      const raw = new URL(rawUrl, location.origin);
      if (raw.origin === location.origin && raw.pathname === `/api/document/${encodeURIComponent(documentRecord.id)}/raw`) {
        const download = node('a', 'Download captured file', 'trace-source');
        download.href = raw.href; download.rel = 'noopener'; download.download = ''; section.append(download);
      }
    } catch { /* Ignore malformed raw document links. */ }
  }
  return section;
}

export async function renderTrace(container, findingId, { signal, runId } = {}) {
  if (signal?.aborted) return;
  container.replaceChildren();
  container.classList.add('trace-panel');
  container.setAttribute('aria-label', 'Finding evidence trace');
  heading(container);
  state(container, 'Retrieving the cited records…');
  const identifier = idOf(findingId);
  if (!identifier) {
    container.replaceChildren(); heading(container); state(container, 'This finding has no traceable identifier.', 'error'); return;
  }
  try {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
    const payload = asRecord(await getJson(`/api/finding/${encodeURIComponent(identifier)}/trace${query}`, signal));
    if (signal?.aborted) return;
    if (runId && String(payload.run_id) !== String(runId)) throw new Error('The trace belongs to a different run, so it was not shown.');
    const trace = payload;
    const steps = asArray(trace.steps).map(asRecord);
    const documentCache = new Map();
    const fetchDocument = documentId => {
      if (!documentCache.has(documentId)) {
        documentCache.set(documentId, getJson(`/api/document/${encodeURIComponent(documentId)}`, signal).then(payload => {
          const document = asRecord(asRecord(payload).document);
          if (document.id !== documentId) throw new Error('The document API returned a different document identifier.');
          return { document, text: payload.text, rawUrl: payload.raw_url };
        }));
      }
      return documentCache.get(documentId);
    };
    const documents = [];
    for (let index = 0; index < steps.length; index += 1) {
      const step = steps[index];
      const documentId = idOf(first(asRecord(step.document).id, step.evidence?.document_id));
      const evidenceDocumentId = idOf(step.evidence?.document_id);
      if (!documentId || !evidenceDocumentId || documentId !== evidenceDocumentId) {
        documents.push({ step, error: new Error(!documentId || !evidenceDocumentId ? 'No captured source document is linked to this evidence.' : 'The evidence and document identifiers do not match.') }); continue;
      }
      try {
        documents.push({ step, ...await fetchDocument(documentId) });
      } catch (error) {
        if (error.name === 'AbortError' || signal?.aborted) return;
        documents.push({ step, error });
      }
    }
    if (signal?.aborted) return;
    container.replaceChildren(); heading(container); chain(container, trace);
    let claimDocument;
    const claim = asRecord(trace.claim);
    const claimSource = asRecord(trace.claim_document);
    const claimDocumentId = idOf(claim.document_id);
    if (claimDocumentId && (!claimSource.id || claimSource.id === claimDocumentId)) {
      try { claimDocument = await fetchDocument(claimDocumentId); }
      catch (error) {
        if (error.name === 'AbortError' || signal?.aborted) return;
        claimDocument = { error };
      }
    } else if (claimSource.id || claimDocumentId) claimDocument = { error: new Error('The claim and original document identifiers do not match.') };
    if (trace.claim) {
      const claimCard = node('section', null, 'trace-claim');
      claimCard.append(node('h5', 'Claim in the listing'));
      if (claim.field) claimCard.append(node('p', fieldName(claim.field), 'trace-copy'));
      if (claim.value !== undefined) claimCard.append(node('p', `Claimed value: ${typeof claim.value === 'string' ? claim.value : JSON.stringify(claim.value)}`, 'trace-copy'));
      if (claimDocument && !claimDocument.error) {
        claimCard.append(documentPanel(claimDocument.document, claim, claimDocument.text, claimDocument.rawUrl, 'claim', trace.claim_quote_verified === true, 'Captured listing source'));
      } else {
        state(claimCard, claimDocument?.error ? `The original listing document is unavailable: ${claimDocument.error.message}` : 'No original listing document was captured for this claim.', claimDocument?.error ? 'error' : 'info');
      }
      container.append(claimCard);
    }
    for (let index = 0; index < steps.length; index += 1) {
      const step = steps[index];
      const record = asRecord(step.evidence);
      const section = node('section', null, 'trace-evidence');
      section.append(node('h5', first(record.source_name, sourceLabel(record), `Evidence ${index + 1}`)));
      if (record.field) section.append(node('p', `Field: ${fieldName(record.field)}`, 'trace-copy'));
      if (record.value !== undefined) section.append(node('p', `Recorded value: ${valueText(record.value, record.unit)}`, 'trace-copy'));
      const loaded = documents[index];
      if (loaded.error) {
        state(section, `The source document is unavailable: ${loaded.error.message}`, 'error');
        sourceLink(asRecord(step.document), record, section);
        state(section, 'The cited span remains in the finding details; the original text is unavailable here.', 'info');
      } else section.append(documentPanel(loaded.document, record, loaded.text, loaded.rawUrl, index, step.quote_verified === true));
      container.append(section);
    }
    if (!steps.length) state(container, 'No evidence records are linked to this finding.', 'info');
  } catch (error) {
    if (error.name === 'AbortError' || signal?.aborted) return;
    container.replaceChildren(); heading(container); state(container, `Trace unavailable: ${error.message}. The finding details remain available.`, 'error');
  }
}
