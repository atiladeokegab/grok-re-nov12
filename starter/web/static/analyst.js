import { safeUrl, sourcePresent, valueText } from './data.js';

const PINNED = {
  'macquarie-way': 'xr-6f65393159',
  'kimberley-road': 'xr-131a92ee3b',
  'charlemont-road': 'xr-f20b9504d5',
};
const number = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 });
const reportURL = run => `/?run=${encodeURIComponent(run.run_id)}`;

export function score(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
}

export function facts(report) {
  const claims = (Array.isArray(report.claims) ? report.claims : []).filter(sourcePresent);
  const evidence = (Array.isArray(report.evidence) ? report.evidence : []).filter(e => sourcePresent(e) && !e.observed_at);
  const claim = field => claims.find(c => c.field === field && c.value != null);
  const epc = field => evidence.find(e => e.agent === 'epc' && e.field === field && e.value != null);
  return {
    price: claim('price'), advertArea: claim('floor_area'), epcArea: epc('floor_area'),
    advertEnergy: claim('energy_rating'), epcEnergy: epc('energy_rating'),
    rooms: evidence.find(e => e.field === 'room_schedule'),
    photo: (report.findings || []).find(f => ['photo_reuse', 'image_reuse'].includes(f.field)),
  };
}

// An export may contain quoted commas, quotes and line breaks inside source excerpts.
export function csvRows(text) {
  const rows = []; let row = []; let cell = ''; let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
      else quoted = !quoted;
    } else if (!quoted && char === ',') { row.push(cell); cell = ''; }
    else if (!quoted && (char === '\n' || char === '\r')) {
      if (char === '\r' && text[i + 1] === '\n') i++;
      row.push(cell); rows.push(row); row = []; cell = '';
    } else cell += char;
  }
  if (quoted) throw new Error('A saved CSV export contains an incomplete quoted field.');
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

export function combineCSV(exports) {
  let header;
  const output = [];
  for (const { listing, report, text } of exports) {
    const [fields, ...rows] = csvRows(text);
    if (!fields?.length || (header && JSON.stringify(header) !== JSON.stringify(fields))) {
      throw new Error('The saved CSV exports have different columns. No file was downloaded.');
    }
    if (!header) { header = fields; output.push(['listing', 'listing_id', 'run_id', ...fields]); }
    for (const row of rows) {
      if (row.length !== fields.length) throw new Error('A saved CSV export has an incomplete row.');
      output.push([listing.title, report.listing_id, report.run_id, ...row]);
    }
  }
  return output.map(row => row.map(value => {
    let text = String(value ?? '');
    if (/^[\s]*[=+\-@]|^[\t\r]/.test(text)) text = `'${text}`; // Prevent spreadsheet formulas in source text.
    return `"${text.replaceAll('"', '""')}"`;
  }).join(',')).join('\r\n') + '\r\n';
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function sourceLink(text, source, fallback) {
  const link = node('a', text);
  let url;
  try { url = safeUrl(new URL(source || fallback, location.origin).href); } catch { /* use saved report */ }
  link.href = url || fallback;
  link.target = '_blank'; link.rel = 'noopener noreferrer';
  return link;
}

function factCell(record, report, formatter = String) {
  const cell = node('td');
  if (record?.value != null) cell.append(sourceLink(formatter(record.value), record.source_url, reportURL(report)));
  else cell.append(node('span', 'Not recorded', 'analyst-unavailable'));
  return cell;
}

function area(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `${number.format(value)} m²` : String(value);
}

function renderRow(entry) {
  const { listing, report, error } = entry;
  const row = node('tr'); row.dataset.listing = listing.name;
  const title = node('th'); title.scope = 'row';
  title.append(sourceLink(report?.place?.address || listing.title, report ? reportURL(report) : listing.url, '/'), node('span', report ? `Saved run ${report.run_id}` : error, 'analyst-cell-note'));
  title.querySelector('a').className = 'analyst-listing';
  row.append(title);
  if (!report) {
    const cell = node('td', 'No saved report available.'); cell.colSpan = 10; cell.className = 'analyst-unavailable';
    row.append(cell); return row;
  }
  const data = facts(report);
  row.append(factCell(data.price, report, v => typeof v === 'number' ? valueText(v, 'GBP') : String(v)));
  const value = score(report.trust_score);
  const scoreCell = node('td');
  scoreCell.append(sourceLink(value == null ? 'Unscored' : String(value), reportURL(report), '/'));
  scoreCell.className = 'analyst-score'; row.append(scoreCell);
  for (const [field, className] of [['matches', 'analyst-match'], ['disagrees', 'analyst-disagree'], ['unverifiable', 'analyst-unverified']]) {
    const count = report.counts?.[field];
    const cell = node('td', undefined, className);
    cell.append(sourceLink(Number.isInteger(count) && count >= 0 ? String(count) : 'Not recorded', reportURL(report), '/'));
    row.append(cell);
  }
  row.append(factCell(data.advertArea, report, area), factCell(data.epcArea, report, area));
  const rooms = data.rooms?.value?.rooms_m2;
  row.append(factCell(typeof rooms === 'number' ? { ...data.rooms, value: rooms } : null, report, area));
  const energy = node('td');
  for (const [label, record] of [['Advert', data.advertEnergy], ['EPC', data.epcEnergy]]) {
    const line = node('span', `${label}: `, 'analyst-cell-note');
    line.append(record ? sourceLink(String(record.value), record.source_url, reportURL(report)) : node('span', 'Not recorded'));
    energy.append(line);
  }
  row.append(energy);
  const photo = node('td');
  const photoEvidence = (report.evidence || []).find(e => data.photo?.evidence_ids?.includes(e.id) && sourcePresent(e));
  const verdict = photoEvidence ? data.photo?.verdict : 'unverifiable';
  const label = verdict === 'matches' ? 'Matches' : ['flag', 'disagrees'].includes(verdict) ? 'Review reuse' : 'Could not verify';
  photo.append(sourceLink(label, photoEvidence?.source_url, reportURL(report)));
  if (data.photo?.reasoning) photo.querySelector('a').title = data.photo.reasoning;
  row.append(photo);
  return row;
}

function renderBar({ listing, report }) {
  const row = node('li');
  const value = score(report?.trust_score);
  row.append(sourceLink(listing.title, report ? reportURL(report) : listing.url, '/'));
  const track = node('span', undefined, 'analyst-bar'); track.setAttribute('aria-hidden', 'true');
  const fill = node('span', undefined, 'analyst-bar-fill'); fill.style.width = `${value ?? 0}%`;
  track.append(fill); row.append(track, node('span', value == null ? 'Unscored' : `${value} / 100`, 'analyst-chart-score'));
  if (value == null) row.dataset.unscored = '';
  return row;
}

async function request(url, csv = false) {
  const response = await fetch(url, { headers: { Accept: csv ? 'text/csv' : 'application/json' }, signal: AbortSignal.timeout(15000) });
  if (!response.ok) {
    const error = new Error(response.status === 404 ? 'No saved report available.' : `Saved data unavailable (${response.status}).`);
    error.status = response.status; throw error;
  }
  if (csv && !response.headers.get('content-type')?.toLowerCase().startsWith('text/csv')) {
    throw new Error('The server did not return a CSV export. No file was downloaded.');
  }
  return csv ? response.text() : response.json();
}

async function savedReport(listing) {
  const pinned = listing.run_id || PINNED[listing.name];
  let report;
  if (pinned) {
    try { report = await request(`/api/xray/${encodeURIComponent(pinned)}`); }
    catch (error) { if (error.status !== 404) throw error; }
  }
  if (!report) {
    const graph = await request(`/api/place/${encodeURIComponent(`place-${listing.listing_id}`)}/graph`);
    if (typeof graph.run_id !== 'string') throw new Error('No saved run recorded for this listing.');
    report = await request(`/api/xray/${encodeURIComponent(graph.run_id)}`);
  }
  if (report.listing_id !== listing.listing_id) throw new Error('The saved report belongs to another listing.');
  if (report.status !== 'done') throw new Error('The saved report is not complete.');
  return report;
}

async function start() {
  const $ = id => document.getElementById(id);
  let entries = [];
  async function load() {
    $('analyst-main').setAttribute('aria-busy', 'true');
    $('analyst-retry').hidden = true; $('analyst-error').hidden = true;
    $('analyst-download').disabled = true; $('analyst-status').textContent = 'Loading saved reports…';
    try {
      const gallery = await request('/api/gallery');
      if (!Array.isArray(gallery)) throw new Error('The saved gallery could not be read.');
      const items = gallery.filter(item => item && typeof item.listing_id === 'string' && typeof item.title === 'string');
      if (!items.some(item => item.name === 'macquarie-way')) items.unshift({ name: 'macquarie-way', title: '24 Macquarie Way, E14', listing_id: 'auctionhouse-0715ecf1' });
      entries = await Promise.all(items.map(async listing => {
        try { return { listing, report: await savedReport(listing) }; }
        catch (error) { return { listing, error: error.message }; }
      }));
      $('analyst-rows').replaceChildren(...entries.map(renderRow));
      $('analyst-chart').replaceChildren(...entries.map(renderBar));
      const count = entries.filter(entry => entry.report).length;
      $('analyst-status').textContent = `${count} of ${entries.length} saved reports ready. Downloads include the ${count} available reports.`;
      $('analyst-download').disabled = !count;
      $('analyst-retry').hidden = count === entries.length;
    } catch (error) {
      entries = [];
      $('analyst-rows').replaceChildren(); $('analyst-chart').replaceChildren();
      $('analyst-error').textContent = error.message; $('analyst-error').hidden = false;
      $('analyst-status').textContent = 'Saved reports could not be loaded.'; $('analyst-retry').hidden = false;
    } finally { $('analyst-main').setAttribute('aria-busy', 'false'); }
  }
  $('analyst-retry').addEventListener('click', load);
  $('analyst-download').addEventListener('click', async () => {
    $('analyst-download').disabled = true; $('analyst-error').hidden = true;
    try {
      const exports = await Promise.all(entries.filter(entry => entry.report).map(async entry => ({ ...entry, text: await request(`/api/xray/${encodeURIComponent(entry.report.run_id)}/export.csv`, true) })));
      const csv = combineCSV(exports);
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
      const link = node('a'); link.href = url; link.download = 'xray-analyst.csv'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      $('analyst-status').textContent = `Downloaded ${exports.length} saved reports with their source records.`;
    } catch (error) { $('analyst-error').textContent = error.message; $('analyst-error').hidden = false; }
    finally { $('analyst-download').disabled = !entries.some(entry => entry.report); }
  });
  await load();
}

if (typeof document !== 'undefined') start();
