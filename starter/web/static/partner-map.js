import { safeUrl } from './data.js';

const NS = 'http://www.w3.org/2000/svg';
const LABELS = { property_type: 'Property type', tenure: 'Tenure' };

export function mapPoints(data) {
  const flags = new Map();
  for (const flag of data.flags) {
    if (!flags.has(flag.listing_id)) flags.set(flag.listing_id, []);
    flags.get(flag.listing_id).push(flag);
  }
  let missing = 0;
  return data.map_points.map(([id, lat, lon]) => {
    const located = Number.isFinite(lat) && Number.isFinite(lon);
    const index = located ? 0 : missing++;
    return { id, located, flags: flags.get(id) || [],
      x: located ? 110 + (lon + 8) * 26 : 28 + (index % 100) * 4.5,
      y: located ? 20 + (59 - lat) * 42 : 454 + Math.floor(index / 100) * 3.5,
      region: located ? Math.max(0, Math.min(4, Math.floor((59 - lat) / 2))) : 5 };
  });
}

function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (className) el.className = className;
  return el;
}

export function renderMap(data) {
  const mount = document.getElementById('partner-map');
  if (!mount || !Array.isArray(data.map_points)) return;
  const points = mapPoints(data);
  const flagged = points.filter(point => point.flags.length);
  const located = points.filter(point => point.located).length;
  const figure = node('figure', null, 'partner-map');
  const visual = node('div', null, 'partner-map-visual');
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 500 510');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `${located.toLocaleString('en-GB')} listings at supplied coordinates; ${points.length - located} in the location unavailable strip. ${flagged.length} flagged for column review. Select a flagged listing below for its details.`);
  const groups = Array.from({ length: 6 }, (_, index) => {
    const group = document.createElementNS(NS, 'g');
    group.setAttribute('class', 'partner-map-region');
    group.style.setProperty('--region-delay', `${index * 180}ms`);
    svg.append(group); return group;
  });
  const circles = new Map();
  for (const point of [...points.filter(p => !p.flags.length), ...flagged]) {
    const circle = document.createElementNS(NS, 'circle');
    circle.setAttribute('cx', point.x); circle.setAttribute('cy', point.y);
    circle.setAttribute('r', point.flags.length ? (point.located ? '2.5' : '1.6') : (point.located ? '1.15' : '.75'));
    circle.setAttribute('class', point.flags.length ? 'partner-map-dot is-flagged' : 'partner-map-dot');
    circle.dataset.listing = point.id;
    if (point.flags.length) {
      const title = document.createElementNS(NS, 'title');
      title.textContent = `${point.flags[0].address} · ${point.flags.map(f => LABELS[f.check]).join(', ')} · review required`;
      circle.append(title); circles.set(point.id, circle);
    }
    groups[point.region].append(circle);
  }
  visual.append(svg, node('p', `${(points.length - located).toLocaleString('en-GB')} location unavailable · bottom strip is not geographic`, 'partner-map-location-note'));
  const side = node('figcaption', null, 'partner-map-detail');
  side.append(node('p', 'The partner footprint', 'partner-map-eyebrow'), node('h3', 'Every listing. One view.'));
  side.append(node('p', `${located.toLocaleString('en-GB')} supplied locations form the map. The strip holds listings without coordinates. Positions are rounded to 3 decimals.`));
  const legend = node('p', null, 'partner-map-legend');
  legend.append(node('span', '● No column flag', 'partner-map-clear'), node('span', '◉ Flagged for review', 'partner-map-flag'));
  side.append(legend);
  const label = node('label', 'Explore a flagged listing');
  const select = node('select'); select.setAttribute('aria-label', 'Explore a flagged listing');
  for (const point of flagged) {
    const option = node('option', `${point.flags[0].address || point.id} · ${point.flags.map(f => LABELS[f.check]).join(', ')}`);
    option.value = point.id; select.append(option);
  }
  label.append(select); side.append(label);
  const details = node('div', null, 'partner-map-selection');
  details.setAttribute('aria-live', 'polite'); side.append(details);
  let selected;
  function show(id) {
    const point = flagged.find(p => p.id === id);
    if (!point || selected === id) return;
    if (selected) circles.get(selected)?.classList.remove('is-selected');
    selected = id; select.value = id; circles.get(id)?.classList.add('is-selected');
    const first = point.flags[0];
    const heading = node('h4', first.address || id);
    const checks = node('ul');
    for (const flag of point.flags) {
      checks.append(node('li', `${LABELS[flag.check]}: advert “${flag.advert_value}” · supplied record “${flag.record_label}”`));
    }
    details.replaceChildren(heading, checks, node('p', 'Supplied-column difference: review the joined unit before relying on it.', 'partner-map-caveat'));
    const href = safeUrl(first.url);
    if (href) {
      const link = node('a', 'Open the advert ↗'); link.href = href;
      link.target = '_blank'; link.rel = 'noopener noreferrer'; details.append(link);
    }
  }
  select.addEventListener('change', () => show(select.value));
  for (const event of ['pointerover', 'click']) {
    svg.addEventListener(event, e => {
      const circle = e.target.closest?.('.is-flagged');
      if (circle) show(circle.dataset.listing);
    });
  }
  figure.append(visual, side); mount.replaceChildren(figure);
  if (flagged.length) show(flagged[0].id);
}

