// "The place, from every source": Street View, satellite and map saved once by
// scripts/record_place_imagery.py, beside the advert's own photos. Pages never call Google.
import { safeUrl } from './data.js';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2022-05" -> "May 2022", "2026-11-12" -> "12 Nov 2026"; anything else as given. */
export function dateText(value) {
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/.exec(String(value || ''));
  if (!m || !MONTHS[m[2] - 1]) return value ? String(value) : '';
  return `${m[3] ? `${Number(m[3])} ` : ''}${MONTHS[m[2] - 1]} ${m[1]}`;
}

/** Tiles in display order with their grid size, or [] when no imagery was saved for this listing. */
export function placeTiles(manifest, result) {
  const base = `/static/images/places/${encodeURIComponent(manifest?.listing_id || '')}/`;
  const saved = (Array.isArray(manifest?.tiles) ? manifest.tiles : [])
    .filter(t => t && typeof t.file === 'string' && /^[\w.-]+$/.test(t.file))
    .sort((a, b) => (b.kind === 'streetview') - (a.kind === 'streetview'))
    .map(t => ({
      src: base + t.file, label: t.label || t.source, source: t.source, url: safeUrl(t.url),
      date: t.date ? `${t.date_note === 'captured' ? 'Captured' : 'Fetched'} ${dateText(t.date)}` : '',
      attribution: manifest.attribution || 'Imagery © Google',
    }));
  if (!saved.length) return [];
  // Two advert photos keep the strip to two rows; the full set is in the advert itself.
  const adverts = (result?.place?.photos || []).filter(p => safeUrl(p?.url)).slice(0, 2).map(p => ({
    src: safeUrl(p.url), label: 'In the advert', source: 'The listing’s own photo',
    url: safeUrl(p.source_url) || safeUrl(p.url), date: '', attribution: '',
  }));
  const tiles = [...saved, ...adverts];
  const rest = tiles.length - 1;
  return tiles.map((t, i) => ({ ...t, size: i === 0 ? 'hero' : rest === 2 ? 'tall' : rest % 2 && i === rest ? 'wide' : '' }));
}

function tileNode(t) {
  const a = document.createElement('a');
  a.className = `place-tile ${t.size}`.trim();
  if (t.url) { a.href = t.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
  const img = document.createElement('img');
  img.src = t.src; img.alt = `${t.label}, ${t.source}`; img.loading = 'lazy';
  img.addEventListener('error', () => a.remove(), { once: true });
  const caption = document.createElement('span'); caption.className = 'place-caption';
  const label = document.createElement('span'); label.className = 'place-label'; label.textContent = t.label;
  const meta = document.createElement('span'); meta.className = 'place-meta'; meta.textContent = [t.source, t.date].filter(Boolean).join(' · ');
  caption.append(label, meta);
  a.append(img, caption);
  if (t.attribution) { const c = document.createElement('span'); c.className = 'place-credit'; c.textContent = t.attribution; a.append(c); }
  return a;
}

const manifests = new Map();

/** Fill `section` for this run's listing, or hide it when nothing was saved. Safe to call on every render. */
export async function renderPlaces(section, result) {
  const id = result?.listing_id;
  section.dataset.want = id || '';
  if (!id) { section.hidden = true; return; }
  if (!manifests.has(id)) {
    manifests.set(id, fetch(`/static/images/places/${encodeURIComponent(id)}/places.json`)
      .then(r => (r.ok ? r.json() : null)).catch(() => null));
  }
  const manifest = await manifests.get(id);
  if (section.dataset.want !== id) return; // a newer listing replaced this one while it loaded
  const tiles = placeTiles(manifest, result);
  const key = `${id}|${tiles.length}`;
  if (section.dataset.key === key) return;
  section.dataset.key = key;
  section.hidden = !tiles.length;
  section.querySelector('.places-grid').replaceChildren(...tiles.map(tileNode));
}
