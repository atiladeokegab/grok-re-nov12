// "Try these": real crawl listings recorded offline (GET /api/gallery), one per discrepancy type.
const LABELS = {
  price_history: 'Price changed since the crawl',
  photo_reuse: 'Photos reused from another advert',
  area_type: 'Floor area disagrees with the EPC',
};

export const discrepancyLabel = kind => LABELS[kind] || String(kind || 'Discrepancy').replace(/_/g, ' ');

/** Valid gallery items only: each needs a name to start the run and a title to show. */
export function galleryItems(body) {
  return (Array.isArray(body) ? body : []).filter(item => item && typeof item.name === 'string' && item.name && typeof item.title === 'string');
}

/** Fill `container` with one button per item; `onPick(item)` starts the run. Hides it when empty. */
export function renderGallery(container, items, onPick) {
  const list = document.createElement('ul');
  list.className = 'gallery-list';
  for (const item of items) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'gallery-item';
    const title = document.createElement('span'); title.className = 'gallery-title'; title.textContent = item.title;
    const kind = document.createElement('span'); kind.className = 'gallery-kind'; kind.textContent = discrepancyLabel(item.discrepancy);
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
    renderGallery(container, response.ok ? galleryItems(await response.json()) : [], onPick);
  } catch { container.hidden = true; /* the gallery is optional: the form still works */ }
}
