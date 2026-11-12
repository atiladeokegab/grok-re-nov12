import { fieldName, VERDICTS, safeUrl, valueText, sourcePresent, findingRecords, sourceLabel, timestamp, photoChange, unitFor } from './data.js';

const $ = id => document.getElementById(id);
const mockup = new URLSearchParams(location.search).get('mockup') === '1';
let current = null;
let selected = null;
let stream = null;
let generation = 0;
let controller = null;
let disposeCurrentFlyIn = null;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function icon(kind = 'arrow') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', kind === 'matches' ? 'm5 12 4 4 10-10' : kind === 'disagrees' || kind === 'flag' ? 'M12 4 2 21h20L12 4Zm0 6v5m0 2v1' : kind === 'unverifiable' ? 'M12 8v5m0 3v1M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0' : 'm9 5 7 7-7 7');
  svg.append(path);
  return svg;
}

function sourceRecord(record) {
  const block = element('div', null, 'evidence-record');
  block.append(element('strong', sourceLabel(record)));
  const link = safeUrl(record.source_url);
  if (link) {
    const a = element('a', 'Open source');
    a.href = link; a.target = '_blank'; a.rel = 'noopener noreferrer';
    block.append(a);
  }
  if (record.doc_span) block.append(element('p', typeof record.doc_span === 'string' ? record.doc_span : JSON.stringify(record.doc_span)));
  block.append(element('p', `${timestamp(record.fetched_at || record.captured_at)}. ${record.agent ? `Retrieved by ${record.agent}.` : 'Agent not recorded.'}`));
  return block;
}

function compareColumn(title, record) {
  const column = element('div');
  column.append(element('dt', title));
  column.append(element('dd', sourcePresent(record) ? valueText(record.value, record.unit) : 'Source not available'));
  const image = safeUrl(record?.value);
  if (sourcePresent(record) && image && ['photo', 'photos', 'image_url'].includes(record.field)) {
    const img = element('img'); img.src = image; img.alt = title; img.loading = 'lazy'; column.append(img);
  }
  return column;
}

function photoFigure(url, label, advertId) {
  const figure = element('figure', null, 'evidence-photo');
  const link = element('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
  const image = element('img'); image.src = url; image.alt = `${label} photograph from listing ${advertId}`; image.loading = 'lazy';
  link.append(image); figure.append(link, element('figcaption', `${label} in advert ${advertId}.`));
  return figure;
}

function showFinding(id, moveFocus = false) {
  selected = id;
  const finding = (current?.findings || []).find(item => item.id === id);
  const detail = $('finding-detail');
  detail.replaceChildren(); detail.hidden = !finding;
  $('findings').hidden = Boolean(finding);
  for (const button of $('findings').querySelectorAll('button')) button.setAttribute('aria-expanded', String(button.dataset.id === id));
  if (!finding) return;
  const back = element('button', 'All findings', 'secondary'); back.type = 'button';
  back.addEventListener('click', () => { showFinding(null); $('findings').querySelector('button')?.focus(); });
  detail.append(back);
  const { claim, evidence } = findingRecords(finding, current);
  detail.append(element('h3', fieldName(finding.field)));
  const cited = evidence.filter(sourcePresent);
  const change = cited.map(photoChange).find(Boolean);
  if (change) {
    const comparison = element('div', null, 'photo-comparison');
    comparison.append(
      photoFigure(change.oldPhoto, 'Removed', change.previous_advert_id),
      photoFigure(change.newPhoto, 'Added', change.advert_id),
    );
    detail.append(comparison);
  } else if (claim || cited.length) {
    const comparison = element('dl', null, 'comparison');
    comparison.append(compareColumn('The listing says', claim), compareColumn('The source records', cited[0]));
    detail.append(comparison);
  }
  const hasSources = cited.length > 0 || finding.verdict === 'unverifiable';
  detail.append(element('p', hasSources ? finding.reasoning : 'The supporting source is missing. This finding cannot yet be verified.', 'reasoning'));
  if (hasSources && finding.model) detail.append(element('p', `Reasoning: ${finding.model}`, 'section-description'));
  if (sourcePresent(claim)) detail.append(sourceRecord(claim));
  for (const record of cited) detail.append(sourceRecord(record));
  if (!cited.length) detail.append(element('p', 'No supporting evidence record is available.', 'empty'));
  if (moveFocus) { detail.tabIndex = -1; detail.focus({ preventScroll: true }); detail.scrollIntoView({ block: 'nearest', behavior: 'instant' }); }
}

function renderHistory(result) {
  const history = (result.history || []).filter(sourcePresent);
  $('history-count').textContent = `${history.length} ${history.length === 1 ? 'record' : 'records'}`;
  $('history').replaceChildren();
  for (const record of history) {
    const row = element('article', null, 'history-entry');
    row.append(element('h3', fieldName(record.field)));
    const values = element('p', null, 'history-values');
    const unit = value => record.unit || unitFor(result, record.field, value);
    if (record.previous_value !== undefined && record.previous_value !== null) values.append(element('del', valueText(record.previous_value, unit(record.previous_value))));
    values.append(element('span', valueText(record.value, unit(record.value))));
    row.append(values, sourceRecord(record));
    if (record.advert_id) row.append(element('p', `Advert ${record.advert_id}`));
    $('history').append(row);
  }
  if (!history.length) $('history').append(element('p', 'No sourced change history is available for this listing.', 'empty'));
}

function renderMedia(result) {
  const media = $('property-media');
  media.replaceChildren();
  const photo = (result.place?.photos || []).find(item => safeUrl(item.url));
  if (photo) {
    const image = element('img'); image.src = safeUrl(photo.url); image.alt = `Listing photograph for ${result.place.address || 'this property'}`;
    image.addEventListener('error', () => { image.replaceWith(element('p', 'The listing’s image could not be loaded. Its source is linked below.', 'media-empty')); }, { once: true });
    const link = element('a', 'Original listing image', 'image-source'); link.href = safeUrl(photo.source_url) || safeUrl(photo.url); link.target = '_blank'; link.rel = 'noopener noreferrer';
    media.append(image, link);
    if (photo.caption) media.append(element('p', photo.caption, 'media-caption'));
  } else {
    media.append(element('p', 'No source photograph has been supplied. Open the original listing to inspect its photos.', 'media-empty'));
    const listingUrl = safeUrl(result.listing_url || result.url);
    if (listingUrl) {
      const link = element('a', 'Open the original listing', 'image-source');
      link.href = listingUrl; link.target = '_blank'; link.rel = 'noopener noreferrer'; media.append(link);
    }
  }
}

function runError(value, fallback = 'The run ended before every check finished. Records received so far remain visible.') {
  return typeof value === 'string' && value.trim() ? value.trim().slice(0, 400) : fallback;
}

async function showFlyIn(result) {
  const container = $('flyin');
  const owner = generation;
  if (!container || container.dataset.enabled !== 'true') return;
  const { lat, lng, use } = result.place || {};
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
  try {
    const module = await import('/static/flyin/flyin.js');
    if (!module.flyIn || !module.disposeFlyIn) return;
    if (owner !== generation) return;
    disposeCurrentFlyIn = () => module.disposeFlyIn(container);
    container.hidden = false;
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    await module.flyIn(container, {
      lat, lng,
      label: result.place?.postcode || result.place?.title || 'Approximate property area',
      precision: result.place?.precision === 'address' ? 'address' : 'postcode_centroid',
      use: use === 'office' ? 'office' : 'residential',
      durationMs: reducedMotion ? 0 : 7000,
    });
    if (owner !== generation) return;
    module.disposeFlyIn(container); disposeCurrentFlyIn = null;
    container.hidden = true;
  } catch {
    if (generation === owner) container.hidden = true;
  }
}

function render(result) {
  current = result;
  $('intro').hidden = true; $('results').hidden = false;
  $('place-title').textContent = result.place?.title || result.place?.address || 'Listing X-ray';
  $('place-description').textContent = result.place?.title && result.place?.address ? result.place.address : result.listing_id || '';
  $('score').textContent = Number.isFinite(result.trust_score) ? result.trust_score : '—';
  const counts = result.counts || {};
  const disagreements = counts.disagrees || 0;
  $('summary-title').textContent = disagreements ? `${disagreements} ${disagreements === 1 ? 'claim doesn’t' : 'claims don’t'} match the records` : (result.findings || []).length ? 'The records are ready to compare' : 'Checking the records';
  $('summary-detail').textContent = `${counts.matches || 0} matched. ${counts.unverifiable || 0} could not be verified. ${counts.flag || 0} worth a closer look. Unverifiable claims are excluded from the score.`;
  $('finding-count').textContent = `${(result.findings || []).length} findings`;
  $('findings').replaceChildren();
  for (const finding of result.findings || []) {
    const { evidence } = findingRecords(finding, result);
    const verdict = finding.verdict === 'unverifiable' || evidence.some(sourcePresent) ? finding.verdict : 'unverifiable';
    const button = element('button', null, 'finding');
    button.type = 'button'; button.dataset.id = finding.id; button.setAttribute('aria-expanded', String(finding.id === selected)); button.setAttribute('aria-controls', 'finding-detail');
    const text = element('span');
    text.append(element('span', fieldName(finding.field), 'finding-name'), element('span', VERDICTS[verdict] || 'Verdict not recorded', `finding-verdict verdict-${verdict}`));
    const statusIcon = icon(verdict); statusIcon.classList.add(`verdict-${verdict}`);
    button.append(statusIcon, text, icon()); button.addEventListener('click', () => showFinding(finding.id, true));
    $('findings').append(button);
  }
  if (!(result.findings || []).length) $('findings').append(element('p', 'No findings have arrived. This is not a verified match.', 'empty'));
  renderMedia(result); renderHistory(result);
  $('sources').replaceChildren();
  for (const source of result.sources || []) {
    const line = element('p', null, 'source-status');
    line.append(element('span', source.name), element('span', source.status === 'ok' ? `${source.n_evidence || 0} evidence records` : source.status === 'error' ? 'Source unavailable' : 'No record found'));
    if (source.detail) line.append(element('small', String(source.detail).slice(0, 240), 'source-detail'));
    $('sources').append(line);
  }
  const calls = result.client_calls || {};
  const activity = [['Grok API calls', calls.grok ?? result.grok_calls], ['Cursor SDK calls', calls.cursor_sdk], ['Grok Bot MCP calls', calls.mcp?.grok_bot], ['Cursor MCP calls', calls.mcp?.cursor]];
  $('activity').replaceChildren();
  for (const [label, count] of activity) $('activity').append(element('dt', label), element('dd', Number.isFinite(count) ? count : 'Not reported'));
  $('run-id').textContent = `Run ${result.run_id || 'not recorded'}`;
  if (selected && (result.findings || []).some(item => item.id === selected)) showFinding(selected);
  else { selected = null; $('finding-detail').hidden = true; $('findings').hidden = false; }
}

async function request(url, options = {}) {
  const response = await fetch(url, { ...options, signal: controller?.signal });
  if (!response.ok) {
    let message = `Request failed (${response.status}). Check the listing and try again.`;
    try {
      const body = await response.json();
      const detail = typeof body.detail === 'string' ? body.detail : typeof body.error === 'string' ? body.error : null;
      if (detail) message = detail.slice(0, 400);
    } catch { /* Preserve the HTTP error if no JSON was returned. */ }
    const error = new Error(message); error.status = response.status; throw error;
  }
  return response.json();
}

async function readRun(runId, ownGeneration) {
  if (generation !== ownGeneration) throw new DOMException('Request superseded', 'AbortError');
  return request(`/api/xray/${encodeURIComponent(runId)}`);
}

function stop() {
  generation += 1;
  controller?.abort(); controller = null;
  stream?.close(); stream = null;
  disposeCurrentFlyIn?.(); disposeCurrentFlyIn = null;
  const flyin = $('flyin'); if (flyin) flyin.hidden = true;
}

function watch(runId, ownGeneration) {
  let refreshing = false;
  let again = false;
  let finished = false;
  const source = new EventSource(`/api/xray/${encodeURIComponent(runId)}/events`);
  stream = source;
  const finish = result => {
    if (finished) return;
    finished = true;
    source.close();
    if (stream === source) stream = null;
    if (result.status === 'error') {
      $('error').textContent = runError(result.error);
      $('error').hidden = false;
    } else $('status').textContent = 'The X-ray is complete. Each finding links to its supporting record.';
  };
  const refresh = async () => {
    if (finished) return;
    if (generation !== ownGeneration) return;
    if (refreshing) { again = true; return; }
    refreshing = true;
    try {
      do {
        again = false;
        const result = await readRun(runId, ownGeneration);
        if (generation !== ownGeneration) return;
        render(result);
        if (result.status === 'done' || result.status === 'error') finish(result);
      } while (again && !finished);
    } catch (error) {
      if (generation === ownGeneration && error.name !== 'AbortError') { $('error').textContent = `Live update failed: ${error.message}`; $('error').hidden = false; }
    } finally { refreshing = false; }
  };
  for (const name of ['message', 'source', 'claim', 'evidence', 'finding', 'history', 'score']) source.addEventListener(name, refresh);
  source.addEventListener('done', async event => {
    await refresh();
    if (generation !== ownGeneration) return;
    let terminal;
    try { terminal = JSON.parse(event.data); } catch { terminal = {}; }
    finish(terminal);
  });
  source.addEventListener('error', () => {
    if (generation !== ownGeneration) return;
    $('run-id').textContent = `Run ${runId}. Live connection interrupted; reconnecting. Last received records remain visible.`;
  });
}

$('xray-form').addEventListener('submit', async event => {
  event.preventDefault();
  const listing = $('listing').value.trim();
  if (!listing) return;
  stop(); controller = new AbortController();
  const ownGeneration = generation;
  $('error').hidden = true; $('start').disabled = true; $('status').textContent = 'Checking the records. Each finding will link to its evidence.';
  try {
    if (mockup) {
      const { prototype } = await import('./prototype.js');
      if (generation === ownGeneration) render(prototype);
    } else {
      const use = document.querySelector('input[name="use"]:checked')?.value === 'office' ? 'office' : 'residential';
      const payload = { ...( /^https?:\/\//i.test(listing) ? { url: listing } : { listing_id: listing }), use };
      const started = await request('/api/xray', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (generation !== ownGeneration) return;
      if (!started.run_id) throw new Error('The server did not return a run ID. Try again.');
      const result = await readRun(started.run_id, ownGeneration);
      if (generation !== ownGeneration) return;
      render(result);
      showFlyIn(result);
      if (result.status === 'running') watch(started.run_id, ownGeneration);
      else if (result.status === 'error') {
        $('error').textContent = runError(result.error);
        $('error').hidden = false;
      }
    }
  } catch (error) {
    if (generation === ownGeneration && error.name !== 'AbortError') { $('error').textContent = error.message; $('error').hidden = false; }
  } finally {
    if (generation === ownGeneration) $('start').disabled = false;
  }
});

$('new-listing').addEventListener('click', () => {
  stop(); selected = null;
  const flyin = $('flyin'); if (flyin) { flyin.hidden = true; }
  $('intro').hidden = false; $('results').hidden = true; $('start').disabled = false; $('error').hidden = true;
  $('status').textContent = 'Every finding opens back to its source.';
  $('listing').focus(); window.scrollTo({ top: 0, behavior: 'instant' });
});
window.addEventListener('pagehide', stop);

if (mockup) {
  $('prototype').hidden = false; $('listing').value = 'illustrative-listing';
  const state = new URLSearchParams(location.search).get('state');
  if (state === 'result' || state === 'detail') {
    const { prototype } = await import('./prototype.js'); render(prototype);
    if (state === 'detail') showFinding(prototype.findings[0].id);
  }
  if (state === 'error') { $('error').textContent = 'The source is unavailable. Check the listing and try again.'; $('error').hidden = false; }
}
