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

export const MATRIX = [
  ['Floor area', ['floor_area']],
  ['Property type', ['property_type']],
  ['Energy rating', ['energy_rating']],
  ['Photos', ['photo_reuse', 'image_reuse']],
  ['Tenure', ['tenure']],
];
const VERDICT = { matches: 'Match', disagrees: 'Mismatch', flag: 'Flag', unverifiable: 'Unverifiable' };

function show(value, field) {
  if (field === 'floor_area' && typeof value === 'number') return `${number.format(value)} m²`;
  return String(value).replace(/ house$/, '');
}

// One matrix cell: the finding's verdict, a short value, and the record that backs it.
export function cell(report, fields) {
  const finding = (report.findings || []).find(f => fields.includes(f.field));
  const claim = (report.claims || []).find(c => fields.includes(c.field) && c.value != null && sourcePresent(c));
  const usable = e => fields.includes(e.field) && e.value != null && sourcePresent(e) && !e.observed_at;
  const evidence = (report.evidence || []).filter(usable);
  const ev = evidence.find(e => finding?.evidence_ids?.includes(e.id)) || evidence.find(e => e.agent === 'epc');
  let verdict = VERDICT[finding?.verdict] ? finding.verdict : 'unverifiable';
  if (verdict !== 'unverifiable' && !ev && !claim) verdict = 'unverifiable'; // missing evidence is never a match
  const field = fields[0];
  const a = claim && show(claim.value, field); const b = ev && show(ev.value, field);
  let text;
  if (field === 'photo_reuse') text = verdict === 'flag' || verdict === 'disagrees' ? `${b ?? 'Some'} reused` : verdict === 'matches' ? 'Original' : 'Not checked';
  else if (a && b && verdict === 'disagrees') text = `${a} ≠ ${b}`;
  else if (!a && b) text = `${b} (not in ad)`;
  else text = a ?? b ?? 'Not stated';
  return { verdict, text, note: finding?.reasoning || VERDICT[verdict], href: ev?.source_url || claim?.source_url || null };
}

// Advert, floor-plan room total and EPC floor area, each with its source record.
export function areas(report) {
  const data = facts(report);
  const rooms = data.rooms?.value?.rooms_m2;
  return [
    ['advert', 'Advert', data.advertArea],
    ['rooms', 'Floor-plan rooms', typeof rooms === 'number' ? { ...data.rooms, value: rooms } : null],
    ['epc', 'EPC', data.epcArea],
  ].map(([key, label, record]) => ({ key, label, value: typeof record?.value === 'number' ? record.value : null, href: record?.source_url || null }));
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

const shortName = listing => listing.title.split(',')[0];

function renderCard({ listing, report, error }) {
  const item = node('li', undefined, 'analyst-card'); item.dataset.listing = listing.name;
  const link = node('a'); link.href = report ? reportURL(report) : listing.url || '/';
  const image = node('img'); image.alt = ''; image.loading = 'lazy';
  image.src = `/static/images/places/${encodeURIComponent(listing.listing_id)}/streetview.jpg`;
  image.addEventListener('error', () => image.replaceWith(node('span', undefined, 'analyst-photo-missing')));
  const scored = (report?.counts?.matches || 0) + (report?.counts?.disagrees || 0) > 0; // flags alone are no score
  const value = scored ? score(report?.trust_score) : null;
  const scoreRow = node('div', undefined, 'analyst-card-score');
  const big = node('span', report ? (value == null ? '–' : String(value)) : '–', 'analyst-score');
  scoreRow.append(big, node('span', value == null ? (report ? 'Unscored' : error) : 'Trust / 100', 'analyst-card-note'));
  const bar = node('span', undefined, 'analyst-bar'); bar.setAttribute('aria-hidden', 'true');
  const fill = node('span', undefined, 'analyst-bar-fill'); fill.style.width = `${value ?? 0}%`; bar.append(fill);
  const claim = f => (report?.claims || []).find(c => c.field === f && c.value != null);
  const price = claim('price')?.value; const beds = claim('bedrooms')?.value;
  const meta = [beds != null && `${beds} bed`, typeof price === 'number' && valueText(price, 'GBP')].filter(Boolean).join(' · ');
  const counts = report?.counts || {};
  const tally = node('span', undefined, 'analyst-tally');
  for (const k of ['matches', 'disagrees', 'flag', 'unverifiable']) {
    if (!counts[k]) continue;
    const t = node('span'); t.append(node('i', undefined, 'dot'), String(counts[k])); t.firstChild.dataset.verdict = k;
    t.title = `${counts[k]} ${VERDICT[k].toLowerCase()}`; tally.append(t);
  }
  scoreRow.append(tally);
  link.append(image, scoreRow, bar, node('strong', shortName(listing), 'analyst-card-title'), node('span', meta || listing.title.split(',').slice(1).join(',').trim(), 'analyst-card-note'));
  item.append(link);
  return item;
}

function renderMatrix(entries) {
  const head = document.getElementById('analyst-matrix-head');
  head.replaceChildren(node('th', 'Field'), ...entries.map(({ listing }) => {
    const th = node('th', shortName(listing)); th.scope = 'col'; return th;
  }));
  head.firstChild.scope = 'col';
  return MATRIX.map(([label, fields]) => {
    const row = node('tr'); row.dataset.field = fields[0];
    const th = node('th', label); th.scope = 'row'; row.append(th);
    for (const { report } of entries) {
      const td = node('td');
      if (!report) { td.append(node('span', 'No report', 'analyst-unavailable')); row.append(td); continue; }
      const c = cell(report, fields);
      const link = sourceLink('', c.href, reportURL(report));
      const dot = node('i', undefined, 'dot'); dot.dataset.verdict = c.verdict;
      link.append(dot, node('span', c.text)); link.title = `${VERDICT[c.verdict]}: ${c.note}`;
      link.setAttribute('aria-label', `${VERDICT[c.verdict]}, ${c.text}`);
      td.append(link); row.append(td);
    }
    return row;
  });
}

const SVG = 'http://www.w3.org/2000/svg';
function svg(tag, attrs, text) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

function renderChart(entries) {
  const W = 560, H = 196, top = 16, base = 168, left = 32, bar = 22, gap = 2;
  const groups = entries.map(({ listing, report }) => ({ listing, report, bars: report ? areas(report) : [] }));
  const max = Math.max(20, ...groups.flatMap(g => g.bars.map(b => b.value ?? 0)));
  const step = max > 100 ? 40 : 20; const top_ = Math.ceil(max / step) * step;
  const y = v => base - (v / top_) * (base - top);
  const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-labelledby': 'chart-title' });
  for (let t = 0; t <= top_; t += step) {
    root.append(svg('line', { x1: left, x2: W, y1: y(t), y2: y(t), class: t ? 'grid' : 'axis' }));
    root.append(svg('text', { x: left - 6, y: y(t) + 4, 'text-anchor': 'end', class: 'tick' }, String(t)));
  }
  const slot = (W - left) / groups.length;
  groups.forEach((g, i) => {
    const cx = left + slot * i + slot / 2; const x0 = cx - (3 * bar + 2 * gap) / 2;
    g.bars.forEach((b, j) => {
      const x = x0 + j * (bar + gap);
      if (b.value == null) { root.append(svg('text', { x: x + bar / 2, y: base - 4, 'text-anchor': 'middle', class: 'none' }, '–')); return; }
      const h = base - y(b.value); const r = Math.min(4, h);
      const a = svg('a', { href: b.href || reportURL(g.report), target: '_blank', rel: 'noopener noreferrer' });
      a.append(svg('path', { d: `M${x},${base}V${base - h + r}q0,-${r} ${r},-${r}h${bar - 2 * r}q${r},0 ${r},${r}V${base}Z`, class: `bar ${b.key}` }));
      a.append(svg('title', {}, `${shortName(g.listing)} · ${b.label}: ${number.format(b.value)} m²`));
      a.append(svg('text', { x: x + bar / 2, y: base - h - 5, 'text-anchor': 'middle', class: 'value' }, number.format(Math.round(b.value))));
      root.append(a);
    });
    if (!g.bars.some(b => b.value != null)) root.append(svg('text', { x: cx, y: base - 24, 'text-anchor': 'middle', class: 'none' }, 'No area on record'));
    root.append(svg('text', { x: cx, y: base + 18, 'text-anchor': 'middle', class: 'label' }, shortName(g.listing)));
  });
  return root;
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
      entries.sort((a, b) => (score(b.report?.trust_score) ?? -1) - (score(a.report?.trust_score) ?? -1));
      $('analyst-cards').replaceChildren(...entries.map(renderCard));
      $('analyst-rows').replaceChildren(...renderMatrix(entries));
      $('analyst-chart').replaceChildren(renderChart(entries));
      const count = entries.filter(entry => entry.report).length;
      $('analyst-status').textContent = `${count} of ${entries.length} saved reports ready`;
      $('analyst-download').disabled = !count;
      $('analyst-retry').hidden = count === entries.length;
    } catch (error) {
      entries = [];
      $('analyst-cards').replaceChildren(); $('analyst-rows').replaceChildren(); $('analyst-chart').replaceChildren();
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
      $('analyst-status').textContent = `Downloaded ${exports.length} reports with sources`;
    } catch (error) { $('analyst-error').textContent = error.message; $('analyst-error').hidden = false; }
    finally { $('analyst-download').disabled = !entries.some(entry => entry.report); }
  });
  await load();
}

if (typeof document !== 'undefined') start();
