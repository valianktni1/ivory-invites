'use strict';

function stationerySelect(label, id, values) {
  const field = el('div', undefined, 'form-field');
  const title = el('label', label);
  title.htmlFor = id;
  const select = el('select');
  select.id = id;
  for (const [value, name] of Object.entries(values)) select.add(new Option(name, value));
  field.append(title, select);
  return {field, select};
}

function paletteControl(metadata) {
  const picker = stationerySelect('Colour palette', 'suite-palette',
    Object.fromEntries(Object.keys(metadata.palettes).map(name => [name, name])));
  picker.select.value = metadata.palette;
  const colours = el('span', undefined, 'palette-colours');
  colours.setAttribute('aria-hidden', 'true');
  function update() {
    colours.replaceChildren(...metadata.palettes[picker.select.value].map(colour => {
      const swatch = el('span');
      swatch.style.backgroundColor = colour;
      return swatch;
    }));
  }
  update();
  picker.select.addEventListener('change', update);
  picker.field.append(colours);
  return picker;
}

async function stationeryDemo(template) {
  const base = '/api/stationery/demo/' + encodeURIComponent(template);
  const metadata = await api(base);
  const page = el('section', undefined, 'organiser-page stationery-workspace');
  const title = el('div', undefined, 'organiser-heading');
  title.append(el('h1', designs[template].name),
    link('Open invitation demo', '/demo/' + encodeURIComponent(template), 'button secondary'));
  const picker = paletteControl(metadata);
  const grid = el('div', undefined, 'suite-grid');
  const dialog = el('dialog', undefined, 'suite-dialog');
  const dialogTitle = el('h2');
  dialogTitle.id = 'suite-dialog-title';
  dialog.setAttribute('aria-labelledby', dialogTitle.id);
  const enlarged = el('img');
  const close = el('button', 'Close preview', 'button secondary');
  close.type = 'button';
  close.addEventListener('click', () => dialog.close());
  dialog.append(dialogTitle, close, enlarged);
  function draw() {
    const palette = Object.keys(metadata.palettes).indexOf(picker.select.value);
    grid.replaceChildren(...Object.entries(metadata.kinds).map(([kind, item]) => {
      const tile = el('article', undefined, 'suite-tile');
      const photo = el('img');
      photo.src = [base, kind, palette].join('/');
      photo.alt = '';
      photo.loading = 'lazy';
      const show = el('button', undefined, 'suite-tile-open');
      show.type = 'button';
      show.append(photo, el('span', item.name));
      show.addEventListener('click', () => {
        dialogTitle.textContent = item.name;
        enlarged.alt = 'Sample ' + item.name.toLowerCase() + ' in ' + picker.select.value;
        enlarged.src = photo.src;
        dialog.showModal();
      });
      tile.append(show);
      return tile;
    }));
  }
  picker.select.addEventListener('change', draw);
  draw();
  page.append(title, picker.field, grid, dialog);
  app.replaceChildren(header('All designs', '/'), page);
}

async function stationeryWorkspace(id) {
  const base = '/api/stationery/' + encodeURIComponent(id);
  const metadata = await api(base);
  const names = Object.fromEntries(Object.entries(metadata.kinds).map(([key, item]) => [key, item.name]));
  const pieces = stationerySelect('Stationery piece', 'suite-kind', names);
  const palette = paletteControl(metadata);
  const page = el('section', undefined, 'organiser-page stationery-workspace');
  const heading = el('div', undefined, 'organiser-heading');
  heading.append(el('h1', 'Matching stationery'),
    link('Back to invitation', invitationUrl(id), 'button secondary'));
  const pickers = el('div', undefined, 'fields suite-controls');
  pickers.append(pieces.field, palette.field);
  const layout = el('div', undefined, 'editor-layout');
  const panel = el('section', undefined, 'panel');
  const preview = el('aside', undefined, 'preview-panel suite-preview');
  preview.id = 'stationery-preview';
  const print = el('img');
  print.hidden = true;
  preview.append(el('h2', 'Print preview'), print);
  layout.append(panel, preview);
  page.append(heading, pickers, layout);
  if (!metadata.canDownload) {
    page.insertBefore(el('p', 'Trial access includes saving and previewing. Full access includes downloads.', 'muted'), layout);
  }
  app.replaceChildren(organiserHeader(), page);

  const drafts = new Map();
  let active;
  let imageURL;
  let rendered;
  window.addEventListener('pagehide', () => {
    if (imageURL) URL.revokeObjectURL(imageURL);
  }, {once: true});

  function snapshot() {
    const data = Object.fromEntries(new FormData(active.form));
    delete data.bleed;
    for (const field of ['photo_x', 'photo_y', 'photo_zoom']) {
      if (field in data) data[field] = Number(data[field]);
      else if (field in active.item.draft) data[field] = active.item.draft[field];
    }
    return data;
  }

  function markPreview() {
    print.classList.toggle('suite-photo-preview', Boolean(metadata.hasPhoto && active.item.photo));
    print.alt = active.item.name + ' print preview';
    const outdated = rendered !== JSON.stringify([active.key, palette.select.value, snapshot()]);
    active.status.textContent = outdated ? 'Preview again to check your changes.' : 'Preview is up to date.';
  }

  function showPiece(key) {
    if (active) drafts.set(active.key, snapshot());
    const item = metadata.kinds[key];
    const values = drafts.get(key) || item.draft;
    const form = el('form');
    const size = stationerySelect('Paper size', 'suite-size', item.sizes);
    size.select.name = 'size';
    size.select.value = values.size;
    form.append(size.field);
    for (const [field, name] of Object.entries(item.fields)) {
      const label = el('label', name);
      const multiline = field === 'lines' || field === 'message';
      const input = el(multiline ? 'textarea' : 'input');
      input.name = field;
      if (multiline) {
        input.rows = field === 'lines' ? 9 : 3;
        input.maxLength = field === 'lines' ? 12000 : 1200;
      } else {
        input.type = {time: 'time', date: 'date'}[field] || 'text';
        input.maxLength = {title: 90, intro: 120, venue: 180, reply: 240}[field] || 10;
      }
      input.value = values[field] || '';
      label.append(input);
      if (field === 'lines') label.append(el('small', item.hint, 'muted'));
      form.append(label);
    }

    if (key === 'place' && metadata.attending) {
      const importNames = el('button', 'Add guests who accepted', 'quiet');
      importNames.type = 'button';
      importNames.addEventListener('click', () => {
        const field = form.elements.lines;
        field.value = [...new Set([field.value, metadata.attending].join('\n').split(/\r?\n/)
          .map(line => line.trim()).filter(Boolean))].join('\n');
        markPreview();
      });
      form.append(importNames);
    }
    if (metadata.hasPhoto && item.photo) {
      const photo = el('details', undefined, 'event-options');
      photo.append(el('summary', 'Position and zoom your photo'),
        el('p', 'Use the controls or drag on the print preview, then preview again.', 'muted'));
      for (const [field, name, min, max, step] of [
        ['photo_x', 'Horizontal position', 0, 100, 1], ['photo_y', 'Vertical position', 0, 100, 1],
        ['photo_zoom', 'Zoom', 1, 3, .05]
      ]) {
        const label = el('label', name);
        const range = el('input');
        range.type = 'range';
        range.name = field;
        range.min = min;
        range.max = max;
        range.step = step;
        range.value = values[field];
        label.append(range);
        photo.append(label);
      }
      form.append(photo);
    }

    const actions = el('div', undefined, 'actions');
    for (const [action, name, style] of [
      ['preview', 'Preview', 'button secondary'], ['save', 'Save this piece', 'button'],
      ['pdf', 'Download PDF', 'button secondary'], ['png', 'Download PNG', 'button secondary']
    ]) {
      if (!metadata.canDownload && ['pdf', 'png'].includes(action)) continue;
      if (action === 'png' && !['day', 'evening', 'save-date', 'thanks'].includes(key)) continue;
      const button = el('button', name, style);
      button.type = 'button';
      button.addEventListener('click', () => perform(action));
      actions.append(button);
    }
    if (metadata.canDownload) {
      const bleed = el('label', undefined, 'check');
      const box = el('input');
      box.type = 'checkbox';
      box.name = 'bleed';
      bleed.append(box, document.createTextNode('Add 3 mm bleed to individual PDFs'));
      form.append(bleed);
    }
    const status = el('p', undefined, 'status');
    status.setAttribute('role', 'status');
    const reset = el('button', 'Use current invitation details', 'quiet');
    reset.type = 'button';
    reset.addEventListener('click', () => {
      for (const field of ['title', 'date', 'venue', ...(key === 'day' ? ['time'] : [])]) {
        if (form.elements[field]) form.elements[field].value = item.defaults[field] || '';
      }
      markPreview();
    });
    if (item.fields.title && !['seating', 'menu', 'thanks'].includes(key)) form.append(reset);
    form.append(actions, status);
    form.addEventListener('input', markPreview);
    form.addEventListener('submit', event => {
      event.preventDefault();
      perform('preview');
    });
    active = {key, item, form, status, actions};
    panel.replaceChildren(el('h2', item.name), form);
    print.hidden = true;
    if (imageURL) URL.revokeObjectURL(imageURL);
    imageURL = undefined;
    rendered = undefined;
    perform('preview');
  }

  async function perform(action) {
    const current = active;
    const payload = {draft: snapshot(), palette: palette.select.value,
      bleed: Boolean(current.form.elements.bleed?.checked)};
    for (const button of current.actions.children) button.disabled = true;
    current.status.textContent = action === 'save' ? 'Saving…' : 'Preparing ' + (action === 'preview' ? 'preview…' : 'download…');
    try {
      const response = await fetch(base + '/' + current.key + '/' + action, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error || 'Please try again.');
      }
      if (action === 'save') {
        current.status.textContent = 'Saved. This palette applies across your stationery.';
      } else {
        const url = URL.createObjectURL(await response.blob());
        if (action === 'preview') {
          if (current !== active || palette.select.value !== payload.palette) {
            URL.revokeObjectURL(url);
            return;
          }
          if (imageURL) URL.revokeObjectURL(imageURL);
          imageURL = url;
          print.src = imageURL;
          print.hidden = false;
          rendered = JSON.stringify([current.key, payload.palette, payload.draft]);
          markPreview();
        } else {
          const anchor = link('', url);
          anchor.download = 'ivory-' + current.key + '.' + action;
          anchor.click();
          window.setTimeout(() => URL.revokeObjectURL(url), 30000);
          current.status.textContent = 'Download ready.';
        }
      }
    } catch (error) {
      current.status.textContent = error.message;
    } finally {
      for (const button of current.actions.children) button.disabled = false;
    }
  }

  let drag;
  print.draggable = false;
  print.addEventListener('pointerdown', event => {
    if (event.pointerType === 'touch' || !active.form.elements.photo_x) return;
    drag = {x: event.clientX, y: event.clientY, form: active.form,
      photoX: Number(active.form.elements.photo_x.value), photoY: Number(active.form.elements.photo_y.value)};
    print.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  print.addEventListener('pointermove', event => {
    if (!drag || drag.form !== active.form) return;
    drag.form.elements.photo_x.value = Math.max(0, Math.min(100, drag.photoX - (event.clientX - drag.x) / 2));
    drag.form.elements.photo_y.value = Math.max(0, Math.min(100, drag.photoY - (event.clientY - drag.y) / 2));
    markPreview();
  });
  print.addEventListener('lostpointercapture', () => { drag = undefined; });
  palette.select.addEventListener('change', () => perform('preview'));
  pieces.select.addEventListener('change', () => showPiece(pieces.select.value));
  showPiece(pieces.select.value);
}
