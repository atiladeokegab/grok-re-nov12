import { fieldName, VERDICTS, safeUrl, valueText, sourcePresent, findingRecords, sourceLabel, timestamp, photoChange, unitFor, hasChangedValue, runFromSearch, withRun } from './data.js';
import { renderTimeline } from './timeline.js';
import { mountClients } from './clients.js';
import { loadGallery } from './gallery.js';

const $ = id => document.getElementById(id);
const mockup = new URLSearchParams(location.search).get('mockup') === '1';
let current = null;
let selected = null;
let stream = null;
let generation = 0;
let controller = null;
let disposeCurrentFlyIn = null;
let activeView = 'findings';
let graphWidget = null;
let graphRequest = 0;
let traceController = null;
let traceRoutes;

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
    a.dataset.testid = 'source-link';
    block.append(a);
  }
  if (record.doc_span) block.append(element('p', typeof record.doc_span === 'string' ? record.doc_span : JSON.stringify(record.doc_span)));
  if (record.field === 'room_schedule' && Array.isArray(record.value?.rooms)) block.append(roomTable(record.value));
  block.append(element('p', `${timestamp(record.fetched_at || record.captured_at)}. ${record.agent ? `Retrieved by ${record.agent}.` : 'Agent not recorded.'}`));
  return block;
}

function roomTable({ rooms, rooms_m2, stated_m2 }) {
  const table = element('table', null, 'room-table');
  table.dataset.testid = 'room-table';
  const row = (cells, tag = 'td') => { const tr = element('tr'); for (const c of cells) tr.append(element(tag, c)); return tr; };
  table.append(row(['Room', 'Size (m)', 'Area (m²)'], 'th'));
  for (const r of rooms) table.append(row([r.name, `${r.width_m} × ${r.length_m}`, r.area_m2.toFixed(1)]));
  table.append(row(['Rooms total', '', rooms_m2.toFixed(1)], 'th'));
  if (stated_m2) table.append(row(['Advert states', '', stated_m2.toFixed(1)], 'th'));
  return table;
}

function compareColumn(title, record) {
  const column = element('div');
  column.append(element('dt', title));
  column.append(element('dd', sourcePresent(record) ? valueText(record.value, record.unit) : record ? 'Source not available' : 'Not stated'));
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
  traceController?.abort();
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
  const trace = element('section', null, 'trace-slot'); detail.append(trace);
  traceController = new AbortController();
  loadTrace(trace, finding.id, traceController.signal, current.run_id);
  if (moveFocus) { detail.tabIndex = -1; detail.focus({ preventScroll: true }); detail.scrollIntoView({ block: 'nearest', behavior: 'instant' }); }
}

async function loadTrace(container, findingId, signal, runId) {
  try {
    traceRoutes ??= fetch('/openapi.json').then(response => response.ok ? response.json() : {}).then(schema => Object.keys(schema.paths || {}).some(path => /^\/api\/finding\/\{[^}]+\}\/trace$/.test(path))).catch(() => false);
    if (!await traceRoutes || signal.aborted) {
      if (!signal.aborted) container.append(element('p', 'Full document trace is not available for this run. Follow the cited source records above.', 'empty'));
      return;
    }
    const { renderTrace } = await import('./trace.js');
    if (!signal.aborted) await renderTrace(container, findingId, { signal, runId });
  } catch (error) {
    if (!signal.aborted) container.replaceChildren(element('p', 'The document trace could not be loaded. The cited records above remain available.', 'empty'));
  }
}

async function updateGraph() {
  if (activeView !== 'connections' || !current) return;
  const requestId = ++graphRequest;
  const runId = current.run_id;
  const container = $('connections-graph');
  if (!graphWidget) container.replaceChildren(element('p', 'Connecting this check’s source records…', 'view-status'));
  try {
    const graph = await request(`/api/place/${encodeURIComponent(current.place_id)}/graph`);
    if (requestId !== graphRequest || runId !== current?.run_id || activeView !== 'connections') return;
    if (graph.run_id !== runId) throw new Error('A newer check has replaced this place’s graph. Start a fresh X-ray to inspect it.');
    if (graphWidget) graphWidget.update(graph);
    else {
      const { mountGraph } = await import('./graph.js');
      if (requestId !== graphRequest || activeView !== 'connections') return;
      const mounted = await mountGraph(container, graph, { onSelect: node => {
        if (node.kind === 'finding') { setView('findings'); showFinding(node.id, true); }
      } });
      if (requestId !== graphRequest || activeView !== 'connections') mounted.dispose();
      else graphWidget = mounted;
    }
  } catch (error) {
    if (requestId === graphRequest) container.replaceChildren(element('p', error.message, 'view-status'));
  }
}

async function updateInside() {
  if (!current) return;
  const result = current;
  const { renderInside } = await import('./inside.js');
  if (activeView === 'inside' && current === result) await renderInside($('inside-plan'), result);
}

function setView(view) {
  activeView = view;
  for (const button of document.querySelectorAll('[data-view]')) button.setAttribute('aria-pressed', String(button.dataset.view === view));
  for (const name of ['findings', 'connections', 'timeline', 'inside']) $(`${name}-view`).hidden = name !== view;
  if (view !== 'connections') { graphRequest += 1; graphWidget?.dispose(); graphWidget = null; }
  if (view === 'timeline' && current) renderTimeline($('history-timeline'), current);
  if (view === 'connections') updateGraph();
  if (view === 'inside') updateInside();
}

function renderHistory(result) {
  const history = (result.history || []).filter(sourcePresent);
  $('history-count').textContent = `${history.length} ${history.length === 1 ? 'record' : 'records'}, ${history.filter(hasChangedValue).length} changes`;
  $('history').replaceChildren();
  for (const record of history) {
    const row = element('article', null, 'history-entry');
    row.append(element('h3', fieldName(record.field)));
    const values = element('p', null, 'history-values');
    const unit = value => record.unit || unitFor(result, record.field, value);
    if (hasChangedValue(record)) values.append(element('del', valueText(record.previous_value, unit(record.previous_value))));
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
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const { lat, lng, use } = result.place || {};
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
  let ended = false;
  let module;
  const skip = element('button', 'Skip to findings', 'secondary flyin-skip'); skip.type = 'button';
  let landingTimer;
  let releaseLanding;
  const finish = () => {
    if (ended) return;
    ended = true; clearTimeout(timeout); clearTimeout(landingTimer); module?.disposeFlyIn(container); skip.remove();
    releaseLanding?.(); releaseLanding = null;
    if (generation === owner) { container.hidden = true; disposeCurrentFlyIn = null; }
  };
  const timeout = setTimeout(finish, 8500);
  skip.addEventListener('click', finish); container.append(skip);
  disposeCurrentFlyIn = finish;
  try {
    module = await import('/static/flyin/flyin.js');
    if (!module.flyIn || !module.disposeFlyIn) return;
    if (owner !== generation || ended) return;
    container.hidden = false;
    await module.flyIn(container, {
      lat, lng,
      label: result.place?.postcode || result.place?.title || 'Approximate property area',
      precision: result.place?.precision === 'address' ? 'address' : 'postcode_centroid',
      use: use === 'office' ? 'office' : 'residential',
      durationMs: 5000,
    });
    if (owner !== generation || ended) return;
    await new Promise(resolve => {
      releaseLanding = resolve;
      landingTimer = setTimeout(() => { landingTimer = null; releaseLanding = null; resolve(); }, 1500);
    });
    if (owner !== generation || ended) return;
    finish();
  } catch {
    finish();
  }
}

function render(result) {
  current = result;
  $('intro').hidden = true; $('results').hidden = false;
  $('place-title').textContent = result.place?.title || result.place?.address || 'Listing X-ray';
  $('place-description').textContent = result.place?.title && result.place?.address ? result.place.address : result.listing_id || '';
  $('run-status').textContent = result.status === 'running' ? 'Checking sources. Findings update as records arrive.' : result.status === 'done' ? 'Check complete.' : result.status === 'error' ? 'Check incomplete. Review the source details below.' : 'Source records from this check.';
  $('score').textContent = Number.isFinite(result.trust_score) ? result.trust_score : '—';
  const counts = result.counts || {};
  const disagreements = counts.disagrees || 0;
  $('summary-title').textContent = disagreements ? `${disagreements} ${disagreements === 1 ? 'claim doesn’t' : 'claims don’t'} match the records` : (result.findings || []).length ? 'The records are ready to compare' : 'Checking the records';
  $('summary-detail').textContent = `${counts.matches || 0} matched. ${counts.unverifiable || 0} could not be verified. ${counts.flag || 0} worth a closer look. Unverifiable claims are left out of the score.`;
  $('run-message').textContent = result.message || ''; $('run-message').hidden = !result.message;
  $('finding-count').textContent = `${(result.findings || []).length} findings`;
  $('findings').replaceChildren();
  for (const finding of result.findings || []) {
    const { evidence } = findingRecords(finding, result);
    const verdict = finding.verdict === 'unverifiable' || evidence.some(sourcePresent) ? finding.verdict : 'unverifiable';
    const button = element('button', null, 'finding');
    button.type = 'button'; button.dataset.id = finding.id; button.dataset.testid = 'finding'; button.setAttribute('aria-expanded', String(finding.id === selected)); button.setAttribute('aria-controls', 'finding-detail');
    const text = element('span');
    text.append(element('span', fieldName(finding.field), 'finding-name'), element('span', VERDICTS[verdict] || 'Verdict not recorded', `finding-verdict verdict-${verdict}`));
    const statusIcon = icon(verdict); statusIcon.classList.add(`verdict-${verdict}`);
    button.append(statusIcon, text, icon()); button.addEventListener('click', () => showFinding(finding.id, true));
    $('findings').append(button);
  }
  if (!(result.findings || []).length) $('findings').append(element('p', 'No findings have arrived. This is not a verified match.', 'empty'));
  renderMedia(result); renderHistory(result);
  $('sources').replaceChildren();
  const notRun = [];
  for (const source of result.sources || []) {
    if (source.status === 'off') {
      notRun.push(source.name === 'companies_house' ? 'Companies House' : source.name.replaceAll('_', ' '));
      continue;
    }
    const line = element('p', null, `source-status status-${source.status}`);
    line.append(element('span', source.name), element('span', source.status === 'ok' ? `${source.n_evidence || 0} evidence records` : source.status === 'error' ? 'Source unavailable' : 'No record found'));
    if (source.detail) line.append(element('small', String(source.detail).slice(0, 240), 'source-detail'));
    $('sources').append(line);
  }
  if (notRun.length) $('sources').append(element('p', `Not run for this listing: ${notRun.join(', ')}`, 'status'));
  const calls = result.client_calls || {};
  const activity = [['Cursor SDK calls', calls.cursor_sdk], ['Cursor MCP calls', calls.mcp?.cursor], ['Other MCP calls', calls.mcp && (calls.mcp.other ?? 0) + (calls.mcp.grok_bot ?? 0)]];
  $('activity').replaceChildren();
  for (const [label, count] of activity) $('activity').append(element('dt', label), element('dd', Number.isFinite(count) ? count : 'Not reported'));
  $('run-id').textContent = `Run ${result.run_id || 'not recorded'}`;
  $('export-csv').hidden = !result.run_id; if (result.run_id) $('export-csv').href = `/api/xray/${encodeURIComponent(result.run_id)}/export.csv`;
  if (selected && (result.findings || []).some(item => item.id === selected)) showFinding(selected);
  else { selected = null; $('finding-detail').hidden = true; $('findings').hidden = false; }
  if (activeView === 'timeline') renderTimeline($('history-timeline'), result);
  if (activeView === 'connections') updateGraph();
  if (activeView === 'inside') updateInside();
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
  traceController?.abort(); traceController = null;
  graphRequest += 1; graphWidget?.dispose(); graphWidget = null;
  disposeCurrentFlyIn?.(); disposeCurrentFlyIn = null;
  const flyin = $('flyin'); if (flyin) flyin.hidden = true;
}

function watch(runId, ownGeneration) {
  let refreshPromise = null;
  let refreshAgain = false;
  let finished = false;
  let lastRefreshError = null;
  const source = new EventSource(`/api/xray/${encodeURIComponent(runId)}/events`);
  stream = source;
  const finish = result => {
    if (finished) return;
    finished = true;
    clients.refresh();
    if (result.message) { $('run-message').textContent = result.message; $('run-message').hidden = false; }
    source.close();
    if (stream === source) stream = null;
    if (result.status === 'error') {
      $('error').textContent = runError(result.error);
      $('error').hidden = false;
    } else $('status').textContent = 'The X-ray is complete. Each finding links to its supporting record.';
  };
  const refresh = () => {
    if (finished || generation !== ownGeneration) return Promise.resolve(null);
    if (refreshPromise) { refreshAgain = true; return refreshPromise; }
    refreshPromise = (async () => {
      let latest = null;
      do {
        refreshAgain = false;
        const result = await readRun(runId, ownGeneration);
        if (generation !== ownGeneration || finished) return null;
        latest = result; lastRefreshError = null;
        render(result);
        if (result.status === 'done' || result.status === 'error') finish(result);
      } while (refreshAgain && !finished && generation === ownGeneration);
      return latest;
    })().catch(error => {
      if (generation === ownGeneration && error.name !== 'AbortError' && !finished) {
        lastRefreshError = error;
        $('error').textContent = `Live update failed: ${error.message}`; $('error').hidden = false;
      }
      return null;
    }).finally(() => { refreshPromise = null; });
    return refreshPromise;
  };
  for (const name of ['message', 'source', 'claim', 'evidence', 'finding', 'history', 'score']) source.addEventListener(name, refresh);
  source.addEventListener('done', async event => {
    const latest = await refresh();
    if (generation !== ownGeneration || finished) return;
    let terminal;
    try { terminal = JSON.parse(event.data); } catch { terminal = {}; }
    if (lastRefreshError || !latest || (latest.status !== 'done' && latest.status !== 'error')) {
      finished = true; source.close(); if (stream === source) stream = null;
      const reason = lastRefreshError ? ` ${lastRefreshError.message}` : typeof terminal.error === 'string' ? ` ${terminal.error.slice(0, 400)}` : '';
      $('error').textContent = `The live stream ended before a final report could be loaded.${reason}`;
      $('error').hidden = false;
      return;
    }
    finish(latest);
  });
  source.addEventListener('error', () => {
    if (generation !== ownGeneration || finished) return;
    $('run-id').textContent = `Run ${runId}. Live connection interrupted; reconnecting. Last received records remain visible.`;
  });
}

const clients = mountClients($('clients'));

$('xray-form').addEventListener('submit', event => {
  event.preventDefault();
  const listing = $('listing').value.trim();
  if (!listing) return;
  const use = document.querySelector('input[name="use"]:checked')?.value === 'office' ? 'office' : 'residential';
  startRun({ ...( /^https?:\/\//i.test(listing) ? { url: listing } : { listing_id: listing }), use });
});

loadGallery($('gallery'), item => { $('listing').value = item.name; startRun({ listing_id: item.name, offline: true }); });

async function startRun(payload) {
  stop(); controller = new AbortController();
  setView('findings');
  const ownGeneration = generation;
  $('error').hidden = true; $('start').disabled = true; $('status').textContent = 'Checking the records. Each finding will link to its evidence.';
  try {
    if (mockup) {
      const { prototype } = await import('./prototype.js');
      if (generation === ownGeneration) render(prototype);
    } else {
      const started = await request('/api/xray', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (generation !== ownGeneration) return;
      if (!started.run_id) throw new Error('The server did not return a run ID. Try again.');
      history.replaceState(null, '', withRun(location.href, started.run_id)); // the tab's URL reopens this run
      await openRun(started.run_id, ownGeneration, true);
    }
  } catch (error) {
    if (generation === ownGeneration && error.name !== 'AbortError') { $('error').textContent = error.message; $('error').hidden = false; }
  } finally {
    if (generation === ownGeneration) $('start').disabled = false;
  }
}

async function openRun(runId, ownGeneration, flyIn) {
  const result = await readRun(runId, ownGeneration);
  if (generation !== ownGeneration) return;
  render(result);
  if (flyIn) showFlyIn(result);
  if (result.status === 'running') watch(runId, ownGeneration);
  else if (result.status === 'error') {
    $('error').textContent = runError(result.error);
    $('error').hidden = false;
  } else $('status').textContent = 'The X-ray is complete. Each finding links to its supporting record.';
}

// /?run=<id>: a saved run, as it finished. No new run starts; a running one is watched.
async function loadRun(runId) {
  stop(); controller = new AbortController();
  const ownGeneration = generation;
  $('error').hidden = true; $('status').textContent = `Opening X-ray run ${runId}.`;
  try {
    await openRun(runId, ownGeneration, false);
  } catch (error) {
    if (generation !== ownGeneration || error.name === 'AbortError') return;
    $('error').textContent = error.status === 404
      ? `No X-ray run "${runId}" on this server. The link may be from another server or an expired run. Start a new X-ray below.`
      : `Could not open X-ray run "${runId}": ${error.message}`;
    $('error').hidden = false; $('status').textContent = 'Every finding opens back to its source.';
  }
}

$('new-listing').addEventListener('click', () => {
  stop(); selected = null;
  history.replaceState(null, '', withRun(location.href, null));
  const flyin = $('flyin'); if (flyin) { flyin.hidden = true; }
  $('intro').hidden = false; $('results').hidden = true; $('start').disabled = false; $('error').hidden = true;
  $('status').textContent = 'Every finding opens back to its source.';
  $('listing').focus(); window.scrollTo({ top: 0, behavior: 'instant' });
});
window.addEventListener('pagehide', stop);
for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => setView(button.dataset.view));

if (mockup) {
  $('prototype').hidden = false; $('listing').value = 'illustrative-listing';
  const state = new URLSearchParams(location.search).get('state');
  if (state === 'result' || state === 'detail') {
    const { prototype } = await import('./prototype.js'); render(prototype);
    if (state === 'detail') showFinding(prototype.findings[0].id);
  }
  if (state === 'error') { $('error').textContent = 'The source is unavailable. Check the listing and try again.'; $('error').hidden = false; }
}

const linkedRun = mockup ? null : runFromSearch(location.search);
if (linkedRun) loadRun(linkedRun);
