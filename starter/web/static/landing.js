// Landing motion: the scan totals count up, and a ticker of real flagged rows from the recorded partner scan.
const moving = () => Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: no-preference)').matches);

/** Count [data-count] elements up from 0 (ending on their exact text); marks them so analyst.js skips them. */
export function countUp(elements) {
  for (const el of elements) {
    el.dataset.countAnimated = 'true';
    if (!moving()) continue;
    const final = el.textContent, target = Number(el.dataset.count), t0 = performance.now();
    const step = now => {
      const k = Math.min(1, Math.max(0, (now - t0) / 1000));
      el.textContent = k < 1 ? Math.round(target * (1 - (1 - k) ** 3)).toLocaleString('en-GB') : final;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}

/** ~n flagged rows spread across the scan, one per address: 'address · Advert: X → Land Registry: Y'. */
export function tickerItems(scan, n = 20) {
  const seen = new Set();
  const rows = (scan?.flags || []).filter(r => r.address && r.advert_value && r.record_label).map(r => ({
    address: String(r.address).split(' - ').pop().trim(), // the crawl's "Property for Auction in X - " page-title prefix
    text: `Advert: ${r.advert_value} → Land Registry: ${r.record_label}`,
  })).filter(r => !seen.has(r.address) && seen.add(r.address)); // one row per place
  const stride = Math.max(1, Math.floor(rows.length / n));
  return rows.filter((_, i) => i % stride === 0).slice(0, n);
}

export async function mountTicker(container, fetchJson = () => fetch('/static/partner-scan.json').then(r => (r.ok ? r.json() : null))) {
  const items = tickerItems(await fetchJson().catch(() => null));
  if (!items.length) return;
  const list = items => {
    const ul = document.createElement('ul');
    for (const item of items) {
      const a = document.createElement('a'); a.href = '/analyst#partner-scan';
      const b = document.createElement('b'); b.textContent = item.address;
      a.append(b, ` · ${item.text}`);
      const li = document.createElement('li'); li.append(a); ul.append(li);
    }
    return ul;
  };
  const track = document.createElement('div'); track.className = 'scan-track';
  track.append(list(items));
  if (moving()) { const copy = list(items); copy.setAttribute('aria-hidden', 'true'); copy.querySelectorAll('a').forEach(a => { a.tabIndex = -1; }); track.append(copy); }
  container.replaceChildren(track);
  container.hidden = false;
}
