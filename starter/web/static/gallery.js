// "Try these": real crawl listings recorded offline (GET /api/gallery), one per discrepancy type.
const LABELS = {
  property_type: 'The advert and EPC describe different property types',
  price_history: 'Price changed since the crawl',
  photo_reuse: 'Photos reused from another advert',
  area_type: 'Floor area disagrees with the EPC',
};

export const SAVED_RUNS = {
  'macquarie-way': 'xr-6f65393159',
  'kimberley-road': 'xr-131a92ee3b',
  'charlemont-road': 'xr-f20b9504d5',
};

export const discrepancyLabel = kind => LABELS[kind] || String(kind || 'Discrepancy').replace(/_/g, ' ');

/** Valid gallery items only: each needs a name and title. */
export function galleryItems(body) {
  return (Array.isArray(body) ? body : []).filter(item => item && typeof item.name === 'string' && item.name && typeof item.title === 'string');
}

export function savedGalleryItems(body) {
  const items = galleryItems(body);
  if (!items.some(item => item.name === 'macquarie-way')) items.unshift({
    name: 'macquarie-way', title: '24 Macquarie Way, E14', listing_id: 'auctionhouse-0715ecf1',
    discrepancy: 'property_type', url: 'https://www.auctionhouse.co.uk/london/auction/lot/152478',
  });
  return items.map(item => ({ ...item, run_id: SAVED_RUNS[item.name] || item.run_id }));
}

/** Open recorded reports only; no source ingestion is started by this gallery. */
export function renderGallery(container, items, onPick) {
  const list = document.createElement('ul');
  list.className = 'gallery-list';
  for (const item of items) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'gallery-item';
    const title = document.createElement('span'); title.className = 'gallery-title'; title.textContent = item.title;
    const kind = document.createElement('span'); kind.className = 'gallery-kind'; kind.textContent = item.run_id ? discrepancyLabel(item.discrepancy) : 'No saved report available';
    button.disabled = !item.run_id;
    button.append(title, kind);
    button.addEventListener('click', () => onPick(item));
    const li = document.createElement('li'); li.append(button); list.append(li);
  }
  container.querySelector('.gallery-list')?.remove();
  container.append(list);
  container.hidden = !items.length;
}

export async function loadGallery(container, onPick) {
  try {
    const response = await fetch('/api/gallery', { headers: { Accept: 'application/json' } });
    renderGallery(container, response.ok ? savedGalleryItems(await response.json()) : [], onPick);
  } catch { container.hidden = true; /* the gallery is optional: the form still works */ }
}
