// X-ray opener: a 3D fly-in from London-wide down to the listing.
// Contract: flyIn(el, {lat, lng, label, precision, use, durationMs}) resolves on landing and never rejects.
const MAPLIBRE = 'https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1';
const TILES = 'https://tiles.openfreemap.org/planet';
const GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';
const CESIUM = 'https://cdnjs.cloudflare.com/ajax/libs/cesium/1.140.0';
const CEILING_MS = 8500; // absolute: the caller has control back by then on the 3D tiles path
const LONDON = [-0.1276, 51.5072];
const C = { bg: '#080a09', water: '#0f1a17', park: '#0d140f', road: '#232a24', major: '#323b33', bldLo: '#151a16', bldHi: '#2c342d', accent: '#b8ed81', muted: '#b4beb2' };

const here = new URL('.', import.meta.url).href;
const live = new WeakMap();

function css(href) {
  if ([...document.styleSheets].some((s) => s.href === href) || document.querySelector(`link[href="${href}"]`)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = href;
  document.head.append(l);
}

function script(src, timeoutMs, name = 'maplibregl') {
  if (window[name]) return Promise.resolve(window[name]);
  return new Promise((ok, no) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => (window[name] ? ok(window[name]) : no(new Error(`${name} missing`)));
    s.onerror = () => no(new Error(`${name} failed to load`));
    setTimeout(() => no(new Error(`${name} timeout`)), timeoutMs);
    document.head.append(s);
  });
}

function hasWebGL() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch { return false; }
}

const fmt = (lat, lng) => `${Math.abs(lat).toFixed(5)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lng).toFixed(5)}° ${lng >= 0 ? 'E' : 'W'}`;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function circle(lng, lat, metres, n = 96) {
  const dLat = metres / 111320, dLng = metres / (111320 * Math.cos((lat * Math.PI) / 180));
  const ring = Array.from({ length: n + 1 }, (_, i) => {
    const a = (i / n) * 2 * Math.PI;
    return [lng + dLng * Math.cos(a), lat + dLat * Math.sin(a)];
  });
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } };
}

function style() {
  return {
    version: 8,
    glyphs: GLYPHS,
    sources: { omt: { type: 'vector', url: window.XRAY_CONFIG?.flyinTiles || TILES } },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': C.bg } },
      { id: 'park', type: 'fill', source: 'omt', 'source-layer': 'landuse', filter: ['in', 'class', 'park', 'cemetery', 'grass'], paint: { 'fill-color': C.park } },
      { id: 'wood', type: 'fill', source: 'omt', 'source-layer': 'landcover', filter: ['in', 'class', 'wood', 'grass'], paint: { 'fill-color': C.park } },
      { id: 'water', type: 'fill', source: 'omt', 'source-layer': 'water', paint: { 'fill-color': C.water } },
      { id: 'water-edge', type: 'line', source: 'omt', 'source-layer': 'water', paint: { 'line-color': '#1f3a2c', 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.4, 16, 1.5] } },
      { id: 'road-minor', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 12, filter: ['in', 'class', 'minor', 'service', 'track'], paint: { 'line-color': C.road, 'line-width': ['interpolate', ['exponential', 1.6], ['zoom'], 12, 0.4, 18, 10] } },
      { id: 'road-major', type: 'line', source: 'omt', 'source-layer': 'transportation', filter: ['in', 'class', 'primary', 'secondary', 'tertiary', 'trunk', 'motorway'], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': C.major, 'line-width': ['interpolate', ['exponential', 1.6], ['zoom'], 8, 0.4, 18, 18] } },
      { id: 'rail', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 11, filter: ['in', 'class', 'rail', 'transit'], paint: { 'line-color': '#2a332b', 'line-width': 1, 'line-dasharray': [3, 2] } },
      { id: 'area-fill', type: 'fill', source: 'target', filter: ['==', 'kind', 'area'], paint: { 'fill-color': C.accent, 'fill-opacity': 0, 'fill-opacity-transition': { duration: 900 } } },
      { id: 'area-glow', type: 'line', source: 'target', filter: ['==', 'kind', 'area'], paint: { 'line-color': C.accent, 'line-width': 10, 'line-blur': 10, 'line-opacity': 0, 'line-opacity-transition': { duration: 900 } } },
      { id: 'area-line', type: 'line', source: 'target', filter: ['==', 'kind', 'area'], paint: { 'line-color': C.accent, 'line-width': 1.5, 'line-opacity': 0, 'line-opacity-transition': { duration: 900 } } },
      {
        id: 'buildings', type: 'fill-extrusion', source: 'omt', 'source-layer': 'building', minzoom: 12.5,
        paint: {
          'fill-extrusion-color': ['interpolate', ['linear'], ['coalesce', ['get', 'render_height'], 8], 0, C.bldLo, 60, '#202721', 160, C.bldHi],
          'fill-extrusion-height': ['interpolate', ['linear'], ['zoom'], 12.5, 0, 14, ['coalesce', ['get', 'render_height'], 8]],
          'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
          'fill-extrusion-opacity': 0.92,
          'fill-extrusion-vertical-gradient': true,
        },
      },
      { id: 'lit', type: 'fill-extrusion', source: 'lit', paint: { 'fill-extrusion-color': C.accent, 'fill-extrusion-height': ['+', ['coalesce', ['get', 'render_height'], 8], 0.6], 'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0], 'fill-extrusion-opacity': 0, 'fill-extrusion-opacity-transition': { duration: 900 } } },
      { id: 'place', type: 'symbol', source: 'omt', 'source-layer': 'place', filter: ['in', 'class', 'city', 'suburb', 'neighbourhood', 'quarter'], layout: { 'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']], 'text-font': ['Noto Sans Regular'], 'text-size': ['interpolate', ['linear'], ['zoom'], 9, 11, 15, 13], 'text-transform': 'uppercase', 'text-letter-spacing': 0.18, 'text-max-width': 8 }, paint: { 'text-color': '#7f8a7e', 'text-halo-color': C.bg, 'text-halo-width': 1.2 } },
      { id: 'water-name', type: 'symbol', source: 'omt', 'source-layer': 'water_name', layout: { 'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']], 'text-font': ['Noto Sans Italic'], 'text-size': 12, 'symbol-placement': 'line', 'text-letter-spacing': 0.2 }, paint: { 'text-color': '#4f6b5c' } },
    ],
  };
}

function hud(el, o) {
  const area = o.precision === 'postcode_centroid';
  const wrap = document.createElement('div');
  wrap.className = 'xf-overlay';
  wrap.innerHTML = `
    <div class="xf-vignette"></div>
    <div class="xf-scan"></div>
    <div class="xf-progress"><span></span></div>
    <div class="xf-status"><i></i><span>Locating</span></div>
    <div class="xf-hud">
      <div class="xf-kicker">${area ? 'Postcode area' : 'Address'}${o.use === 'office' ? ' · Office' : ''}</div>
      <div class="xf-label">${esc(o.label)}</div>
      <div class="xf-coords">${fmt(o.lat, o.lng)}${area ? ' · postcode area centre' : ''}</div>
    </div>`;
  el.append(wrap);
  wrap.querySelector('.xf-progress span').style.transitionDuration = `${o.durationMs}ms`;
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('xf-flying')));
  return {
    land() {
      el.classList.add('xf-landed');
      wrap.querySelector('.xf-status span').textContent = area ? 'Postcode area located' : 'Located';
    },
  };
}

function fallback(el, o, reason) {
  const area = o.precision === 'postcode_centroid';
  el.querySelectorAll('.xf-map, .xf-overlay').forEach((n) => n.remove());
  el.classList.remove('xf-flying');
  el.classList.add('xf-landed');
  const card = document.createElement('div');
  card.className = 'xf-fallback';
  card.dataset.reason = reason;
  card.innerHTML = `
    <div class="xf-fb-grid"></div>
    <div class="xf-fb-mark ${area ? 'is-area' : 'is-pin'}" aria-hidden="true">
      ${area ? '<span></span><span></span>' : '<svg viewBox="0 0 24 32" width="40" height="54"><path d="M12 31s10-11.2 10-19A10 10 0 0 0 2 12c0 7.8 10 19 10 19z" fill="#b8ed81"/><circle cx="12" cy="12" r="4" fill="#080a09"/></svg>'}
    </div>
    <div class="xf-fb-text">
      <div class="xf-kicker">${area ? 'Postcode area' : 'Address'}</div>
      <div class="xf-label">${esc(o.label)}</div>
      <div class="xf-coords">${fmt(o.lat, o.lng)}</div>
      <div class="xf-note">Map preview unavailable. Location shown from coordinates.</div>
    </div>`;
  el.append(card);
}

const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));

function metresBetween([lng1, lat1], [lng2, lat2]) {
  return Math.hypot((lng2 - lng1) * Math.cos((lat1 * Math.PI) / 180), lat2 - lat1) * 111320;
}

function centroid(geom) {
  const ring = geom.coordinates[0];
  const s = ring.reduce((a, p) => [a[0] + p[0], a[1] + p[1]], [0, 0]);
  return [s[0] / ring.length, s[1] / ring.length];
}

function contains(ring, [x, y]) {
  let c = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

// Light the target lime: every building in the postcode ring, or the one nearest the address.
// OpenFreeMap merges same-height buildings into one MultiPolygon per tile, so split before measuring.
function light(map, area, target) {
  const near = map.querySourceFeatures('omt', { sourceLayer: 'building' })
    .flatMap((f) => (f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates).map((rings) => ({ type: 'Feature', properties: f.properties, geometry: { type: 'Polygon', coordinates: rings } })))
    .map((f) => [metresBetween(target, centroid(f.geometry)), f])
    .filter(([d]) => d < (area ? 150 : 40))
    .sort((a, b) => a[0] - b[0]);
  const inside = near.filter(([, f]) => contains(f.geometry.coordinates[0], target));
  const hits = (area ? near : inside.length ? inside : near.slice(0, 1)).map(([, f]) => f);
  map.getSource('lit').setData({ type: 'FeatureCollection', features: hits });
  map.setPaintProperty('lit', 'fill-extrusion-opacity', area ? 0.6 : 0.95);
}

async function runMapLibre(el, o, state) {
  const ml = await script(`${MAPLIBRE}/maplibre-gl.js`, 8000);
  if (state.done) return;
  const area = o.precision === 'postcode_centroid';
  const target = [o.lng, o.lat];
  const mapEl = document.createElement('div');
  mapEl.className = 'xf-map';
  el.prepend(mapEl);
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const final = { center: target, zoom: area ? 15.6 : 16.9, pitch: area ? 58 : 64, bearing: 28 };
  const s = style();
  s.sources.lit = { type: 'geojson', data: { type: 'FeatureCollection', features: [] } };
  s.sources.target = { type: 'geojson', data: { type: 'FeatureCollection', features: area ? [{ ...circle(o.lng, o.lat, 170), properties: { kind: 'area' } }] : [] } };
  const map = new ml.Map({
    container: mapEl, style: s, interactive: false, attributionControl: false, fadeDuration: 0,
    ...(reduce ? final : { center: LONDON, zoom: 9.6, pitch: 0, bearing: -12 }),
    maxPitch: 75, canvasContextAttributes: { antialias: true }, antialias: true,
  });
  map.addControl(new ml.AttributionControl({ compact: false }), 'bottom-right');
  state.map = map;

  await new Promise((ok, no) => {
    map.once('load', ok);
    map.on('error', (e) => { if (!map.loaded()) no(e.error || new Error('map error')); });
    setTimeout(() => no(new Error('map load timeout')), 9000);
  });
  if (state.done) return;
  if (!map.getSource('omt')?.loaded?.() && !map.isSourceLoaded('omt')) await new Promise((ok) => { map.once('idle', ok); setTimeout(ok, 2500); });

  const marker = area ? null : new ml.Marker({ element: Object.assign(document.createElement('div'), { className: 'xf-pin', innerHTML: '<i></i><b></b>' }), anchor: 'bottom' }).setLngLat(target).addTo(map);

  if (!reduce) {
    const t = o.durationMs;
    map.flyTo({ center: [(LONDON[0] + o.lng) / 2 + 0.01, (LONDON[1] + o.lat) / 2], zoom: 12.4, pitch: 42, bearing: -24, duration: t * 0.42, curve: 1.2, essential: true });
    await wait(t * 0.42 + 50);
    if (state.done) return;
    map.easeTo({ ...final, duration: t * 0.58, easing: (x) => 1 - Math.pow(1 - x, 3), essential: true });
    await wait(t * 0.58 + 50);
  } else {
    await new Promise((ok) => { map.once('idle', ok); setTimeout(ok, 3000); });
  }
  if (state.done) return;

  light(map, area, target);
  ['area-fill', 'area-glow', 'area-line'].forEach((id, i) => map.setPaintProperty(id, id === 'area-fill' ? 'fill-opacity' : 'line-opacity', [0.1, 0.55, 0.9][i]));
  marker?.getElement().classList.add('is-landed');
  if (!reduce) map.easeTo({ bearing: final.bearing + 14, duration: 20000, easing: (x) => x, essential: true });
}

// Google Photorealistic 3D Tiles: a browser Maps key is public by design, served by /api/config.
async function mapsKey() {
  if (window.XRAY_CONFIG && 'mapsKey' in window.XRAY_CONFIG) return window.XRAY_CONFIG.mapsKey;
  try {
    const r = await fetch('/api/config', { signal: AbortSignal.timeout(1500) });
    return r.ok ? (await r.json()).maps_key || null : null;
  } catch { return null; }
}

const within = (p, ms, msg) => Promise.race([p, wait(Math.max(ms, 0)).then(() => { throw new Error(msg); })]);
const lerp = (a, b, u) => a + (b - a) * u;
const rad = (d) => (d * Math.PI) / 180;
const inOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

// Orbit-and-descend: London from 28 km straight down, spiralling onto an oblique orbit of the target.
async function runTiles(el, o, state, key, deadline) {
  window.CESIUM_BASE_URL = `${CESIUM}/`;
  css(`${CESIUM}/Widgets/widgets.css`);
  const Cesium = await script(`${CESIUM}/Cesium.js`, Math.min(5000, deadline - performance.now() - 3500), 'Cesium');
  if (state.done) return;
  const area = o.precision === 'postcode_centroid';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const mapEl = document.createElement('div');
  mapEl.className = 'xf-map xf-tiles';
  el.prepend(mapEl);
  const widget = new Cesium.CesiumWidget(mapEl, { baseLayer: false, globe: false, skyBox: false, showRenderLoopErrors: false, msaaSamples: 4 });
  state.map = { remove: () => widget.isDestroyed() || widget.destroy(), loaded: () => true };
  const scene = widget.scene;
  scene.backgroundColor = Cesium.Color.fromCssColorString(C.bg);
  scene.screenSpaceCameraController.enableInputs = false;
  let broke;
  const failed = new Promise((_, no) => { broke = no; });
  scene.renderError.addEventListener((_, e) => broke(e || new Error('render error')));
  // Google's own endpoint with Google's logo credit; no ion asset, no globe, no base imagery.
  const tileset = await within(Cesium.createGooglePhotorealistic3DTileset({ key, onlyUsingWithGoogleGeocoder: true }, { showCreditsOnScreen: true, maximumScreenSpaceError: 16 }), Math.min(3000, deadline - performance.now() - 5500), 'tiles timeout');
  if (state.done) return;
  scene.primitives.add(tileset);

  // shortcut: London ground is ~50 m above the ellipsoid; replaced by the sampled roof once tiles load.
  let H = 60, roof = Cesium.Cartesian3.fromDegrees(o.lng, o.lat, H + 20);
  const R = area ? 950 : 300, PITCH = area ? -52 : -42, SPIN = 3, PRELOAD = 2000; // SPIN: degrees per second of orbit
  const D = reduce ? 0 : Math.min(o.durationMs, deadline - performance.now() - PRELOAD - 300);
  if (!reduce && D < 3000) throw new Error('tiles too slow');
  let t0 = null; // null while preloading: the camera holds the landing pose so its tiles stream first, unseen
  const pose = () => {
    const sec = t0 === null ? D / 1000 : (performance.now() - t0) / 1000, u = D ? Math.min(sec * 1000 / D, 1) : 1, e = inOut(u), c = 1 - Math.pow(1 - u, 3);
    const center = Cesium.Cartesian3.fromDegrees(lerp(LONDON[0], o.lng, c), lerp(LONDON[1], o.lat, c), H);
    const heading = -40 + 40 * e + (reduce ? 0 : SPIN * sec);
    widget.camera.lookAt(center, new Cesium.HeadingPitchRange(rad(heading), rad(lerp(-89, PITCH, e)), Math.exp(lerp(Math.log(28000), Math.log(R), e))));
  };
  mapEl.style.opacity = '0';
  scene.preRender.addEventListener(pose);
  await Promise.race([new Promise((ok) => tileset.allTilesLoaded.addEventListener(ok)), wait(PRELOAD), failed]);
  if (state.done) return;
  // A judge never sees a grey blur: if the landing view is not sharp in time, MapLibre takes over.
  if (!tileset.tilesLoaded) throw new Error('tiles not sharp in time');
  const top = scene.sampleHeightSupported ? scene.sampleHeight(Cesium.Cartographic.fromDegrees(o.lng, o.lat)) : undefined;
  if (top > 0 && top < 400) { H = top - 10; roof = Cesium.Cartesian3.fromDegrees(o.lng, o.lat, top + 2); }

  const pin = area ? null : Object.assign(document.createElement('div'), { className: 'xf-pin', innerHTML: '<i></i><b></b>' });
  if (pin) mapEl.append(pin);
  if (pin) scene.postRender.addEventListener(() => {
    const p = Cesium.SceneTransforms.worldToWindowCoordinates(scene, roof);
    if (p) pin.style.transform = `translate(${p.x - 8}px, ${p.y - 56}px)`;
  });
  t0 = performance.now();
  mapEl.style.transition = 'opacity 400ms';
  mapEl.style.opacity = '1';
  await Promise.race([wait(D), failed]);
  if (reduce) scene.preRender.removeEventListener(pose);
  pin?.classList.add('is-landed');
}

export function flyIn(el, opts = {}) {
  const o = { label: '', precision: 'address', use: 'residential', durationMs: 7000, ...opts };
  o.durationMs = Math.min(Math.max(+o.durationMs || 7000, 1500), 9000);
  return new Promise((resolve) => {
    const state = { done: false, map: null };
    let ui;
    const finish = (reason) => {
      if (state.done) return;
      state.done = true;
      clearTimeout(guard);
      if (reason) {
        try { state.map?.remove(); } catch {}
        state.map = null;
        try { fallback(el, o, reason); } catch {}
      } else {
        ui?.land();
      }
      live.set(el, state);
      resolve();
    };
    // Hard ceiling: whatever happens, the caller gets control back.
    const guard = setTimeout(() => finish(state.map?.loaded() ? null : 'timeout'), o.durationMs + 9000);
    try {
      dispose(el);
      el.classList.add('xf-root');
      css(`${here}flyin.css`);
      if (!Number.isFinite(+o.lat) || !Number.isFinite(+o.lng)) return finish('no-coordinates');
      o.lat = +o.lat; o.lng = +o.lng;
      if (!hasWebGL()) return finish('no-webgl');
      css(`${MAPLIBRE}/maplibre-gl.css`);
      const deadline = performance.now() + CEILING_MS;
      live.set(el, state);
      const run = async () => {
        const key = await mapsKey();
        if (key && !state.done) {
          const full = o.durationMs;
          o.durationMs = Math.min(o.durationMs, CEILING_MS - 1500);
          ui = hud(el, o);
          try {
            await runTiles(el, o, state, key, deadline);
            el.dataset.flyin = 'tiles';
            return;
          } catch (e) {
            // Any 3D tiles failure (403, no WebGL2, slow CDN, render error) drops to MapLibre in the time left.
            el.dataset.flyinTilesError = String(e?.message || e);
            try { state.map?.remove(); } catch {}
            state.map = null;
            el.querySelectorAll('.xf-map, .xf-overlay').forEach((n) => n.remove());
            el.classList.remove('xf-flying');
            o.durationMs = Math.min(full, Math.max(1500, deadline - performance.now() - 2500));
          }
        }
        if (state.done) return;
        ui = hud(el, o);
        await runMapLibre(el, o, state);
        el.dataset.flyin = 'maplibre';
      };
      run().then(() => finish(null), (e) => finish(String(e?.message || e || 'map error')));
    } catch (e) {
      finish(String(e?.message || e));
    }
  });
}

function dispose(el) {
  const s = live.get(el);
  if (s) { s.done = true; try { s.map?.remove(); } catch {} }
  live.delete(el);
  el.querySelectorAll('.xf-map, .xf-overlay, .xf-fallback').forEach((n) => n.remove());
  el.classList.remove('xf-root', 'xf-flying', 'xf-landed');
  delete el.dataset.flyin; delete el.dataset.flyinTilesError;
}

export function disposeFlyIn(el) {
  if (el) dispose(el);
}
