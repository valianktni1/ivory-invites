'use strict';

const app = document.querySelector('#app');
const designs = {
  wedding: {name: 'Wedding', title: 'Amelia & Oliver', intro: 'Together with their families', colour: '#4c5631'},
  birthday: {name: 'Birthday', title: 'Leo turns 6!', intro: "You're invited", colour: '#315238'}
};
let photoUpdate = null;
let photoRemoved = false;
let session = {};

function el(tag, value, className) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (className) element.className = className;
  return element;
}

function link(label, href, className) {
  const anchor = el('a', label, className);
  anchor.href = href;
  return anchor;
}

async function api(path, data) {
  const options = data === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  };
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || 'Something went wrong. Try again.');
  }
  return response.json();
}

function header(label, href) {
  const top = el('header', undefined, 'top');
  const brand = link('Ivory Invites', '/', 'brand');
  top.append(brand);
  if (label) top.append(link(label, href, 'nav-link'));
  return top;
}

function dateText(event) {
  const day = new Intl.DateTimeFormat('en-GB', {dateStyle: 'full', timeZone: 'UTC'}).format(
    new Date(event.date + 'T12:00:00Z'));
  return event.time ? day + ' at ' + event.time : day;
}

function alert(form, text) {
  form.querySelector('[role="status"]').textContent = text;
}

function wire(form, handler) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = form.querySelector('button[type=submit]');
    submit.disabled = true;
    alert(form, '');
    try {
      await handler(new FormData(form));
    } catch (error) {
      alert(form, error.message);
    } finally {
      submit.disabled = false;
    }
  });
}

function home() {
  app.replaceChildren(header('Organiser sign in', '/editor'));
  const main = el('section', undefined, 'showcase');
  const copy = el('div', undefined, 'hero');
  copy.append(el('p', 'DIGITAL INVITATIONS', 'eyebrow'),
    el('h1', 'An invitation worth opening.'),
    el('p', 'Try two interactive invitations. Open them as a guest and see how the RSVP works.', 'lede'));
  main.append(copy);
  const cards = el('div', undefined, 'cards');
  for (const [key, design] of Object.entries(designs)) {
    const card = link(undefined, '/demo/' + key, 'design-card ' + key);
    const image = el('img');
    image.src = '/static/' + key + '.webp';
    image.alt = key === 'wedding' ? 'A country house framed by garden flowers' : 'Two painted dinosaurs among ferns';
    const info = el('div', undefined, 'design-info');
    info.append(el('p', design.name, 'eyebrow'), el('h2', design.title), el('span', 'Open demo →', 'design-action'));
    card.append(image, info);
    cards.append(card);
  }
  main.append(cards);
  app.append(main);
}

function showLogin(message = '') {
  app.replaceChildren(header('View demos', '/'));
  const box = el('section', undefined, 'panel login');
  box.innerHTML = `
    <h1>Organiser sign in</h1>
    <form>
      <label>Email address<input required type="email" maxlength="254" autocomplete="username" name="email"></label>
      <label>Password<input required type="password" maxlength="256" autocomplete="current-password" name="password"></label>
      <button type="submit" class="button">Sign in</button>
      <p role="status" class="status"></p>
    </form>
    <div class="account-links">
      ${session.ownerSetup ? '<a href="/account/signup">Set up the owner account</a>' : ''}
      <a href="/account/forgot">Forgot your password?</a>
    </div>`;
  app.append(box);
  const form = box.querySelector('form');
  if (message) alert(form, message);
  wire(form, async (data) => {
    await api('/api/login', {email: data.get('email'), password: data.get('password')});
    session = await api('/api/session');
    if (location.pathname === '/admin') await adminPage();
    else await organiserView();
  });
}

function accountPage(path) {
  app.replaceChildren(header('Organiser sign in', '/editor'));
  const box = el('section', undefined, 'panel login');
  const choosing = path.endsWith('/setup') || path.endsWith('/reset');
  const reset = path.endsWith('/forgot') || path.endsWith('/reset');
  const title = choosing ? (reset ? 'Reset your password' : 'Choose your password')
    : (reset ? 'Forgot your password?' : 'Set up the owner account');
  const token = location.hash.slice(1);
  if (choosing && !/^[A-Za-z0-9_-]{43}$/.test(token)) {
    box.append(el('h1', title), el('p', 'Open the full link from your email to continue.'));
    if (reset) box.append(link('Request a new link', '/account/forgot', 'button'));
    app.append(box);
    return;
  }
  const instructions = choosing ? 'Enter the email address the link was sent to.'
    : (reset ? 'Enter your email address and we’ll send you a link.' : 'Enter the configured owner email address.');
  box.innerHTML = `
    <h1>${title}</h1>
    <p>${instructions}</p>
    <form>
      <label>Email address<input required type="email" maxlength="254" autocomplete="username" name="email"></label>
      ${choosing ? '<label>New password<input required type="password" minlength="8" maxlength="256" autocomplete="new-password" name="password" aria-describedby="password-rules"></label><p id="password-rules" class="muted">Use at least 8 characters, including a special character such as ! or #.</p>' : ''}
      <button type="submit" class="button">${choosing ? (reset ? 'Save new password' : 'Create account') : 'Email me a link'}</button>
      <p role="status" class="status"></p>
    </form>`;
  app.append(box);
  const form = box.querySelector('form');
  wire(form, async (data) => {
    const details = {email: data.get('email')};
    if (choosing) Object.assign(details, {token, password: data.get('password')});
    await api('/api' + path, details);
    if (!choosing) {
      alert(form, reset ? 'If an account exists for that address, a reset link will be emailed to you.'
        : 'If that address is ready for owner setup, a link will be emailed to you. Check your inbox and junk folder.');
    } else if (reset) {
      history.replaceState(null, '', '/editor');
      session = await api('/api/session');
      showLogin('Password updated. Sign in with your new password.');
    } else {
      location.replace('/editor');
    }
  });
}

function organiserHeader() {
  const top = header('Your invitations', '/editor');
  if (session.admin) top.append(link('Admin', '/admin', 'nav-link'));
  const signOut = el('button', 'Sign out', 'quiet');
  signOut.addEventListener('click', async () => {
    await api('/api/logout', {});
    location.assign('/editor');
  });
  top.append(signOut);
  return top;
}

function accessField(value = '') {
  const label = el('label', 'Access');
  const select = el('select');
  select.name = 'access';
  select.required = true;
  for (const [id, title] of [['', 'Choose access'], ['free', 'Free'], ['trial', 'Trial'], ['paid', 'Paid']]) {
    const option = el('option', title);
    option.value = id;
    select.append(option);
  }
  select.value = value;
  label.append(select);
  return label;
}

async function adminPage(message = '') {
  if (!session.admin) {
    const panel = el('section', undefined, 'panel login');
    panel.append(el('h1', 'Administrator access is required'), link('Your invitations', '/editor', 'button'));
    app.replaceChildren(organiserHeader(), panel);
    return;
  }
  const customers = await api('/api/admin/customers');
  const page = el('section', undefined, 'organiser-page admin-page');
  const heading = el('div', undefined, 'organiser-heading');
  heading.append(el('h1', 'Customer access'));
  const status = el('p', message, 'status');
  status.setAttribute('role', 'status');
  heading.append(status);
  const invite = el('section', undefined, 'panel');
  invite.innerHTML = `
    <h2>Invite a customer</h2>
    <p>Free gives your couples full access. Trial allows design and preview. Choose Paid once payment is confirmed.</p>
    <form>
      <label>Customer email<input name="email" type="email" maxlength="254" required></label>
      <button type="submit" class="button">Send setup link</button>
      <p class="status" role="status"></p>
    </form>`;
  const form = invite.querySelector('form');
  form.querySelector('button').before(accessField());
  wire(form, async (fields) => {
    await api('/api/admin/invite', Object.fromEntries(fields));
    await adminPage('Setup link sent.');
  });
  const list = el('section', undefined, 'panel customer-list');
  list.append(el('h2', 'Customers'));
  if (!customers.length) list.append(el('p', 'Customer accounts and pending invitations will appear here.', 'muted'));
  const labels = {active: 'Active', invited: 'Awaiting setup', unsent: 'Email pending'};
  for (const customer of customers) {
    const row = el('form', undefined, 'customer-row');
    const identity = el('div', undefined, 'customer-identity');
    identity.append(el('strong', customer.email), el('p', labels[customer.status], 'muted'));
    const access = accessField(customer.access);
    access.querySelector('select').setAttribute('aria-label', 'Access for ' + customer.email);
    const actions = el('div', undefined, 'actions');
    const save = el('button', 'Change access', 'button secondary');
    save.type = 'submit';
    const feedback = el('p', '', 'status');
    feedback.setAttribute('role', 'status');
    actions.append(save);
    if (customer.status !== 'active') {
      const resend = el('button', 'Send setup link', 'button secondary');
      resend.type = 'button';
      resend.addEventListener('click', async () => {
        resend.disabled = true;
        try {
          await api('/api/admin/invite', {email: customer.email, access: access.querySelector('select').value});
          await adminPage('Setup link sent.');
        } catch (error) {
          alert(row, error.message);
        } finally {
          resend.disabled = false;
        }
      });
      actions.append(resend);
    }
    row.append(identity, access, actions, feedback);
    wire(row, async (fields) => {
      await api('/api/admin/access', {email: customer.email, access: fields.get('access')});
      await adminPage('Access updated.');
    });
    list.append(row);
  }
  page.append(heading, invite, list);
  app.replaceChildren(organiserHeader(), page);
}

function invitationUrl(id) {
  return '/editor?event=' + encodeURIComponent(id);
}

async function dashboard() {
  const events = await api('/api/events');
  const page = el('section', undefined, 'organiser-page');
  const heading = el('div', undefined, 'organiser-heading');
  heading.append(el('h1', 'Your invitations'),
    link('New invitation', '/editor?new=1', 'button'));
  page.append(heading);
  const list = el('div', undefined, 'saved-invitations');
  if (!events.length) list.append(el('p', 'Choose a template to create your first invitation.', 'panel'));
  for (const event of events) {
    const card = link(undefined, invitationUrl(event.id), 'panel saved-invitation');
    const copy = el('div');
    copy.append(el('h2', event.title), el('p', dateText(event), 'muted'));
    card.append(copy, el('span', 'Open invitation →', 'design-action'));
    list.append(card);
  }
  page.append(list);
  app.replaceChildren(organiserHeader(), page);
}

function templatePicker() {
  const page = el('section', undefined, 'organiser-page');
  const heading = el('div', undefined, 'organiser-heading');
  heading.append(el('h1', 'Choose a template'));
  const cards = el('div', undefined, 'cards');
  for (const [key, design] of Object.entries(designs)) {
    const card = link(undefined, '/editor?new=' + key, 'design-card');
    const artwork = el('img');
    artwork.src = '/static/' + key + '.webp';
    artwork.alt = '';
    const copy = el('div', undefined, 'design-info');
    copy.append(el('p', design.name, 'eyebrow'), el('h2', design.title),
      el('span', 'Use this template →', 'design-action'));
    card.append(artwork, copy);
    cards.append(card);
  }
  page.append(heading, cards);
  app.replaceChildren(organiserHeader(), page);
}

async function organiserView() {
  const query = new URLSearchParams(location.search);
  const id = query.get('event');
  const preview = query.get('preview');
  const template = query.get('new');
  if (preview) await guestView(preview, true);
  else if (id) await editor(id);
  else if (template && Object.hasOwn(designs, template)) await editor(null, template);
  else if (query.has('new')) templatePicker();
  else await dashboard();
}

async function editor(id, template = 'wedding') {
  const selected = id ? await api('/api/events/' + encodeURIComponent(id)) : null;
  photoUpdate = null;
  photoRemoved = false;
  const work = el('div', undefined, 'organiser-page editor-workspace');
  const heading = el('div', undefined, 'organiser-heading');
  heading.append(el('h1', id ? 'Edit invitation' : 'Create an invitation'));
  const shortcuts = el('div', undefined, 'actions');
  if (id) {
    shortcuts.append(link('Preview invitation', '/editor?preview=' + encodeURIComponent(id), 'button secondary'));
    if (selected.canShare) shortcuts.append(link('Guest links and replies', '#replies', 'button secondary'));
  } else shortcuts.append(link('Choose another template', '/editor?new=1', 'button secondary'));
  heading.append(shortcuts);
  work.append(heading);
  if (session.access === 'trial') {
    work.append(el('p', 'Trial access lets you design and preview. Guest links and RSVPs unlock when your access is upgraded.', 'muted'));
  }
  const section = el('section', undefined, 'panel');
  section.innerHTML = `
    <form id="event-form">
      <label>Design<select name="template"><option value="wedding">Amelia & Oliver · Wedding</option><option value="birthday">Leo Turns 6 · Birthday</option></select></label>
      <div class="fields"><label>Invitation title<input name="title" required maxlength="90"></label>
      <label>Opening line<input name="intro" maxlength="90"></label></div>
      <div class="fields"><label>Date<input type="date" name="date" required></label>
      <label>Time (UK)<input type="time" name="time"></label></div>
      <label>Venue or address<input name="venue" required maxlength="180"></label>
      <label>Message<textarea name="message" rows="3" maxlength="1200"></textarea></label>
      <div class="fields"><label>Accent colour<input type="color" name="colour"></label>
      <label>Photo (optional)<input type="file" accept="image/*" name="photo"></label></div>
      <button class="quiet" type="button" id="remove-photo" hidden>Use design artwork</button>
      <label>Meal choices (optional, one per line)<textarea name="meal" rows="2" maxlength="500"></textarea></label>
      <label class="check"><input type="checkbox" name="song"> Ask for a song request</label>
      <button type="submit" class="button">Save invitation</button><p role="status" class="status"></p>
    </form>`;
  const form = section.querySelector('form');
  const preview = el('div', undefined, 'editor-preview');
  const artwork = el('img');
  artwork.alt = 'Invitation artwork preview';
  const previewTitle = el('strong');
  preview.append(artwork, previewTitle);
  form.querySelector('#remove-photo').after(preview);
  const remove = form.querySelector('#remove-photo');
  const defaults = selected || {template, ...designs[template]};
  for (const field of ['template', 'title', 'intro', 'date', 'time', 'venue', 'message', 'colour', 'meal']) {
    form.elements[field].value = defaults[field] || '';
  }
  form.elements.song.checked = Boolean(defaults.song);
  function drawPreview() {
    const photo = photoUpdate ? 'data:image/jpeg;base64,' + photoUpdate
      : (selected?.hasPhoto && !photoRemoved ? '/api/events/' + id + '/photo' : '');
    artwork.src = photo || '/static/' + form.elements.template.value + '.webp';
    previewTitle.textContent = form.elements.title.value;
    previewTitle.style.color = readableAccent(form.elements.colour.value);
    remove.hidden = !photo;
  }
  form.elements.template.addEventListener('change', () => {
    const design = designs[form.elements.template.value];
    const previous = Object.values(designs).find((item) => item.title === form.elements.title.value);
    if (!form.elements.title.value || previous) form.elements.title.value = design.title;
    if (!form.elements.intro.value || Object.values(designs).some((item) => item.intro === form.elements.intro.value)) {
      form.elements.intro.value = design.intro;
    }
    form.elements.colour.value = design.colour;
    drawPreview();
  });
  form.elements.title.addEventListener('input', drawPreview);
  form.elements.colour.addEventListener('input', drawPreview);
  form.elements.photo.addEventListener('change', async () => {
    const file = form.elements.photo.files[0];
    if (!file) return;
    const save = form.querySelector('button[type=submit]');
    save.disabled = true;
    try {
      photoUpdate = await resizePhoto(file);
      photoRemoved = false;
      drawPreview();
      alert(form, '');
    } catch (error) {
      alert(form, error.message);
    } finally {
      save.disabled = false;
    }
  });
  remove.addEventListener('click', () => {
    photoUpdate = null;
    photoRemoved = true;
    form.elements.photo.value = '';
    drawPreview();
  });
  drawPreview();
  wire(form, async (fields) => {
    const details = Object.fromEntries(fields);
    details.song = fields.has('song');
    details.photo = photoUpdate;
    details.removePhoto = photoRemoved;
    const saved = await api('/api/events' + (id ? '/' + encodeURIComponent(id) : ''), details);
    history.replaceState(null, '', invitationUrl(saved.id));
    await editor(saved.id);
    alert(document.querySelector('#event-form'), 'Invitation saved.');
  });
  work.append(section);
  if (selected?.canShare) work.append(households(selected));
  app.replaceChildren(organiserHeader(), work);
}

async function resizePhoto(file) {
  if (file.size > 20_000_000) throw new Error('Choose a photo smaller than 20 MB.');
  const url = URL.createObjectURL(file);
  try {
    const photo = new Image();
    photo.src = url;
    await photo.decode();
    const ratio = Math.min(1, 1200 / Math.max(photo.naturalWidth, photo.naturalHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(photo.naturalWidth * ratio));
    canvas.height = Math.max(1, Math.round(photo.naturalHeight * ratio));
    const context = canvas.getContext('2d', {alpha: false});
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(photo, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
  } catch {
    throw new Error('This photo could not be opened. Try a JPEG or PNG.');
  } finally {
    URL.revokeObjectURL(url);
  }
}

function households(event) {
  const section = el('section', undefined, 'panel');
  section.id = 'replies';
  section.innerHTML = `
    <h2>Guest links and replies</h2>
    <p>Make one link per household. Each named guest can reply separately.</p>
    <form>
      <label>Household name<input name="household name" required maxlength="100" placeholder="The Smith family"></label>
      <label>Guest names (one per line)<textarea name="guest names" rows="2" maxlength="800" required></textarea></label>
      <button type="submit" class="button">Create guest link</button><p role="status" class="status"></p>
    </form>`;
  wire(section.querySelector('form'), async (fields) => {
    await api('/api/events/' + event.id + '/households', Object.fromEntries(fields));
    await editor(event.id);
    const latest = document.querySelector('.household:last-child');
    latest?.scrollIntoView({block: 'nearest'});
    latest?.querySelector('input')?.focus({preventScroll: true});
  });
  for (const household of event.households) {
    const block = el('article', undefined, 'household');
    const url = new URL('/invite/' + household.token, location.origin).href;
    const field = el('input');
    field.value = url;
    field.readOnly = true;
    field.setAttribute('aria-label', 'Invitation link for ' + household.label);
    const actions = el('div', undefined, 'actions');
    const copy = el('button', 'Copy link', 'button secondary');
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(url);
        copy.textContent = 'Copied';
      } catch {
        field.focus();
        field.select();
        copy.textContent = 'Link selected';
      }
    });
    actions.append(copy, link('Open invite', url, 'button secondary'),
      link('Share on WhatsApp', 'https://wa.me/?text=' + encodeURIComponent(url), 'button secondary'));
    block.append(el('h3', household.label), el('p', household.names.join(', ')), field, actions);
    if (household.reply) {
      const replies = el('ul', undefined, 'replies');
      for (const person of household.reply.people) {
        const summary = [person.status === 'yes' ? 'Attending' : 'Unable to attend', person.meal, person.dietary];
        replies.append(el('li', person.name + ' · ' + summary.filter(Boolean).join(' · ')));
      }
      block.append(replies);
      if (household.reply.song) block.append(el('p', 'Song request · ' + household.reply.song));
    } else {
      block.append(el('p', 'Awaiting reply', 'muted'));
    }
    section.append(block);
  }
  return section;
}

function readableAccent(hex) {
  const channels = hex.slice(1).match(/.{2}/g).map((value) => parseInt(value, 16) / 255);
  const luminance = channels.map((c) => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const lightness = luminance[0] * 0.2126 + luminance[1] * 0.7152 + luminance[2] * 0.0722;
  return lightness > 0.16 ? '#293224' : hex;
}

async function guestView(token, preview = false) {
  const path = '/api/events/' + encodeURIComponent(token);
  let guest;
  if (preview) {
    const draft = await api(path);
    guest = {event: draft, label: 'Your guests', photo: draft.hasPhoto ? path + '/photo' : ''};
  } else guest = await api('/api/guest/' + token);
  const event = guest.event;
  document.title = event.title + ' · Ivory Invites';
  const page = el('div', undefined, 'guest-page ' + event.template);
  page.style.setProperty('--accent', readableAccent(event.colour));
  page.style.setProperty('--chosen', event.colour);
  const shell = el('section', undefined, 'opening');
  const opener = el('button', undefined, 'opener');
  opener.setAttribute('aria-label', 'Open invitation');
  const wedding = event.template === 'wedding';
  const decoration = el('span', undefined, wedding ? 'envelope' : 'egg');
  decoration.setAttribute('aria-hidden', 'true');
  if (wedding) {
    const initials = event.title.split(/\s*(?:&|\+|\band\b)\s*/i).slice(0, 2)
      .map(name => name.trim().match(/\p{L}/u)?.[0] || '').filter(Boolean).join(' & ');
    const letter = el('span', undefined, 'envelope-letter');
    letter.append(el('span', initials.toLocaleUpperCase('en-GB')));
    const seal = el('span', undefined, 'wax-seal');
    seal.append(el('span', initials.toLocaleUpperCase('en-GB') || '✦'));
    decoration.append(letter, el('span', undefined, 'envelope-front'),
      el('span', undefined, 'envelope-flap'), seal);
  } else {
    decoration.append(el('span', undefined, 'egg-light'), el('span', undefined, 'egg-top'),
      el('span', undefined, 'egg-bottom'), el('span', undefined, 'egg-crack'));
  }
  opener.append(decoration);
  shell.append(el('p', 'AN INVITATION FOR', 'eyebrow'), el('h1', guest.label), opener,
    el('p', wedding ? 'Tap the wax seal to open' : 'Tap the egg to hatch it', 'opening-hint'));
  const card = el('article', undefined, 'invite-card');
  card.hidden = true;
  const cover = el('div', undefined, 'cover-copy');
  if (event.intro) cover.append(el('p', event.intro, 'eyebrow'));
  const title = el('h1', event.title);
  title.tabIndex = -1;
  cover.append(title);
  if (wedding) cover.append(el('span', undefined, 'cover-rule'));
  const image = el('img', undefined, 'cover-image');
  image.src = guest.photo || '/static/' + event.template + '.webp';
  image.alt = guest.photo ? 'Event photo' : event.template === 'wedding' ? 'An English country house and gardens' : 'Painted dinosaurs and ferns';
  const details = el('section', undefined, 'invite-details');
  details.append(el('p', dateText(event), 'event-date'), el('p', event.venue, 'venue'));
  if (event.message) details.append(el('p', event.message, 'event-message'));
  const actions = el('div', undefined, 'actions');
  const map = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(event.venue);
  if (!preview) {
    actions.append(link('RSVP', '#rsvp', 'button'));
    if (!guest.demo) actions.append(link('Directions', map, 'button secondary'));
    actions.append(link('Add to calendar', '/calendar/' + token, 'button secondary'));
    details.append(actions);
  }
  card.append(cover, image, details);
  if (!preview) card.append(replyForm(token, guest));
  function open() {
    opener.disabled = true;
    shell.classList.add('unsealing');
    const duration = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 920;
    window.setTimeout(() => {
      shell.hidden = true;
      card.hidden = false;
      title.focus({preventScroll: true});
    }, duration);
  }
  opener.addEventListener('click', open);
  if (guest.demo) page.append(header('All demos', '/'));
  if (preview) page.append(header('Back to editor', invitationUrl(token)));
  page.append(shell, card);
  app.replaceChildren(page);
}

function replyForm(token, guest) {
  const section = el('section', undefined, 'rsvp');
  section.id = 'rsvp';
  section.append(el('h2', 'RSVP'));
  if (guest.demo) section.append(el('p', 'This is a demo. Your reply is not saved.', 'muted'));
  if (guest.answered) section.append(el('p', 'A reply has already been sent. Submit a fresh reply for everyone to update it.'));
  const form = el('form');
  const mealChoices = guest.event.meal.split(/\r?\n/).map((meal) => meal.trim()).filter(Boolean);
  guest.names.forEach((name, index) => {
    const group = el('fieldset');
    group.append(el('legend', name));
    const choices = el('div', undefined, 'choices');
    for (const [value, label] of [['yes', 'Attending'], ['no', 'Unable to attend']]) {
      const option = el('label', undefined, 'check');
      const radio = el('input');
      radio.type = 'radio';
      radio.name = 'status' + index;
      radio.value = value;
      radio.required = true;
      option.append(radio, document.createTextNode(label));
      choices.append(option);
    }
    group.append(choices);
    if (mealChoices.length) {
      const extras = el('div', undefined, 'meal-fields');
      extras.hidden = true;
      const mealLabel = el('label', 'Meal choice');
      const select = el('select');
      select.name = 'meal' + index;
      const blank = el('option', 'Select a meal (optional)');
      blank.value = '';
      select.append(blank);
      for (const meal of mealChoices) select.append(el('option', meal));
      mealLabel.append(select);
      const dietaryLabel = el('label', 'Dietary requirements (optional)');
      const dietary = el('input');
      dietary.name = 'dietary' + index;
      dietary.maxLength = 160;
      dietaryLabel.append(dietary);
      extras.append(mealLabel, dietaryLabel);
      group.append(extras);
      choices.addEventListener('change', () => {
        extras.hidden = form.elements['status' + index].value !== 'yes';
      });
    }
    form.append(group);
  });
  if (guest.event.song) {
    const label = el('label', 'Song request (optional)');
    const input = el('input');
    input.name = 'song';
    input.maxLength = 120;
    label.append(input);
    form.append(label);
  }
  const submit = el('button', guest.answered ? 'Update reply' : 'Send RSVP', 'button');
  submit.type = 'submit';
  const status = el('p', '', 'status');
  status.setAttribute('role', 'status');
  form.append(submit, status);
  wire(form, async (fields) => {
    const people = guest.names.map((_, index) => ({
      status: fields.get('status' + index),
      meal: fields.get('meal' + index) || '',
      dietary: fields.get('dietary' + index) || ''
    }));
    await api('/api/guest/' + token, {people, song: fields.get('song') || ''});
    status.textContent = guest.demo ? 'Demo complete. Here’s where guests see their confirmation.' : 'Thank you. Your RSVP has been sent.';
  });
  section.append(form);
  return section;
}

async function start() {
  try {
    const path = location.pathname;
    if (path.startsWith('/demo/') || path.startsWith('/invite/')) {
      await guestView(path.split('/')[2]);
    } else if (path.startsWith('/account/')) {
      accountPage(path);
    } else if (path === '/editor' || path === '/admin') {
      session = await api('/api/session');
      if (session.signedIn && path === '/admin') await adminPage();
      else if (session.signedIn) await organiserView();
      else showLogin();
    } else {
      home();
    }
  } catch (error) {
    const panel = el('section', undefined, 'panel login');
    panel.append(el('h1', 'Invitation unavailable'), el('p', error.message), link('Ivory Invites', '/', 'button'));
    app.replaceChildren(panel);
  }
}

start();
