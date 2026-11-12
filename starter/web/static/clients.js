// "X-ray over MCP" card: live MCP call counts across every run, from GET /api/clients.
const LABELS = { cursor: 'Cursor', other: 'Other MCP clients' };
const HIDDEN = new Set(['grok_bot']); // no xAI key: never show a Grok row the demo can't back
const POLL_MS = 10000;

/** [[label, count]] in a stable order: known clients first, then any new ones the API adds. */
export function clientRows(body) {
  const mcp = body && typeof body.mcp === 'object' && !Array.isArray(body.mcp) ? body.mcp : {};
  const keys = [...Object.keys(LABELS), ...Object.keys(mcp).filter(key => !(key in LABELS) && !HIDDEN.has(key)).sort()];
  return keys.map(key => [LABELS[key] || key.replace(/_/g, ' '), Number.isFinite(mcp[key]) ? mcp[key] : 0]);
}

/** Mount the card in `container`; returns { refresh, stop }. Polls every 10 s while the page is visible. */
export function mountClients(container, { fetchJson = path => fetch(path).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }) } = {}) {
  const list = document.createElement('dl');
  const note = document.createElement('p');
  note.className = 'clients-note';
  container.replaceChildren(list, note);
  const refresh = async () => {
    try {
      const rows = clientRows(await fetchJson('/api/clients'));
      list.replaceChildren(...rows.flatMap(([label, count]) => {
        const dt = document.createElement('dt'); dt.textContent = label;
        const dd = document.createElement('dd'); dd.textContent = String(count);
        return [dt, dd];
      }));
      note.textContent = `MCP tool calls across all runs. Updated ${new Date().toLocaleTimeString()}.`;
      container.dataset.state = 'ok';
    } catch {
      note.textContent = 'Live counts unavailable. Showing the last counts received.';
      container.dataset.state = 'error';
    }
  };
  const timer = setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
  refresh();
  return { refresh, stop: () => clearInterval(timer) };
}
