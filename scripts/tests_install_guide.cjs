const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
const start = source.indexOf('let deferredPrompt;');
const end = source.indexOf("window.addEventListener('online'", start);
assert.ok(start >= 0 && end > start);
const installCode = source.slice(start, end);

function harness({ secure = true, installed = false, embedded = false, storageBlocked = false } = {}) {
  const events = {};
  const storage = new Map();
  const guides = [];
  const notices = [];
  const logs = [];
  const elements = new Map();
  const focus = { isConnected: true, restored: false, focus() { this.restored = true; } };
  const document = {
    activeElement: focus,
    getElementById(id) { return elements.get(id) || null; },
    createElement() {
      return { style: {}, remove() { elements.delete('installBanner'); } };
    },
    body: {
      appendChild(element) {
        elements.set('installBanner', element);
        for (const id of ['installButton', 'dismissInstall']) {
          elements.set(id, { disabled: false, addEventListener(name, callback) { this[name] = callback; } });
        }
      },
    },
  };
  const window = {
    self: {},
    isSecureContext: secure,
    matchMedia() { return { matches: installed }; },
    addEventListener(name, callback) { events[name] = callback; },
    ToastCenter: {
      action(type, message, actions, opts) {
        const api = {
          element: { dataset: {}, querySelector() { return { focus() {} }; } },
          hide() { opts.onHidden(); },
        };
        guides.push({ type, message, actions, opts, api });
        return api;
      },
    },
  };
  window.top = embedded ? {} : window.self;
  const context = vm.createContext({
    window,
    document,
    navigator: {},
    location: { protocol: secure ? 'https:' : 'http:', pathname: '/login/' },
    localStorage: {
      getItem(key) { if (storageBlocked) throw new Error('blocked'); return storage.get(key); },
      setItem(key, value) { if (storageBlocked) throw new Error('blocked'); storage.set(key, value); },
    },
    console: { warn(...args) { logs.push(args); }, error(...args) { logs.push(args); } },
    showToast(...args) { notices.push(args); },
  });
  vm.runInContext(installCode, context);
  return { context, guides, events, storage, notices, logs, elements, focus };
}

test('HTTPS first visit guides through three persistent, dismissible steps once', () => {
  const h = harness();
  h.context.initInstallGuide();
  assert.equal(h.guides.length, 1);
  assert.match(h.guides[0].message, /شهادة الثقة/);
  assert.equal(h.guides[0].opts.autohide, false);
  assert.equal(h.guides[0].api.element.dataset.installGuide, 'true');
  h.guides[0].actions[0].onClick();
  h.guides[0].api.hide();
  assert.match(h.guides[1].message, /Edge/);
  h.guides[1].actions[0].onClick();
  h.guides[1].api.hide();
  assert.match(h.guides[2].message, /لا تشغّل خادماً/);
  h.guides[2].actions[0].onClick();
  h.guides[2].api.hide();
  assert.equal(h.focus.restored, true);
  h.context.initInstallGuide();
  assert.equal(h.guides.length, 3);
});

test('closing the first step ends the guide and remembers the visit', () => {
  const h = harness();
  h.context.initInstallGuide();
  h.guides[0].api.hide();
  h.context.initInstallGuide();
  assert.equal(h.guides.length, 1);
});

test('HTTP explains prerequisites, not install availability', () => {
  const h = harness({ secure: false });
  h.context.initInstallGuide();
  assert.match(h.guides[0].message, /ليس متاحاً/);
  h.guides[0].actions[0].onClick();
  h.guides[0].api.hide();
  assert.match(h.guides[1].message, /أغلق المتصفح/);
  assert.match(h.guides[1].opts.title, /2 من 2/);
});

test('installed, embedded, and offline contexts do not show onboarding', () => {
  for (const options of [{ installed: true }, { embedded: true }]) {
    const h = harness(options);
    h.context.initInstallGuide();
    assert.equal(h.guides.length, 0);
  }
  const h = harness();
  vm.runInContext("location.pathname = '/offline.html'", h.context);
  h.context.initInstallGuide();
  assert.equal(h.guides.length, 0);
});

test('blocked storage reports errors but still provides help', () => {
  const h = harness({ storageBlocked: true });
  h.context.initInstallGuide();
  assert.equal(h.guides.length, 1);
  assert.equal(h.logs.length, 2);
});

test('install offer is deduplicated and acceptance is not reported as completed', async () => {
  const h = harness();
  let calls = 0;
  const event = { preventDefault() {}, async prompt() { calls++; }, userChoice: Promise.resolve({ outcome: 'accepted' }) };
  h.events.beforeinstallprompt(event);
  const banner = h.elements.get('installBanner');
  h.events.beforeinstallprompt(event);
  assert.equal(h.elements.get('installBanner'), banner);
  await h.context.promptAppInstall(h.elements.get('installButton'));
  assert.equal(calls, 1);
  assert.match(h.notices[0][0], /قبول طلب/);
  assert.equal(h.notices[0][1], 'info');
  h.events.appinstalled();
  assert.equal(h.notices[1][1], 'success');
});

test('install prompt failure is explicit and removes the stale offer', async () => {
  const h = harness();
  h.events.beforeinstallprompt({ preventDefault() {}, prompt() { throw new Error('unavailable'); } });
  await h.context.promptAppInstall(h.elements.get('installButton'));
  assert.equal(h.logs.length, 1);
  assert.equal(h.notices[0][1], 'error');
  assert.equal(h.elements.has('installBanner'), false);
});
