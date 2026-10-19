const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'extraction_smart.js'), 'utf8');
const classSource = source.slice(source.indexOf('class ExtractionSmartSystem'), source.indexOf('// Initialize system after DOM'));
const settle = () => new Promise(resolve => setImmediate(resolve));
const kind = 'incoming_internal';

function harness({ reserveError = false, voidError = false, kind = 'incoming_internal' } = {}) {
  const nodes = new Map();
  for (const id of ['reservationRing', 'reservationStatus', 'reservationTimer', 'reservationContext',
    'bookNumberHint', 'bookNumber', 'bookKind', 'numberlessCheckbox', 'recycledBanner',
    'bookRegisterChip', 'releaseReservationBtn', 'saveButton', `tabNum_${kind}`]) {
    const classes = new Set();
    nodes.set(id, {
      value: '', textContent: '', innerHTML: '', title: '', dataset: {}, style: {},
      classList: {
        add(...names) { names.forEach(n => classes.add(n)); },
        remove(...names) { names.forEach(n => classes.delete(n)); },
        toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
        contains(name) { return classes.has(name); },
      },
      setAttribute(name, value) { this[name] = value; },
      addEventListener(name, handler) { this[name] = handler; },
      focus() { this.focused = true; },
      querySelector() { return null; },
    });
  }
  nodes.get('bookKind').value = kind;
  const calls = [];
  const toasts = [];
  const reservation = {
    id: 1, number: 3925, formatted: '3925', kind, status: 'active',
    expires_at: new Date(Date.now() + 2700000).toISOString(),
  };
  const context = vm.createContext({
    document: {
      getElementById(id) { return nodes.get(id) || null; },
      querySelector() { return null; },
    },
    window: { confirm: () => true },
    console: { warn() {}, info() {}, log() {} },
    setTimeout, clearTimeout, setInterval, clearInterval,
    async fetch(url, options = {}) {
      calls.push({ url, method: options.method || 'GET' });
      const failed = (url === '/reserve/' && reserveError) || (url === '/void/' && voidError);
      return {
        ok: !failed, status: failed ? 400 : 200,
        json: async () => url.startsWith('/status/')
          ? { has_reservation: false, preview_number: '3930', other_holds: { count: 0, numbers: [] } }
          : url === '/save/'
            ? { success: true, book_id: 20, book_number: '3925' }
            : { success: !failed, reservation, message: 'reservation failed' },
      };
    },
  });
  const System = vm.runInContext(`${classSource}\nExtractionSmartSystem`, context);
  const system = Object.create(System.prototype);
  Object.assign(system, {
    reservations: {}, _reservationRequests: {},
    apiEndpoints: { reservationReserve: '/reserve/', reservationStatus: '/status/', reservationVoid: '/void/', saveBook: '/save/' },
    getCurrentKind: () => nodes.get('bookKind').value,
    getCookie: () => 'csrf',
    _kindMeta: () => ({ label: 'الوارد الداخلي', bg: '#fff', fg: '#000' }),
    showToast: (...args) => toasts.push(args),
    _ensurePresence() {}, _ensureReservationCountdown() {}, _beep() {},
    _flushPendingEntities: async () => {},
    _sessionExpired: () => false, t: value => value,
    smartClearAndStay() {}, clearFile() {},
  });
  return { system, nodes, calls, toasts, reservation };
}

test('external outgoing uses explicit system reservation and a separate office number', async () => {
  const h = harness({ kind: 'outgoing_external' });
  const config = h.system.getKindConfig('outgoing_external');
  assert.ok(!config.manualNumber);
  assert.equal(config.showDirectorGeneralNumber, true);
  await h.system.ensureReservation('outgoing_external');
  assert.equal(h.calls.filter(c => c.url === '/reserve/').length, 1);
  assert.equal(h.nodes.get('bookNumber').value, '3925');
});

test('opening and switching kinds never reserves or displays an unheld preview', async () => {
  const h = harness();
  h.system.loadAllReservationStatuses();
  await settle();
  h.system.renderReservationState(kind);
  h.system.renderReservationState('incoming_external');
  assert.equal(h.calls.filter(c => c.method === 'POST').length, 0);
  assert.equal(h.nodes.get('bookNumber').value, '');
  assert.equal(h.nodes.get(`tabNum_${kind}`).textContent, '—');
  assert.equal(h.nodes.get('reservationRing')['aria-pressed'], 'false');
});

test('explicit click reserves once, disables while pending and becomes green on success', async () => {
  const h = harness();
  h.system.loadAllReservationStatuses();
  await settle();
  const first = h.system.ensureReservation(kind);
  const second = h.system.ensureReservation(kind);
  assert.equal(h.nodes.get('reservationRing').disabled, true);
  assert.equal(h.nodes.get('reservationRing')['aria-busy'], 'true');
  await Promise.all([first, second]);
  assert.equal(h.calls.filter(c => c.url === '/reserve/').length, 1);
  assert.equal(h.nodes.get('bookNumber').value, '3925');
  assert.equal(h.nodes.get('reservationRing').classList.contains('is-reserved'), true);
});

test('failed reservation stays unreserved, reports error and permits retry', async () => {
  const h = harness({ reserveError: true });
  assert.equal(await h.system.ensureReservation(kind), null);
  assert.equal(h.nodes.get('reservationRing').disabled, false);
  assert.equal(h.nodes.get('bookNumber').value, '');
  assert.ok(h.toasts.some(t => t[1] === 'error'));
  assert.equal(h.calls.length, 1);
});

test('losing or expiring a reservation never silently obtains a different number', async () => {
  const h = harness();
  h.system.reservations[kind] = h.reservation;
  h.system._onReservationLost(kind);
  await h.system.recoverReservationForRetry(kind, 'expired');
  assert.equal(h.calls.length, 0);
  assert.equal(h.nodes.get('bookNumber').value, '');
  assert.equal(h.nodes.get('reservationRing').disabled, false);
});

test('release leaves standby without reserving again', async () => {
  const h = harness();
  h.system.reservations[kind] = h.reservation;
  h.system._releaseCurrentReservation();
  await settle();
  assert.deepEqual(h.calls.map(c => c.url), ['/void/']);
  assert.equal(h.system.reservations[kind], undefined);
  assert.equal(h.nodes.get('bookNumber').value, '');
});

test('failed release preserves the hold and shows an error', async () => {
  const h = harness({ voidError: true });
  h.system.reservations[kind] = h.reservation;
  h.system._releaseCurrentReservation();
  await settle();
  assert.equal(h.system.reservations[kind].id, 1);
  assert.ok(h.toasts.some(t => t[1] === 'error'));
});

test('saving without a reservation requires explicit activation instead of auto-numbering', async () => {
  const h = harness();
  await h.system.saveBook();
  assert.equal(h.calls.length, 0);
  assert.equal(h.nodes.get('reservationRing').focused, true);
});

test('successful save returns to standby without another reservation', async () => {
  const h = harness();
  h.system.reservations[kind] = h.reservation;
  const data = new FormData();
  data.set('kind', kind);
  await h.system.submitBookData(data);
  assert.deepEqual(h.calls.map(c => c.url), ['/save/']);
  assert.equal(h.system.reservations[kind], undefined);
  assert.equal(h.nodes.get('reservationRing')['aria-pressed'], 'false');
});

test('another kind losing its reservation cannot clear the active kind field', () => {
  const h = harness();
  h.system.reservations[kind] = h.reservation;
  h.system.applyReservationToUI(kind, h.reservation);
  h.system._onReservationLost('incoming_external');
  assert.equal(h.nodes.get('bookNumber').value, '3925');
});

test('an idle standby page sends no heartbeat and displays no idle warning', () => {
  const h = harness();
  h.system._lastActivity = Date.now() - 3600000;
  for (let n = 0; n < 20; n++) h.system._presenceTick();
  assert.equal(h.calls.length, 0);
  assert.equal(h.toasts.length, 0);
});

test('numberless and edit modes cannot allocate numbers with the reserve button', async () => {
  const h = harness();
  h.nodes.get('numberlessCheckbox').checked = true;
  assert.equal(await h.system.ensureReservation(kind), null);
  h.nodes.get('numberlessCheckbox').checked = false;
  h.system._editData = { pk: 20 };
  assert.equal(await h.system.ensureReservation(kind), null);
  assert.equal(h.calls.length, 0);
});
