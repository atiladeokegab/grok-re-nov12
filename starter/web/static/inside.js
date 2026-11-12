// The "Inside" view: the property reconstructed from the advert's room schedule, beside the facts a
// analyst asks first, each with its source.
// Walk-through controls adapted from sesasa/3d-house-walkthrough (MIT, (c) 2026 Saeed Asadzadeh).
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

// The numbers a reader asks first, as big figures; each tile links to where it came from.
export function insideStats(result, text, schedule) {
  const claim = f => (result.claims || []).find(c => c.field === f);
  const epc = f => (result.evidence || []).find(e => e.field === f && e.agent === 'epc');
  const advert = listingUrl(result);
  const m = advertMoney(text);
  const stats = [];
  const add = (big, label, url, title, wide = false) => { if (big !== undefined && big !== null && big !== '') stats.push({ big: String(big), label, url, title: title || label, wide }); };
  add(claim('floor_area')?.value ?? schedule?.stated_m2, 'm² advert', advert);
  add(schedule?.rooms_m2, 'm² rooms', advert, 'Sum of the advert room schedule');
  const reg = epc('floor_area');
  add(reg?.value, 'm² register', reg?.source_url, 'EPC register floor area');
  const price = claim('price');
  add(price && gbp(price.value), claim('sale_status')?.value || 'price', price?.source_url || advert);
  const amount = c => c?.match(/£\s?\d[\d,]*/)?.[0]?.replace(/\s/, '');
  add(amount(m.rent), 'rent pcm', advert, m.rent);
  add(amount(m.deposit), 'deposit', advert, m.deposit);
  const fee = m.fees[0];
  if (fee) add([fee.match(/\d+(?:\.\d+)?%/)?.[0], amount(fee)].filter(Boolean).join(' · ') || 'Yes', 'fees', advert, m.fees.join(' · '), true);
  const rating = epc('energy_rating') || claim('energy_rating');
  add(rating?.value, 'energy rating', rating?.source_url, rating?.agent === 'epc' ? 'EPC register' : 'Advert');
  add(claim('bedrooms')?.value, 'bedrooms', advert);
  add(text.match(/Council Tax\s*[-:]?\s*Band\s*([A-H])\b/i)?.[1]?.toUpperCase(), 'council tax band', advert);
  return stats;
}

// Isometric dollhouse: each room a box of walls, rotated by `angle` about the house centre and projected.
const WALL = 2.4, GAP = 3, ISO = Math.PI / 6;
const HUES = [{ re: /living|lounge|reception|sitting|dining/i, h: 34 }, { re: /kitchen|utility/i, h: 12 }, { re: /bath|shower|en-?suite|wc|cloak/i, h: 195 },
  { re: /bed/i, h: 92 }, { re: /dressing|study|office/i, h: 265 }];
const hue = name => (HUES.find(x => x.re.test(name)) || { h: 150 }).h;

// lift(level, room index) -> [wall height fraction, drop in metres]: the build-up intro; default is the finished house.
export function isoScene(floors, angle = 0, lift = () => [1, 0]) {
  const packs = floors.map(f => packRooms(f.rooms));
  const cos = Math.cos(angle), sin = Math.sin(angle);
  const proj = (x, y, z) => { const u = x * cos - y * sin, v = x * sin + y * cos; return { X: (u - v) * Math.cos(ISO), Y: (u + v) * Math.sin(ISO) - z, d: u + v }; };
  const levels = packs.map((pack, i) => {
    const z0 = i * (WALL + GAP), ox = pack.width / 2, oy = pack.height / 2;
    const faces = [], labels = [];
    for (const [k0, r] of pack.rooms.entries()) {
      const [rise, drop] = lift(i, k0), z = z0 + drop, top = WALL * rise;
      const c = [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]].map(([x, y]) => [x - ox, y - oy]);
      const h = hue(r.name);
      const floor = c.map(([x, y]) => proj(x, y, z));
      faces.push({ kind: 'floor', room: r, h, pts: floor, d: -Infinity });
      for (let k = 0; k < 4; k++) {
        const [a, b] = [c[k], c[(k + 1) % 4]];
        const pts = [proj(a[0], a[1], z), proj(b[0], b[1], z), proj(b[0], b[1], z + top), proj(a[0], a[1], z + top)];
        const nx = b[1] - a[1], ny = -(b[0] - a[0]); // outward normal for a clockwise-in-screen ring
        const facing = (nx * cos - ny * sin) + (nx * sin + ny * cos); // toward the viewer when > 0
        faces.push({ kind: facing > 0 ? 'near' : 'far', room: r, h, pts, d: (pts[0].d + pts[1].d) / 2 + (facing > 0 ? 0.01 : -0.01), light: (nx * cos - ny * sin) / Math.hypot(nx, ny) });
      }
      const mid = proj(r.x + r.w / 2 - ox, r.y + r.h / 2 - oy, z);
      labels.push({ room: r, X: mid.X, Y: mid.Y, d: mid.d, area: r.area_m2 || r.w * r.h });
    }
    const rank = f => (f.kind === 'far' ? 0 : f.kind === 'floor' ? 1 : 2);
    faces.sort((a, b) => rank(a) - rank(b) || a.d - b.d);
    labels.sort((a, b) => a.d - b.d);
    return { name: floors[i].name, z: z0, faces, labels };
  });
  return levels;
}

// Walls of one room as boxes, with a 0.9 m door gap in the middle of every side long enough for one.
// shortcut: doors are not taken from a real plan and walls do not block you; fine for a sense of size.
export function wallSegments(r, door = 0.9) {
  const out = [];
  for (const [x1, y1, x2, y2] of [[r.x, r.y, r.x + r.w, r.y], [r.x + r.w, r.y, r.x + r.w, r.y + r.h], [r.x, r.y + r.h, r.x + r.w, r.y + r.h], [r.x, r.y, r.x, r.y + r.h]]) {
    const len = Math.hypot(x2 - x1, y2 - y1), ux = (x2 - x1) / len, uy = (y2 - y1) / len;
    const cuts = len > door + 0.6 ? [[0, (len - door) / 2], [(len + door) / 2, len]] : [[0, len]];
    for (const [a, b] of cuts) out.push({ x: x1 + ux * (a + b) / 2, y: y1 + uy * (a + b) / 2, len: b - a, along: ux !== 0 });
  }
  return out;
}

async function walkThrough(host, floors) {
  const THREE = await import('./vendor/three.module.min.js');
  const width = host.clientWidth || 640, height = Math.round(width * 0.66);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.setSize(width, height);
  renderer.domElement.className = 'inside-walk';
  renderer.domElement.tabIndex = 0;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#0d100e');
  scene.add(new THREE.HemisphereLight('#e8f0ff', '#c8b999', 1.4));
  const sun = new THREE.DirectionalLight('#fff5e3', 1.6); sun.position.set(-5, 12, 8); scene.add(sun);
  const camera = new THREE.PerspectiveCamera(72, width / height, 0.05, 100);
  const STOREY = WALL + 0.3;
  let start = null;
  floors.forEach((floor, i) => {
    const pack = packRooms(floor.rooms), y0 = i * STOREY, ox = pack.width / 2, oy = pack.height / 2;
    for (const r of pack.rooms) {
      const color = new THREE.Color(`hsl(${hue(r.name)}, 40%, 62%)`);
      const slab = new THREE.Mesh(new THREE.BoxGeometry(r.w, 0.06, r.h), new THREE.MeshStandardMaterial({ color: color.clone().multiplyScalar(0.55) }));
      slab.position.set(r.x + r.w / 2 - ox, y0 - 0.03, r.y + r.h / 2 - oy); scene.add(slab);
      const wallMat = new THREE.MeshStandardMaterial({ color });
      for (const w of wallSegments(r)) {
        const box = new THREE.Mesh(new THREE.BoxGeometry(w.along ? w.len : 0.08, WALL, w.along ? 0.08 : w.len), wallMat);
        box.position.set(w.x - ox, y0 + WALL / 2, w.y - oy); scene.add(box);
      }
      if (i === 0 && (!start || r.w * r.h > start.a)) start = { a: r.w * r.h, x: r.x + r.w / 2 - ox, z: r.y + r.h / 2 - oy };
    }
  });
  // first-person look and move, as in the reference's navigation.js: drag to look, WASD or arrows to walk
  let yaw = 0, pitch = -0.05, level = 0, drag = false, lx = 0, ly = 0, last = 0, alive = true;
  const keys = new Set();
  camera.position.set(start.x, 1.6, start.z);
  const look = () => camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, 'YXZ'));
  look();
  const c = renderer.domElement;
  c.addEventListener('pointerdown', e => { drag = true; lx = e.clientX; ly = e.clientY; c.setPointerCapture(e.pointerId); c.focus(); });
  c.addEventListener('pointerup', () => { drag = false; });
  c.addEventListener('pointermove', e => { if (!drag) return; yaw -= (e.clientX - lx) * 0.005; pitch = Math.max(-1.1, Math.min(1.1, pitch - (e.clientY - ly) * 0.005)); lx = e.clientX; ly = e.clientY; look(); });
  const MOVE = ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
  c.addEventListener('keydown', e => { if (MOVE.includes(e.code)) { keys.add(e.code); e.preventDefault(); } });
  c.addEventListener('keyup', e => keys.delete(e.code));
  c.addEventListener('blur', () => keys.clear());
  const tick = now => {
    if (!alive || !c.isConnected && last) { renderer.dispose(); return; }
    const dt = last ? Math.min((now - last) / 1000, 0.05) : 0; last = now;
    const f = (keys.has('KeyW') || keys.has('ArrowUp')) - (keys.has('KeyS') || keys.has('ArrowDown'));
    const side = (keys.has('KeyD')) - (keys.has('KeyA'));
    yaw -= ((keys.has('ArrowRight')) - (keys.has('ArrowLeft'))) * 1.6 * dt; look();
    camera.position.x += (-Math.sin(yaw) * f + Math.cos(yaw) * side) * 2.2 * dt;
    camera.position.z += (-Math.cos(yaw) * f - Math.sin(yaw) * side) * 2.2 * dt;
    camera.position.y += (level * STOREY + 1.6 - camera.position.y) * Math.min(1, dt * 6);
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  const bar = el('div', null, 'inside-walk-bar');
  if (floors.length > 1) {
    const up = el('button', 'Go upstairs'); up.type = 'button';
    up.addEventListener('click', () => { level = (level + 1) % floors.length; up.textContent = level ? 'Go downstairs' : 'Go upstairs'; c.focus(); });
    bar.append(up);
  }
  bar.append(el('span', 'Drag to look · WASD or arrows to walk'));
  host.replaceChildren(c, bar);
  c.focus();
  return () => { alive = false; host.replaceChildren(); };
}

const S = 46; // pixels per metre in the 3D view

function draw3d(floors) {
  const r = Math.max(...floors.map(f => { const p = packRooms(f.rooms); return Math.hypot(p.width, p.height) / 2; }));
  const half = r * Math.SQRT2, top = (floors.length - 1) * (WALL + GAP) + WALL;
  const vb = [-half * Math.cos(ISO) * S - 20, (-half * Math.sin(ISO) - top) * S - 20, 2 * half * Math.cos(ISO) * S + 40, (2 * half * Math.sin(ISO) + top) * S + 40];
  const svg = svgEl('svg', { viewBox: vb.join(' '), role: 'img', class: 'inside-iso' });
  const total = floors.reduce((s, f) => s + f.rooms.length, 0);
  svg.append(svgEl('title', {}, `Isometric reconstruction: ${floors.map(f => f.name).join(' and ')}, ${total} rooms`));
  const scene = svgEl('g', {});
  svg.append(scene);
  const pt = p => `${(p.X * S).toFixed(1)},${(p.Y * S).toFixed(1)}`;
  const render = (angle, at = Infinity) => {
    const intro = introAt(floors, at);
    scene.replaceChildren();
    const tags = [];
    for (const [i, level] of isoScene(floors, angle, intro.lift).entries()) {
      if (intro.lift(i, 0)[1] >= 40) continue; // an upper floor still waiting to drop in
      const g = svgEl('g', { class: 'iso-level' });
      const glow = intro.glow > 0 ? `;stroke:var(--color-accent);stroke-opacity:${intro.glow.toFixed(2)};stroke-width:1.5` : '';
      for (const f of level.faces) {
        const light = f.kind === 'floor' ? 30 : 42 + 14 * (f.light || 0);
        g.append(svgEl('polygon', { points: f.pts.map(pt).join(' '), class: `iso-${f.kind}`, style: `--h:${f.h};--l:${light.toFixed(0)}%${glow}` }));
      }
      for (const l of level.labels) {
        const t = svgEl('g', { class: 'iso-label', transform: `translate(${(l.X * S).toFixed(1)} ${(l.Y * S).toFixed(1)}) scale(${intro.label.toFixed(3)})`, style: `opacity:${Math.min(1, intro.label).toFixed(2)}` });
        t.append(svgEl('text', { y: -5, class: 'iso-name' }, l.room.name), svgEl('text', { y: 15, class: 'iso-area' }, `${l.area.toFixed(1)} m²`));
        t.append(svgEl('title', {}, `${l.room.name}: ${l.room.width_m} × ${l.room.length_m} m`));
        g.append(t);
      }
      const tag = proj0(level.z + WALL, half);
      tags.push(svgEl('text', { x: vb[0] + 24, y: (tag * S).toFixed(1), class: 'iso-tag' }, level.name));
      scene.append(g);
    }
    scene.append(...tags); // on top, so the upper floor never hides the ground floor's name
  };
  const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const animate = !still && typeof requestAnimationFrame === 'function';
  render(0, animate ? 0 : Infinity); // reduced motion: the finished house at once
  if (animate) {
    let angle = 0, last = 0, start = 0, paused = false;
    const end = introAt(floors, 0).duration;
    svg.addEventListener('pointerenter', () => { paused = true; });
    svg.addEventListener('pointerleave', () => { paused = false; });
    const tick = now => {
      if (!svg.isConnected && last) return; // the view was replaced
      if (!start) start = now;
      const at = now - start;
      if (at <= end + 32) render(0, at); // build-up first, ending on the finished frame
      else if (last && !paused && !document.hidden) { angle += (now - last) * 0.00012; render(angle); }
      last = now; requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  return svg;
}
const ease = t => 1 - (1 - Math.min(1, Math.max(0, t))) ** 3;
const pop = t => { const x = Math.min(1, Math.max(0, t)); return x >= 1 ? 1 : 1 + 0.25 * Math.sin(x * Math.PI) - 0.25 * (1 - x) - (1 - x) * 0.75; };

/** The build-up intro at `at` ms: flat plan, ground-floor walls rise room by room, upper floors drop in, labels pop. */
export function introAt(floors, at) {
  const FLAT = 250, RISE = 520, STAGGER = Math.min(110, 900 / Math.max(1, floors[0]?.rooms.length || 1)), DROP = 520, LABELS = 380;
  const groundDone = FLAT + STAGGER * Math.max(0, (floors[0]?.rooms.length || 1) - 1) + RISE;
  const dropDone = floors.length > 1 ? groundDone + DROP * (floors.length - 1) : groundDone;
  const duration = dropDone + LABELS;
  const lift = (level, k) => {
    if (level === 0) return [ease((at - FLAT - k * STAGGER) / RISE), 0];
    const t = ease((at - groundDone - (level - 1) * DROP) / DROP);
    return [1, t <= 0 ? 40 : (1 - t) * 3.5]; // waits far above the frame, then drops into place
  };
  const glow = at >= duration ? 0 : at < groundDone ? 1 : 1 - (at - groundDone) / (duration - groundDone);
  return { lift, glow, label: pop((at - dropDone) / LABELS), duration };
}

// Screen y of a level's label: just above the back corner of its walls.
const proj0 = (z, half) => -half * Math.sin(ISO) * 0.55 - z;

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
    const stage = el('div', null, 'inside-stage');
    const iso = draw3d(floors);
    const plans = el('div', null, `inside-plans inside-floors-${floors.length}`);
    for (const floor of floors) plans.append(drawFloor(floor));
    plans.hidden = true;
    const walkHost = el('div', null, 'inside-walk-host');
    let stopWalk = null;
    const toggle = el('div', null, 'inside-toggle');
    toggle.setAttribute('role', 'group'); toggle.setAttribute('aria-label', 'View');
    for (const [label, show] of [['3D', iso], ['Plan', plans], ['Walk through', walkHost]]) {
      const b = el('button', label); b.type = 'button'; b.setAttribute('aria-pressed', String(show === iso));
      b.addEventListener('click', async () => {
        iso.style.display = show === iso ? '' : 'none'; plans.hidden = show !== plans;
        for (const x of toggle.children) x.setAttribute('aria-pressed', String(x === b));
        stopWalk?.(); stopWalk = null;
        if (show === walkHost) stopWalk = await walkThrough(walkHost, floors).catch(err => { console.error(err); walkHost.replaceChildren(el('p', 'Walk-through needs WebGL, which this browser has turned off.', 'inside-empty')); return null; });
      });
      toggle.append(b);
    }
    stage.append(toggle, iso, plans, walkHost);
    const credit = el('figcaption', 'Approximate, to scale from the advert’s room sizes. Walkthrough based on ', 'inside-note');
    const ref = el('a', 'sesasa/3d-house-walkthrough'); ref.href = 'https://github.com/sesasa/3d-house-walkthrough'; ref.target = '_blank'; ref.rel = 'noopener noreferrer';
    credit.append(ref, ' (MIT).');
    planCol.append(stage, credit);
  } else {
    planCol.append(el('p', 'No room dimensions were recorded for this listing. Its description and sourced facts remain available below.', 'inside-empty'));
  }
  const facts = el('div', null, 'inside-stats');
  for (const s of insideStats(result, text, schedule)) {
    const href = safeUrl(s.url);
    const tile = el(href ? 'a' : 'div', null, s.wide ? 'inside-stat inside-stat-wide' : 'inside-stat');
    if (href) { tile.href = href; tile.target = '_blank'; tile.rel = 'noopener noreferrer'; }
    tile.title = s.title;
    tile.append(el('strong', s.big), el('span', s.label));
    facts.append(tile);
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
  if (photos.length) planCol.append(strip);
  container.replaceChildren(wrap);
}
