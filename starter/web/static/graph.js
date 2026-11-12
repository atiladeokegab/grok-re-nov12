import { fieldName, safeUrl, timestamp, valueText, VERDICTS } from './data.js';

// The evidence graph of one check, read left to right: advert claim -> finding -> source evidence.
const EXTRA_FIELDS = { bedrooms: 'Bedrooms', bathrooms: 'Bathrooms', epc_valid_until: 'Certificate valid until', address: 'Address' };
const VERDICT_ORDER = ['disagrees', 'flag', 'unverifiable', 'matches'];
const SHORT_VERDICT = { matches: 'Matches', disagrees: 'Doesn’t match', unverifiable: 'Can’t verify', flag: 'Worth a look' };
const legendName = (verdict, n) => ({ disagrees: n === 1 ? 'mismatch' : 'mismatches', matches: n === 1 ? 'match' : 'matches', flag: 'worth a look', unverifiable: 'can’t verify' })[verdict];
const AGENTS = { epc: 'EPC agent', listing_history: 'Listing history agent', floor_plan: 'Floor plan agent', companies_house: 'Companies House agent', photos: 'Photo agent' };

const asId = value => value == null ? '' : String(value);
const list = value => Array.isArray(value) ? value : [];

export function label(field) {
  const name = EXTRA_FIELDS[field] || fieldName(field);
  return name.charAt(0).toUpperCase() + name.slice(1);
}

// Plain-English value; objects other than a room schedule have no honest one-line form, so none.
export function plainValue(record) {
  const value = record?.value;
  if (value == null || value === '') return '';
  if (typeof value === 'object' && !Array.isArray(value?.rooms)) return '';
  return valueText(value, record.unit).replace(/\bm2\b/g, 'm²');
}

export function quoteOf(record) {
  const quote = record?.span?.quote || record?.doc_span;
  return typeof quote === 'string' ? quote.trim() : '';
}

export function agentName(agent) {
  if (!agent) return '';
  return AGENTS[agent] || `${label(agent)} agent`;
}

export function nodeTitle(node) {
  const data = node?.data || {};
  if (node?.kind === 'place') return data.address || data.title || node.id;
  if (node?.kind === 'document') return data.title || data.name || data.file_name || data.filename || 'Source document';
  if (node?.kind === 'finding') return `${label(data.field)}: ${VERDICTS[data.verdict] || 'Status not recorded'}`;
  const value = plainValue(data);
  return data.field ? `${label(data.field)}${value ? `: ${value}` : ''}` : 'Record';
}

// One row per finding (worst first) with its claim and cited evidence; the rest are left over.
// shortcut: a claim or evidence record shared by two findings is drawn once per row, upgrade to a
// measured edge layer if the API starts sharing records across findings.
export function storyRows(graphData) {
  const nodes = list(graphData?.nodes).filter(node => node && node.id != null).map(node => ({ ...node, id: asId(node.id), data: node.data && typeof node.data === 'object' ? node.data : {} }));
  const byId = new Map(nodes.map(node => [node.id, node]));
  const edges = list(graphData?.edges).filter(edge => edge && byId.has(asId(edge.from)) && byId.has(asId(edge.to)));
  const findings = nodes.filter(node => node.kind === 'finding');
  const rank = node => { const i = VERDICT_ORDER.indexOf(node.data.verdict); return i < 0 ? VERDICT_ORDER.length : i; };
  findings.sort((a, b) => rank(a) - rank(b));
  const used = new Set();
  const rows = findings.map(finding => {
    const claim = byId.get(asId(finding.data.claim_id));
    const cited = edges.filter(edge => asId(edge.from) === finding.id && edge.kind === 'cites').map(edge => byId.get(asId(edge.to)));
    const evidence = cited.length ? cited : list(finding.data.evidence_ids).map(id => byId.get(asId(id))).filter(Boolean);
    [finding, claim, ...evidence].forEach(node => node && used.add(node.id));
    return { verdict: finding.data.verdict || 'unknown', finding, claim: claim?.kind === 'claim' ? claim : null, evidence: evidence.filter(node => node.kind === 'evidence') };
  });
  const place = nodes.find(node => node.kind === 'place') || null;
  return {
    place,
    rows,
    otherClaims: nodes.filter(node => node.kind === 'claim' && !used.has(node.id)),
    otherEvidence: nodes.filter(node => node.kind === 'evidence' && !used.has(node.id)),
    nodes: byId,
  };
}

function el(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text != null) item.textContent = String(text);
  return item;
}

function nodeButton(node, kind, verdict) {
  const data = node.data;
  const button = el('button', `eg-card eg-card-${kind}`);
  button.type = 'button';
  button.dataset.nodeId = node.id;
  button.setAttribute('aria-pressed', 'false');
  if (verdict) button.dataset.verdict = verdict;
  if (kind === 'finding') {
    button.append(el('span', 'eg-card-caption', label(data.field)), el('span', 'eg-verdict', SHORT_VERDICT[data.verdict] || 'Not recorded'));
  } else {
    const caption = kind === 'claim' ? label(data.field) : (data.source_name || data.source || 'Source record');
    const value = plainValue(data) || quoteOf(data) || 'Not recorded';
    button.append(el('span', 'eg-card-caption', caption), el('span', 'eg-card-value', kind === 'claim' ? value : `${label(data.field)}: ${value}`));
    const fetched = data.fetched_at || data.captured_at || data.retrieved_at;
    if (kind === 'evidence' && (data.agent || fetched)) button.append(el('span', 'eg-card-stamp', [agentName(data.agent), fetched ? `retrieved ${timestamp(fetched)}` : ''].filter(Boolean).join(' · ')));
  }
  button.setAttribute('aria-label', kind === 'finding' ? `Finding: ${nodeTitle(node)}` : `${kind === 'claim' ? 'Advert claim' : 'Source evidence'}: ${nodeTitle(node)}`);
  return button;
}

const ghost = text => el('div', 'eg-card eg-ghost', text);

function renderDetail(detail, node, onSelect) {
  detail.replaceChildren();
  if (!node) { detail.append(el('p', 'eg-empty', 'Select any box to read its source, quote and when it was fetched.')); return; }
  const data = node.data || {};
  const kindName = { claim: 'What the advert says', finding: 'What X-ray found', evidence: 'What the record says' }[node.kind] || 'Record';
  detail.append(el('p', 'eg-detail-kind', kindName));
  const title = el('h3', 'eg-detail-title', node.kind === 'finding' ? label(data.field) : nodeTitle(node));
  detail.append(title);
  if (node.kind === 'finding') {
    const badge = el('p', 'eg-verdict eg-detail-verdict', VERDICTS[data.verdict] || 'Status not recorded');
    badge.dataset.verdict = data.verdict || 'unknown';
    detail.append(badge);
    if (data.reasoning) detail.append(el('p', 'eg-reasoning', String(data.reasoning).replace(/\bm2\b/g, 'm²')));
  }
  const quote = node.kind === 'finding' ? '' : quoteOf(data);
  if (quote) {
    const block = el('blockquote', 'eg-quote');
    block.append(el('p', null, `“${quote}”`));
    detail.append(block);
  }
  const facts = el('dl', 'eg-facts');
  const add = (term, value) => { if (value) facts.append(el('dt', null, term), el('dd', null, value)); };
  if (node.kind === 'claim') add('Source', 'The advert');
  if (node.kind === 'evidence') add('Source', data.source_name || data.source || 'Source record');
  const fetched = data.fetched_at || data.captured_at || data.retrieved_at || data.created_at;
  add(node.kind === 'finding' ? 'Decided' : 'Fetched', fetched ? timestamp(fetched) : '');
  add(node.kind === 'finding' ? 'Decided by' : 'Agent', node.kind === 'finding' ? (data.model === 'rules' ? 'Rule check (no model)' : data.model) : agentName(data.agent) || (node.kind === 'claim' ? 'Advert reader' : ''));
  if (facts.childElementCount) detail.append(facts);
  const href = safeUrl(data.source_url) || safeUrl(data.url);
  if (href) {
    const link = el('a', 'eg-source-link', `Open the source at ${new URL(href).hostname}`);
    link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    detail.append(link);
  }
  if (node.kind === 'finding' && onSelect) {
    const open = el('button', 'eg-open', 'Open this finding');
    open.type = 'button';
    open.addEventListener('click', () => onSelect({ kind: node.kind, id: node.id, data }));
    detail.append(open);
  }
}

export function mountGraph(container, graphData, { onSelect } = {}) {
  if (!container) throw new TypeError('mountGraph requires a container');
  const shell = el('section', 'eg-graph');
  shell.setAttribute('aria-label', 'Evidence graph');
  const head = el('header', 'eg-header');
  const map = el('div', 'eg-map');
  const detail = el('aside', 'eg-detail');
  detail.setAttribute('aria-live', 'polite');
  detail.setAttribute('aria-label', 'Selected record');
  const body = el('div', 'eg-body');
  body.append(map, detail);
  shell.append(head, body);
  container.replaceChildren(shell);
  let story = storyRows(graphData);
  let selectedId = null;

  const select = id => {
    selectedId = id;
    for (const card of map.querySelectorAll('[data-node-id]')) card.setAttribute('aria-pressed', String(card.dataset.nodeId === id));
    for (const row of map.querySelectorAll('.eg-row')) row.classList.toggle('is-active', Boolean(row.querySelector(`[aria-pressed="true"]`)));
    renderDetail(detail, story.nodes.get(id) || null, onSelect);
  };

  const render = () => {
    head.replaceChildren();
    const titleWrap = el('div');
    titleWrap.append(el('h3', 'eg-title', story.place ? nodeTitle(story.place) : 'This check'));
    const counts = el('p', 'eg-legend');
    for (const verdict of VERDICT_ORDER) {
      const n = story.rows.filter(row => row.verdict === verdict).length;
      if (!n) continue;
      const chip = el('span', 'eg-legend-item', `${n} ${legendName(verdict, n)}`);
      chip.dataset.verdict = verdict;
      counts.append(chip);
    }
    titleWrap.append(counts);
    head.append(titleWrap);

    map.replaceChildren();
    const columns = el('div', 'eg-row eg-columns');
    columns.setAttribute('aria-hidden', 'true');
    columns.append(el('span', null, 'The advert says'), el('span'), el('span', null, 'X-ray found'), el('span'), el('span', null, 'The records say'));
    map.append(columns);
    if (!story.rows.length) map.append(el('p', 'eg-empty', 'This check has no findings to connect yet.'));
    for (const row of story.rows) {
      const line = el('div', 'eg-row');
      line.dataset.verdict = row.verdict;
      const left = row.claim ? nodeButton(row.claim, 'claim') : ghost('The advert doesn’t say');
      const right = el('div', 'eg-sources');
      if (row.evidence.length) row.evidence.forEach(item => right.append(nodeButton(item, 'evidence')));
      else right.append(ghost('No source checks this yet'));
      const edge = side => { const e = el('span', `eg-edge eg-edge-${side}`); if (side === 'in' ? !row.claim : !row.evidence.length) e.classList.add('is-missing'); return e; };
      line.append(left, edge('in'), nodeButton(row.finding, 'finding', row.verdict), edge('out'), right);
      map.append(line);
    }
    const others = [['Also in the advert, not checked', story.otherClaims, 'claim'], ['Also on record', story.otherEvidence, 'evidence']];
    for (const [heading, items, kind] of others) {
      if (!items.length) continue;
      const group = el('div', 'eg-others');
      group.append(el('span', 'eg-others-title', heading));
      for (const item of items) {
        const chip = el('button', 'eg-chip', nodeTitle(item));
        chip.type = 'button'; chip.dataset.nodeId = item.id; chip.dataset.kind = kind; chip.setAttribute('aria-pressed', 'false');
        group.append(chip);
      }
      map.append(group);
    }
    const first = story.rows.find(row => row.verdict === 'disagrees') || story.rows[0];
    select(story.nodes.has(selectedId) ? selectedId : first?.finding.id ?? null);
  };

  const onClick = event => {
    const card = event.target.closest('[data-node-id]');
    if (card) select(card.dataset.nodeId);
  };
  map.addEventListener('click', onClick);
  render();

  return {
    update(nextData) { story = storyRows(nextData); render(); },
    dispose() { map.removeEventListener('click', onClick); container.replaceChildren(); },
  };
}
