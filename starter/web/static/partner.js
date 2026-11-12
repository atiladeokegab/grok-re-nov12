import { safeUrl } from './data.js';
import { renderMap } from './partner-map.js';

const LABELS = { property_type: 'Property type', tenure: 'Tenure' };
const format = value => Number.isInteger(value) ? value.toLocaleString('en-GB') : 'not recorded';

export function filterFlags(rows, check, query) {
  const needle = query.trim().toLowerCase();
  return rows.filter(row => (!check || row.check === check) && [row.address, row.listing_id,
    row.record_address, row.advert_value, row.record_label].join(' ').toLowerCase().includes(needle));
}

export function validateScan(data) {
  if (data?.schema_version !== 1 || !Number.isInteger(data.rows_scanned) || !Array.isArray(data.flags)
      || data.flags.length !== data.flagged_comparisons
      || data.flags.some(row => !row || !LABELS[row.check] || typeof row.listing_id !== 'string')
      || new Set(data.flags.map(row => row.listing_id)).size !== data.flagged_listings
      || data.flagged_listings > data.rows_scanned) {
    throw new Error('The recorded partner scan is incomplete.');
  }
  return data;
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function start() {
  const $ = id => document.getElementById(id);
  let data;
  function render() {
    const matches = filterFlags(data.flags, $('partner-check').value, $('partner-search').value);
    const rows = matches.slice(0, 5).map(flag => {
      const row = node('tr'); row.dataset.listing = flag.listing_id;
      const listing = node('th'); listing.scope = 'row';
      const href = safeUrl(flag.url);
      const name = node(href ? 'a' : 'span', flag.address || flag.listing_id);
      if (href) { name.href = href; name.target = '_blank'; name.rel = 'noopener noreferrer'; }
      listing.append(name, node('span', flag.listing_id, 'partner-note'));
      const record = node('td', `${flag.record_label} (${flag.record_value})`);
      record.append(node('span', [flag.record_address, flag.record_date].filter(Boolean).join(' · '), 'partner-note'));
      row.append(listing, node('td', LABELS[flag.check]), node('td', flag.advert_value), record);
      return row;
    });
    if (!rows.length) {
      const row = node('tr'); const cell = node('td', 'No flagged comparisons match these filters.');
      cell.colSpan = 4; row.append(cell); rows.push(row);
    }
    $('partner-rows').replaceChildren(...rows);
    $('partner-showing').textContent = `Showing ${Math.min(matches.length, 5)} of ${format(matches.length)} flagged comparisons. Search or choose a check to narrow the list.`;
  }
  async function load() {
    $('partner-retry').hidden = true; $('partner-error').hidden = true;
    $('partner-results').hidden = true; $('partner-title').textContent = 'Loading the recorded partner-data scan…';
    try {
      const response = await fetch('/static/partner-scan.json', { signal: AbortSignal.timeout(15000) });
      if (!response.ok) throw new Error(`The recorded scan could not be loaded (${response.status}).`);
      data = validateScan(await response.json());
      const total = node('span', format(data.rows_scanned)); total.dataset.count = data.rows_scanned;
      const flagged = node('span', format(data.flagged_listings)); flagged.dataset.count = data.flagged_listings;
      $('partner-title').replaceChildren('Ran across all ', total, ' partner listings · flagged ', flagged);
      renderMap(data);
      $('partner-coverage').textContent = `Property type: ${format(data.checks?.property_type?.comparable)} comparisons, ${format(data.checks?.property_type?.flagged)} flags. Tenure: ${format(data.checks?.tenure?.comparable)} comparisons, ${format(data.checks?.tenure?.flagged)} flags. ${format(data.confidence_rows?.high)} rows were labelled high confidence.`;
      $('partner-missing').textContent = `${format(data.price_context?.context)} dated sale-price comparisons retained as context, never flags. Unverifiable price fields: ${format(data.unverifiable_missing_values?.price)}; size fields: ${format(data.unverifiable_missing_values?.size)}.`;
      $('partner-source').textContent = `Source: ${data.source?.file || 'supplied CSV'} · SHA256 ${data.source?.sha256 || 'not recorded'}`;
      $('partner-results').hidden = false; render();
    } catch (error) {
      $('partner-title').textContent = 'Partner-data scan unavailable';
      $('partner-error').textContent = error.message; $('partner-error').hidden = false;
      $('partner-retry').hidden = false;
    }
  }
  $('partner-check').addEventListener('change', render);
  $('partner-search').addEventListener('input', render);
  $('partner-retry').addEventListener('click', load);
  await load();
}

if (typeof document !== 'undefined') start();
