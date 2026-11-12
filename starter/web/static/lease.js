const $ = id => document.getElementById(id);
const LABELS = {
  parties: 'Parties', premises: 'Premises', permitted_use: 'Permitted use',
  contractual_term: 'Contractual term', main_rent: 'Main rent', rent_review: 'Rent review',
  break_clause: 'Break clause', alienation: 'Assignment & subletting', insurance: 'Insurance',
  lr_prescribed_clauses: 'Land Registry clauses',
};
const label = field => LABELS[field] || field.replaceAll('_', ' ');
const node = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};

async function request(url, options) {
  const response = await fetch(url, options);
  let body;
  try { body = await response.json(); }
  catch { throw new Error('The server did not return a readable response. Please try again.'); }
  if (!response.ok) {
    const detail = typeof body.error === 'string' ? body.error : body.detail;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}). Please try again.`);
  }
  return body;
}

async function loadEvaluation() {
  $('benchmark-retry').hidden = true;
  $('benchmark-status').textContent = 'Loading the recorded results…';
  try {
    const result = await request('/api/lease/eval');
    $('benchmark-strict').textContent = `${result.overall.strict} / ${result.overall.n}`;
    $('benchmark-content').textContent = `${result.overall.content} / ${result.overall.n}`;
    $('benchmark-documents').textContent = `${result.documents} documents · ${result.overall.n} fields checked. These are in-sample results, not a score for your upload.`;
    $('benchmark-fields').replaceChildren();
    for (const [field, score] of Object.entries(result.fields)) {
      const row = node('tr');
      const heading = node('th', label(field)); heading.scope = 'row';
      row.append(heading, node('td', `${score.strict} / ${score.n}`), node('td', `${score.content} / ${score.n}`));
      $('benchmark-fields').append(row);
    }
    $('benchmark-status').textContent = '';
    $('benchmark-results').hidden = false;
  } catch (error) {
    $('benchmark-status').textContent = `Evaluation unavailable. ${error.message}`;
    $('benchmark-retry').hidden = false;
  }
}

function renderTerms(result, filename) {
  const terms = Object.entries(result.terms);
  let missing = 0;
  let placeholders = 0;
  $('lease-terms').replaceChildren();
  for (const [field, term] of terms) {
    const absent = term.value == null || term.value === '';
    missing += Number(absent);
    placeholders += Number(!absent && term.placeholder);
    const state = absent ? 'Not found' : term.placeholder ? 'Placeholder' : 'Text found';
    const detail = node('details', undefined, 'lease-term');
    detail.dataset.state = absent || term.placeholder ? 'attention' : 'found';
    detail.dataset.field = field;
    detail.open = field === 'main_rent';
    const summary = node('summary');
    summary.append(node('span', label(field), 'lease-term-name'), node('span', state, 'lease-term-state'));
    const body = node('div', undefined, 'lease-term-body');
    const finding = (result.findings || []).find(item => item.field === field);
    if (absent) {
      body.append(node('p', finding?.reasoning || 'No text was found for this term in the document.'));
    } else {
      body.append(node('p', `Source: ${term.source || 'Uploaded document'}`, 'status'));
      body.append(node('blockquote', term.value));
      if (term.optional) body.append(node('p', 'Optional clause: bracketed in the source document.', 'status'));
      if (finding?.reasoning) body.append(node('p', finding.reasoning, 'status'));
    }
    detail.append(summary, body);
    $('lease-terms').append(detail);
  }
  $('lease-filename').textContent = filename;
  $('lease-counts').textContent = `${terms.length} terms checked · ${placeholders} placeholders · ${missing} not found`;
  $('lease-results').hidden = false;
}

$('lease-file').addEventListener('change', () => {
  const file = $('lease-file').files[0];
  $('lease-submit').disabled = !file;
  $('lease-results').hidden = true;
  $('lease-error').hidden = true;
  $('lease-status').textContent = file ? `Ready to read ${file.name}.` : 'Select a document to begin.';
});

$('lease-form').addEventListener('submit', async event => {
  event.preventDefault();
  const file = $('lease-file').files[0];
  if (!file) return;
  $('lease-error').hidden = true;
  $('lease-results').hidden = true;
  try {
    if (!file.name.toLowerCase().endsWith('.docx')) throw new Error('Choose a Word document (.docx).');
    if (file.size > 5 * 1024 * 1024) throw new Error('This file is too large. Choose a document up to 5 MB.');
    $('lease-submit').disabled = true;
    $('lease-file').disabled = true;
    $('lease-form').setAttribute('aria-busy', 'true');
    $('lease-status').textContent = 'Reading the lease and locating its source clauses…';
    const body = new FormData(); body.append('file', file);
    const result = await request('/api/lease/abstract', { method: 'POST', body });
    renderTerms(result, file.name);
    $('lease-status').textContent = 'Lease read. The extracted terms and source text are below.';
    $('lease-results').scrollIntoView({ block: 'start' });
  } catch (error) {
    $('lease-error').textContent = error.message;
    $('lease-error').hidden = false;
    $('lease-status').textContent = 'The lease could not be read. Choose another document or try again.';
  } finally {
    $('lease-file').disabled = false;
    $('lease-submit').disabled = !$('lease-file').files.length;
    $('lease-form').removeAttribute('aria-busy');
  }
});
$('benchmark-retry').addEventListener('click', loadEvaluation);
loadEvaluation();
