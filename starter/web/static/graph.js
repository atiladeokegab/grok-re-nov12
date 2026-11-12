import { fieldName, safeUrl, timestamp, valueText, VERDICTS } from './data.js';

const vendorUrl = '/static/vendor/graph-3d-force-graph-1.77.0.min.js';
let vendorPromise;

const safeText = value => value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const asId = value => value == null ? '' : String(value);
const category = kind => kind === 'place' || kind === 'claim' || kind === 'finding' ? kind : 'source';
const relationName = kind => ({ has: 'has claim', checked_by: 'checked against', cites: 'cites source' })[kind] || String(kind || 'connected').replaceAll('_', ' ');

export function nodeTitle(node) {
  const data = node?.data || {};
  if (node?.kind === 'place') return data.title || data.address || node.id;
  if (node?.kind === 'document') return data.title || data.name || data.file_name || data.filename || node.id;
  if (node?.kind === 'finding') return `${fieldName(data.field)}: ${VERDICTS[data.verdict] || 'Status not recorded'}`;
  const value = data.value == null ? '' : valueText(data.value, data.unit);
  return data.field ? `${fieldName(data.field)}${value ? `: ${value}` : ''}` : node?.id || 'Record';
}

export function graphSlice(graphData, filter = 'all') {
  const nodes = Array.isArray(graphData?.nodes) ? graphData.nodes.filter(node => node && node.id != null).map(node => ({ ...node, id: asId(node.id), data: node.data && typeof node.data === 'object' ? node.data : {} })) : [];
  const edges = Array.isArray(graphData?.edges) ? graphData.edges.filter(edge => edge && edge.from != null && edge.to != null).map(edge => ({ ...edge, from: asId(edge.from), to: asId(edge.to) })) : [];
  const ids = new Set(nodes.map(node => node.id));
  const validEdges = edges.filter(edge => ids.has(edge.from) && ids.has(edge.to));
  if (filter === 'all') return { nodes, edges: validEdges };
  const seeds = new Set(nodes.filter(node => category(node.kind) === filter).map(node => node.id));
  const visible = new Set(seeds);
  for (const edge of validEdges) {
    if (seeds.has(edge.from) || seeds.has(edge.to)) { visible.add(edge.from); visible.add(edge.to); }
  }
  return { nodes: nodes.filter(node => visible.has(node.id)), edges: validEdges.filter(edge => visible.has(edge.from) && visible.has(edge.to)) };
}

function appendText(parent, tag, text, className) {
  const item = document.createElement(tag);
  item.textContent = safeText(text);
  if (className) item.className = className;
  parent.append(item);
  return item;
}

function loadVendor() {
  if (window.ForceGraph3D) return Promise.resolve(window.ForceGraph3D);
  if (!vendorPromise) vendorPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = vendorUrl;
    script.onload = () => window.ForceGraph3D ? resolve(window.ForceGraph3D) : reject(new Error('Graph library did not initialize'));
    script.onerror = () => { vendorPromise = null; reject(new Error('Graph library could not load')); };
    document.head.append(script);
  });
  return vendorPromise;
}

function webglAvailable() {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    return Boolean(gl);
  } catch { return false; }
}

function escapeHtml(value) {
  return safeText(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function renderNodeDetail(detail, node, onSelect, notify = false) {
  detail.replaceChildren();
  if (!node) {
    appendText(detail, 'p', 'Select a point to read its claim, source and retrieval context.', 'eg-empty');
    return;
  }
  const data = node.data || {};
  appendText(detail, 'h3', nodeTitle(node), 'eg-detail-title');
  appendText(detail, 'p', `Record type: ${node.kind || 'record'}.`, 'eg-kind');
  const fields = Object.entries(data).filter(([, value]) => value != null && value !== '' && typeof value !== 'function');
  const urlField = fields.find(([key, value]) => /^(source_url|document_url|url|uri)$/i.test(key) && safeUrl(value));
  const grid = document.createElement('dl');
  grid.className = 'eg-fields';
  for (const [key, value] of fields) {
    if (urlField?.[0] === key) continue;
    appendText(grid, 'dt', key.replaceAll('_', ' '));
    appendText(grid, 'dd', value);
  }
  if (grid.childElementCount) detail.append(grid);
  const fetchedAt = data.retrieved_at || data.fetched_at || data.captured_at || data.created_at;
  if (fetchedAt || data.agent) {
    const provenance = fetchedAt ? `Retrieved ${timestamp(fetchedAt)}${data.agent ? ` by ${data.agent}` : ''}.` : `Retrieved by ${data.agent}.`;
    appendText(detail, 'p', provenance, 'eg-provenance');
  }
  if (urlField) {
    const href = safeUrl(urlField[1]);
    const link = appendText(detail, 'a', `Open source record at ${new URL(href).hostname}`, 'eg-source-link');
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
  } else if (node.kind === 'evidence' || node.kind === 'document') {
    appendText(detail, 'p', 'This record has no source link.', 'eg-provenance');
  }
  if (notify && ['finding', 'evidence', 'document'].includes(node.kind)) onSelect?.({ kind: node.kind, id: node.id, data });
}

export function graphColor(node) {
  if (node.kind === 'place') return '#b8ed81';
  if (node.kind === 'finding') {
    return ({ matches: '#b8ed81', disagrees: '#ffb4a8', unverifiable: '#efd18b', flag: '#efd18b' })[node.data?.verdict] || '#f2f5ee';
  }
  return '#f2f5ee';
}

export function mountGraph(container, graphData, { onSelect } = {}) {
  if (!container) throw new TypeError('mountGraph requires a container');
  const externalDetail = container.parentElement?.querySelector('#graph-detail') || document.getElementById('graph-detail');
  const shell = document.createElement('section');
  shell.className = 'eg-graph';
  shell.setAttribute('aria-label', 'Evidence graph');
  shell.setAttribute('aria-live', 'off');
  shell.innerHTML = `
    <header class="eg-header"><div><h2>Evidence graph</h2><p>Follow each claim to its finding and source record.</p></div><span class="eg-run"></span></header>
    <div class="eg-controls" role="group" aria-label="Filter graph records">
      <button type="button" data-filter="all" aria-pressed="true">All records</button>
      <button type="button" data-filter="claim" aria-pressed="false">Claims</button>
      <button type="button" data-filter="source" aria-pressed="false">Sources</button>
      <button type="button" data-filter="finding" aria-pressed="false">Findings</button>
    </div>
    <div class="eg-layout">
      <div class="eg-scene-wrap"><div class="eg-scene" aria-hidden="true"></div><div class="eg-scene-message" role="status" hidden></div>
        <div class="eg-camera" role="group" aria-label="Graph view controls">
          <button type="button" data-camera="in" aria-label="Zoom in">+</button><button type="button" data-camera="out" aria-label="Zoom out">−</button><button type="button" data-camera="fit">Fit graph</button>
        </div>
      </div>
      <div class="eg-records"><section class="eg-node-list" aria-label="Graph records"></section><section class="eg-edge-list" aria-label="Record connections"></section></div>
    </div>`;
  container.replaceChildren(shell);
  const detail = externalDetail || appendText(shell, 'aside', '', 'eg-detail');
  if (externalDetail) externalDetail.classList.add('eg-detail');
  detail.setAttribute('aria-live', 'polite');
  detail.setAttribute('aria-label', 'Selected record details');
  const scene = shell.querySelector('.eg-scene');
  const message = shell.querySelector('.eg-scene-message');
  const nodeList = shell.querySelector('.eg-node-list');
  const edgeList = shell.querySelector('.eg-edge-list');
  const graphButtons = [...shell.querySelectorAll('[data-filter]')];
  let currentData = graphData || { nodes: [], edges: [] };
  let filter = 'all';
  let selectedId = null;
  let graph = null;
  let disposed = false;
  let pageVisible = document.visibilityState !== 'hidden';
  let inViewport = true;
  let filterClick = null;
  let cameraClick = null;
  let onVisibility = null;
  let intersection = null;

  const setMessage = text => { message.textContent = text; message.hidden = !text; };
  const getSlice = () => graphSlice(currentData, filter);
  const graphDataFor = slice => ({
    nodes: slice.nodes.map(node => ({ ...node, data: node.data })),
    links: slice.edges.map(edge => ({ source: edge.from, target: edge.to, from: edge.from, to: edge.to, kind: edge.kind })),
  });
  const setSelected = (node, notify = false) => {
    selectedId = node?.id ?? null;
    for (const button of nodeList.querySelectorAll('[data-node-id]')) button.setAttribute('aria-pressed', String(button.dataset.nodeId === selectedId));
    renderNodeDetail(detail, node || null, onSelect, notify);
  };
  const renderLists = () => {
    const slice = getSlice();
    const all = graphSlice(currentData);
    nodeList.replaceChildren();
    edgeList.replaceChildren();
    appendText(nodeList, 'h3', `Records (${slice.nodes.length})`, 'eg-list-title');
    const buttons = document.createElement('div');
    buttons.className = 'eg-node-buttons';
    for (const node of slice.nodes) {
      const button = appendText(buttons, 'button', null, 'eg-node');
      button.type = 'button'; button.dataset.nodeId = node.id; button.setAttribute('aria-pressed', String(node.id === selectedId));
      button.dataset.kind = node.kind || 'record';
      appendText(button, 'span', nodeTitle(node), 'eg-node-name');
      appendText(button, 'span', `Record type: ${node.kind || 'record'}.`, 'eg-node-type');
      button.addEventListener('click', () => setSelected(node, true));
    }
    if (slice.nodes.length) nodeList.append(buttons);
    else appendText(nodeList, 'p', 'No records match this filter.', 'eg-empty');
    appendText(edgeList, 'h3', `Connections (${slice.edges.length})`, 'eg-list-title');
    const relations = document.createElement('ul');
    relations.className = 'eg-relations';
    for (const edge of slice.edges) {
      const from = all.nodes.find(node => node.id === edge.from);
      const to = all.nodes.find(node => node.id === edge.to);
      if (!from || !to) continue;
      const row = document.createElement('li');
      appendText(row, 'span', nodeTitle(from));
      appendText(row, 'span', relationName(edge.kind), 'eg-edge-kind');
      appendText(row, 'span', nodeTitle(to));
      relations.append(row);
    }
    if (slice.edges.length) edgeList.append(relations);
    else appendText(edgeList, 'p', 'No source connections are available for this run.', 'eg-empty');
    shell.querySelector('.eg-run').textContent = currentData?.run_id ? `Run ${currentData.run_id}` : '';
    graphButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.filter === filter));
      const kind = button.dataset.filter;
      const count = kind === 'all' ? all.nodes.length : all.nodes.filter(node => category(node.kind) === kind).length;
      button.textContent = `${button.dataset.label || button.textContent.replace(/\s+\(\d+\)$/, '')} (${count})`;
      button.dataset.label ||= button.textContent.replace(/\s+\(\d+\)$/, '');
    });
    if (selectedId && !slice.nodes.some(node => node.id === selectedId)) setSelected(null);
    else if (selectedId) setSelected(slice.nodes.find(node => node.id === selectedId));
    return slice;
  };
  const syncAnimation = () => {
    if (!graph) return;
    if (pageVisible && inViewport && !disposed) graph.resumeAnimation();
    else graph.pauseAnimation();
  };
  const updateGraph = () => {
    const slice = renderLists();
    if (graph) graph.graphData(graphDataFor(slice));
    return slice;
  };
  const initGraph = async () => {
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion) { setMessage('Reduced motion is enabled. Use the record and connection lists below.'); return; }
    if (!webglAvailable()) { setMessage('3D view is unavailable here. Use the record and connection lists below.'); return; }
    setMessage('Loading the evidence graph…');
    try {
      const ForceGraph3D = await loadVendor();
      if (disposed) return;
      graph = ForceGraph3D()(scene)
        .backgroundColor('#080a09')
        .showNavInfo(false)
        .nodeId('id')
        .nodeVal(node => node.kind === 'place' ? 9 : node.kind === 'finding' ? 5 : 3)
        .nodeColor(graphColor)
        .nodeLabel(node => `<strong>${escapeHtml(node.kind || 'record')}</strong><br>${escapeHtml(nodeTitle(node))}`)
        .linkSource('source').linkTarget('target')
        .linkColor(link => link.kind === 'cites' ? '#b8ed81' : link.kind === 'checked_by' ? '#b4beb2' : '#3f4940')
        .linkOpacity(0.68).linkWidth(link => link.kind === 'cites' ? 1.4 : 1)
        .linkDirectionalArrowLength(3).linkDirectionalArrowRelPos(0.92)
        .linkDirectionalParticles(link => link.kind === 'cites' ? 1 : 0)
        .linkDirectionalParticleColor(() => '#b8ed81').linkDirectionalParticleSpeed(0.001)
        .cooldownTicks(70).autoPauseRedraw(true)
        .onNodeClick(node => setSelected(node, true))
        .graphData(graphDataFor(getSlice()));
      const width = Math.max(1, scene.clientWidth);
      const height = Math.max(1, scene.clientHeight);
      graph.width(width).height(height).zoomToFit(0, 64);
      setMessage('');
      syncAnimation();
    } catch {
      graph = null;
      setMessage('3D view could not start. Use the record and connection lists below.');
    }
  };
  filterClick = event => {
    const button = event.target.closest('[data-filter]');
    if (!button) return;
    filter = button.dataset.filter;
    updateGraph();
  };
  cameraClick = event => {
    const button = event.target.closest('[data-camera]');
    if (!button || !graph) return;
    if (button.dataset.camera === 'fit') graph.zoomToFit(350, 64);
    else {
      const position = graph.cameraPosition();
      const scale = button.dataset.camera === 'in' ? 0.8 : 1.25;
      graph.cameraPosition({ x: position.x * scale, y: position.y * scale, z: position.z * scale }, null, 180);
    }
  };
  onVisibility = () => { pageVisible = document.visibilityState !== 'hidden'; syncAnimation(); };
  shell.querySelector('.eg-controls').addEventListener('click', filterClick);
  shell.querySelector('.eg-camera').addEventListener('click', cameraClick);
  document.addEventListener('visibilitychange', onVisibility);
  if ('IntersectionObserver' in window) {
    intersection = new IntersectionObserver(entries => { inViewport = Boolean(entries[0]?.isIntersecting); syncAnimation(); });
    intersection.observe(container);
  }
  renderLists();
  initGraph();

  return {
    update(nextData) {
      if (disposed) return;
      currentData = nextData || { nodes: [], edges: [] };
      updateGraph();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      shell.querySelector('.eg-controls').removeEventListener('click', filterClick);
      shell.querySelector('.eg-camera').removeEventListener('click', cameraClick);
      document.removeEventListener('visibilitychange', onVisibility);
      intersection?.disconnect();
      if (graph) {
        graph.pauseAnimation();
        graph._destructor?.();
        graph.renderer?.()?.dispose?.();
        graph.renderer?.()?.forceContextLoss?.();
        graph.controls?.()?.dispose?.();
      }
      if (externalDetail) externalDetail.replaceChildren();
      container.replaceChildren();
    },
  };
}
