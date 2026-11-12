// The "Inside" view: the property reconstructed from the advert's room schedule, beside the facts a
// renter or analyst asks first, each with its source.
import { safeUrl } from './data.js';

const SVG = 'http://www.w3.org/2000/svg';
const UPSTAIRS = /bed|dressing|en-?suite|landing/i;

// Shelf packing: rooms in rows, long side horizontal, tallest first, wrapped at a near-square width.
// shortcut: rooms keep their schedule sizes and gaps stay empty, so it is plausible rather than the real plan.
export function packRooms(rooms) {
  const sized = rooms
    .filter(r => r.width_m > 0 && r.length_m > 0)
    .map(r => ({ ...r, w: Math.max(r.width_m, r.length_m), h: Math.min(r.width_m, r.length_m) }))
    .sort((a, b) => b.h - a.h || b.w - a.w);
  const area = sized.reduce((sum, r) => sum + r.w * r.h, 0);
  const width = Math.max(Math.sqrt(area) * 1.3, ...sized.map(r => r.w));
  let x = 0, y = 0, rowH = 0, used = 0;
  const placed = [];
  for (const r of sized) {
    if (x > 0 && x + r.w > width + 1e-9) { y += rowH; x = 0; rowH = 0; }
    placed.push({ ...r, x, y });
    x += r.w; rowH = Math.max(rowH, r.h); used = Math.max(used, x);
  }
  return { width: used, height: y + rowH, rooms: placed };
}

// A house whose advert mentions an upper floor gets its bedrooms drawn upstairs; anything else is one floor.
export function splitFloors(rooms, text = '') {
  const up = rooms.filter(r => UPSTAIRS.test(r.name));
  if (!/first floor|upstairs|second floor/i.test(text) || !up.length || up.length === rooms.length) return [{ name: 'Floor plan', rooms }];
  return [{ name: 'Ground floor', rooms: rooms.filter(r => !UPSTAIRS.test(r.name)) }, { name: 'First floor', rooms: up }];
}

const money = /£\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:pcm|pw|p\.c\.m\.?|per calendar month|per month|per week|per annum|pa))?(?:\s*\((?:inc|exc)[^)]*\))?/gi;

// Rent, deposit and fees named in the advert text. Each is the clause it came from, so the reader sees the words.
export function advertMoney(text = '') {
  const out = { rent: null, deposit: null, fees: [] };
  for (const m of text.matchAll(money)) {
    const before = text.slice(Math.max(0, m.index - 170), m.index);
    const cut = Math.max(before.lastIndexOf('. '), before.lastIndexOf(' - '), before.lastIndexOf(': '));
    const clause = `${before.slice(cut + 2).trim()} ${m[0]}`.trim();
    if (/pcm|per (?:calendar )?month|per week|\bpw\b|\brent/i.test(clause)) out.rent ??= clause;
    else if (/deposit/i.test(clause)) out.deposit ??= clause;
    else if (/\bfees?\b|premium|charge|commission|holding/i.test(clause) && !out.fees.includes(clause)) out.fees.push(clause);
  }
  return out;
}

// The advert's own words about the inside: its description from "comprising" or "Accommodation".
export function insideDescription(text = '') {
  const at = text.search(/\bcompris|\bAccommodation\b/i);
  if (at < 0) return '';
  const nav = text.lastIndexOf('Previous Next', at); // the listing page's carousel buttons sit right before the copy
  const start = Math.max(text.lastIndexOf('. ', at) + 2, nav >= 0 && at - nav < 200 ? nav + 14 : at - 120, 0);
  const stop = text.slice(at).search(/\b(Situation|Location|Energy Efficiency|Viewing)\b/);
  const slice = text.slice(start, Math.min(start + 480, stop > 0 ? at + stop : Infinity));
  const end = slice.lastIndexOf('.');
  return end > 60 ? slice.slice(0, end + 1).trim() : slice.trim();
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function svgEl(tag, attrs, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

const PX = 56; // pixels per metre inside the viewBox; the SVG scales to its column
const PAD = 30;

function drawFloor(floor) {
  const pack = packRooms(floor.rooms);
  const w = pack.width * PX, h = pack.height * PX;
  const svg = svgEl('svg', { viewBox: `${-PAD} ${-PAD - 22} ${w + PAD * 2} ${h + PAD * 2 + 22}`, role: 'img', class: 'inside-plan' });
  const total = floor.rooms.reduce((s, r) => s + (r.area_m2 || r.width_m * r.length_m), 0);
  svg.append(svgEl('title', {}, `${floor.name}: ${floor.rooms.length} rooms, ${total.toFixed(1)} m²`));
  svg.append(svgEl('text', { x: 0, y: -12, class: 'plan-floor' }, `${floor.name} · ${total.toFixed(1)} m²`));
  svg.append(svgEl('rect', { x: 0, y: 0, width: w, height: h, class: 'plan-footprint' }));
  for (const r of pack.rooms) {
    const g = svgEl('g', { class: `plan-room${UPSTAIRS.test(r.name) || /bed/i.test(r.name) ? ' plan-room-private' : ''}` });
    const rx = r.x * PX, ry = r.y * PX, rw = r.w * PX, rh = r.h * PX;
    g.append(svgEl('rect', { x: rx, y: ry, width: rw, height: rh }));
    const small = rw < 160 || rh < 90;
    const cx = rx + rw / 2, cy = ry + rh / 2;
    g.append(svgEl('text', { x: cx, y: cy - (small ? 4 : 8), class: small ? 'plan-name plan-small' : 'plan-name' }, r.name));
    g.append(svgEl('text', { x: cx, y: cy + (small ? 10 : 14), class: small ? 'plan-area plan-small' : 'plan-area' }, small ? `${(r.area_m2 || r.w * r.h).toFixed(1)} m²` : `${(r.area_m2 || r.w * r.h).toFixed(1)} m² · ${r.width_m}×${r.length_m} m`));
    g.append(svgEl('title', {}, `${r.name}: ${r.width_m} m × ${r.length_m} m, ${(r.area_m2 || r.w * r.h).toFixed(1)} m²`));
    svg.append(g);
  }
  // scale bar: 1 m
  svg.append(svgEl('path', { d: `M${w - PX} ${h + 8}h${PX}`, class: 'plan-scale' }), svgEl('text', { x: w - PX / 2, y: h + 24, class: 'plan-area' }, '1 m'));
  return svg;
}

const gbp = n => `£${Math.round(n).toLocaleString('en-GB')}`;
const listingUrl = result => (result.claims || []).find(c => c.source === 'listing')?.source_url;

function sourceLink(label, url) {
  const href = safeUrl(url);
  if (!href) return el('span', label, 'inside-source');
  const a = el('a', label, 'inside-source'); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
  return a;
}

export function insideFacts(result, text, schedule) {
  const claim = f => (result.claims || []).find(c => c.field === f);
  const epc = f => (result.evidence || []).find(e => e.field === f && e.agent === 'epc');
  const advert = listingUrl(result);
  const m = advertMoney(text);
  const facts = [];
  const price = claim('price');
  const status = claim('sale_status')?.value;
  facts.push(['Price', price ? `${gbp(price.value)}${status ? ` · ${status}` : ''}` : 'Not stated in the advert', price ? ['Advert', price.source_url] : ['Advert text', advert]]);
  facts.push(['Rent', m.rent || 'Not stated in the advert', ['Advert text', advert]]);
  facts.push(['Deposit', m.deposit || 'Not stated in the advert', ['Advert text', advert]]);
  facts.push(['Fees', m.fees.length ? m.fees.join(' · ') : 'Not stated in the advert', ['Advert text', advert]]);
  const tax = text.match(/Council Tax\s*[-:]?\s*Band\s*([A-H])\b/i);
  facts.push(['Council tax', tax ? `Band ${tax[1].toUpperCase()}` : 'Not stated in the advert', ['Advert text', advert]]);
  const stated = claim('floor_area')?.value ?? schedule?.stated_m2;
  const epcArea = epc('floor_area');
  facts.push(['Floor area', null, null, [
    ['Advert states', stated ? `${stated} m²` : 'Not stated', ['Advert', advert]],
    ['Rooms add up to', schedule ? `${schedule.rooms_m2} m²` : 'No room schedule', ['Room schedule', advert]],
    ['EPC records', epcArea ? `${epcArea.value} m²` : 'No EPC area', ['EPC register', epcArea?.source_url]],
  ]]);
  const rating = epc('energy_rating') || claim('energy_rating');
  facts.push(['Energy rating', rating ? `EPC ${rating.value}` : 'Not found', [rating?.agent === 'epc' ? 'EPC register' : 'Advert', rating?.source_url]]);
  const beds = claim('bedrooms');
  facts.push(['Bedrooms', beds ? beds.value : 'Not stated in the advert', ['Advert', beds?.source_url || advert]]);
  const type = claim('property_type'), tenure = claim('tenure') || (result.evidence || []).find(e => e.field === 'tenure');
  if (type || tenure) facts.push(['Type', [type?.value, tenure?.value].filter(Boolean).join(' · '), ['Advert', advert]]);
  return facts;
}

const cache = new Map();
async function advertText(result) {
  const doc = (result.documents || []).find(d => d.agent === 'listing_history' && !String(d.url).includes('#')) ||
    (result.documents || []).find(d => d.agent === 'listing_history');
  if (!doc) return '';
  if (!cache.has(doc.id)) cache.set(doc.id, fetch(`/api/document/${encodeURIComponent(doc.id)}`).then(r => (r.ok ? r.json() : {})).then(d => d.text || '').catch(() => ''));
  return cache.get(doc.id);
}

export async function renderInside(container, result) {
  const text = await advertText(result);
  const schedule = (result.evidence || []).find(e => e.field === 'room_schedule')?.value;
  const rooms = schedule?.rooms || [];
  const wrap = el('div', null, 'inside');
  const planCol = el('figure', null, 'inside-plan-col');
  if (rooms.length) {
    const floors = splitFloors(rooms, text);
    const plans = el('div', null, `inside-plans inside-floors-${floors.length}`);
    for (const floor of floors) plans.append(drawFloor(floor));
    planCol.append(plans, el('figcaption', `Layout is approximate: drawn from the advert’s room sizes, to scale. ${floors.length > 1 ? 'Floors are inferred from room names. ' : ''}The outline is the rooms’ bounding box; halls, stairs and walls are not in the schedule.`, 'inside-note'));
  } else {
    planCol.append(el('p', 'No room dimensions were recorded for this listing. Its description and sourced facts remain available below.', 'inside-empty'));
  }
  const words = insideDescription(text);
  if (words) {
    const quote = el('blockquote', null, 'inside-quote');
    quote.append(el('p', words), sourceLink('The advert’s description', listingUrl(result)));
    planCol.append(quote);
  }
  const facts = el('dl', null, 'inside-facts');
  for (const [label, value, source, rows] of insideFacts(result, text, schedule)) {
    const row = el('div', null, 'inside-fact');
    row.append(el('dt', label));
    const dd = el('dd');
    if (rows) {
      const list = el('ul', null, 'inside-area');
      for (const [l, v, [s, u]] of rows) { const li = el('li'); li.append(el('span', l), el('strong', v), sourceLink(s, u)); list.append(li); }
      dd.append(list);
    } else {
      dd.append(el('span', value, /^Not /.test(String(value)) ? 'inside-missing' : 'inside-value'), sourceLink(source[0], source[1]));
    }
    row.append(dd); facts.append(row);
  }
  wrap.append(planCol, facts);
  const photos = (result.place?.photos || []).map(p => safeUrl(p.url)).filter(Boolean);
  const strip = el('div', null, 'inside-photos');
  strip.setAttribute('aria-label', 'Listing photographs');
  for (const [i, src] of photos.entries()) {
    const img = el('img'); img.src = src; img.loading = 'lazy'; img.alt = `Listing photograph ${i + 1} of ${photos.length}`;
    img.addEventListener('error', () => img.remove(), { once: true });
    strip.append(img);
  }
  if (!photos.length) strip.append(el('p', 'The advert supplied no photographs.', 'inside-missing'));
  planCol.append(strip);
  container.replaceChildren(wrap);
}
