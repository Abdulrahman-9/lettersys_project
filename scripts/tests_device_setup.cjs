const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'device_setup.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

async function harness({ secure = true, server = { ok: true }, agent = null, devices = null } = {}) {
  const nodes = new Map();
  for (const id of ['deviceSetup', 'setupConnection', 'deviceCheckResult', 'checkDevice',
    'deviceCheckSpinner', 'deviceCheckLabel', 'deviceSetupHelp', 'downloadSetup',
    'showTrustHelp', 'trustSetupHelp', 'showSetupHelp', 'showScannerHelp', 'scannerSetupHelp',
    'retryConnection', 'recheckAfterSetup', 'recheckScanner', 'goEnrollment',
    'deviceEnrollment', 'workstationName', 'installSetupApp', 'setupInstallResult']) {
    nodes.set(id, {
      dataset: {}, hidden: false, disabled: false, textContent: '', className: '',
      classList: { add() {}, remove() {} },
      addEventListener(name, handler) { this[name] = handler; },
      setAttribute(name, value) { this[name] = value; },
      querySelector() { return { focus() {} }; },
      scrollIntoView() { this.scrolled = true; },
      focus() { this.focused = true; },
    });
  }
  nodes.get('deviceSetup').dataset = { healthUrl: '/server-health', agentPort: '17865' };
  for (const id of ['trustSetupHelp', 'scannerSetupHelp', 'deviceEnrollment']) nodes.get(id).hidden = true;
  const calls = [];
  const logs = [];
  const context = vm.createContext({
    document: { getElementById(id) { return nodes.get(id); }, dispatchEvent() {} },
    CustomEvent: class CustomEvent { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    window: { isSecureContext: secure, addEventListener() {} },
    location: { protocol: secure ? 'https:' : 'http:' },
    console: { warn(...args) { logs.push(args); }, error(...args) { logs.push(args); } },
    AbortController, setTimeout, clearTimeout,
    async fetch(url) {
      calls.push(url);
      let data = url === '/server-health' ? server : url.endsWith('/agent/health') ? agent : devices;
      if (data instanceof Error || data === null) throw data || new Error('connection refused');
      return { ok: true, json: async () => data };
    },
  });

  vm.runInContext(source, context);
  await settle();
  return {
    nodes, calls, logs,
    async check() { await nodes.get('checkDevice').click(); },
    message() { return nodes.get('deviceCheckResult').textContent; },
  };
}

const readyAgent = { ok: true, version: '1.0.1', naps2_available: true };

test('each preparation action reveals its own guide and exposes expanded state', async () => {
  const h = await harness();
  for (const [trigger, panel] of [
    ['showTrustHelp', 'trustSetupHelp'], ['showSetupHelp', 'deviceSetupHelp'],
    ['showScannerHelp', 'scannerSetupHelp'],
  ]) {
    h.nodes.get(trigger).click();
    assert.equal(h.nodes.get(panel).hidden, false);
    assert.equal(h.nodes.get(trigger)['aria-expanded'], 'true');
    assert.equal(h.nodes.get(panel).scrolled, true);
  }
});

test('naming action leads to required check rather than pretending to register a device', async () => {
  const h = await harness();
  h.nodes.get('goEnrollment').click();
  assert.match(h.message(), /أولاً/);
  assert.equal(h.nodes.get('checkDevice').focused, true);
  assert.ok(!h.calls.some(url => url.includes('/enroll')));
  h.nodes.get('deviceEnrollment').hidden = false;
  h.nodes.get('goEnrollment').click();
  assert.equal(h.nodes.get('workstationName').focused, true);
});

test('recheck and connection-retry buttons run the actual checks', async () => {
  const h = await harness({ agent: readyAgent, devices: { ok: true, devices: [] } });
  for (const id of ['recheckAfterSetup', 'recheckScanner']) {
    h.nodes.get(id).click();
    await settle();
    assert.match(h.message(), /لم يظهر ماسح/);
  }
  const retry = h.nodes.get('retryConnection');
  await retry.click({ currentTarget: retry });
  assert.equal(retry.disabled, false);
  assert.ok(h.calls.filter(url => url === '/server-health').length >= 4);
});

test('install action preserves direct user activation and offers honest manual recovery', async () => {
  const h = await harness();
  const callsBefore = h.calls.length;
  await h.nodes.get('installSetupApp').click({ currentTarget: h.nodes.get('installSetupApp') });
  assert.equal(h.calls.length, callsBefore);
  assert.match(h.nodes.get('setupInstallResult').textContent, /قائمة المتصفح/);
  const insecure = await harness({ secure: false });
  await insecure.nodes.get('installSetupApp').click({ currentTarget: insecure.nodes.get('installSetupApp') });
  assert.match(insecure.nodes.get('setupInstallResult').textContent, /الاتصال الآمن/);
});

test('secure server connection is verified independently of scanner availability', async () => {
  const h = await harness();
  assert.match(h.nodes.get('setupConnection').textContent, /جاهز وآمن/);
  assert.deepEqual(h.calls, ['/server-health']);
});

test('HTTP offers no certificate-package download and does not probe local devices', async () => {
  const h = await harness({ secure: false });
  await h.check();
  assert.equal(h.nodes.get('downloadSetup').hidden, true);
  assert.match(h.message(), /الاتصال الآمن/);
  assert.ok(h.calls.every(url => url === '/server-health'));
});

test('server failure cannot be mistaken for scanner readiness', async () => {
  const h = await harness({ server: new Error('offline'), agent: readyAgent });
  await h.check();
  assert.match(h.nodes.get('setupConnection').textContent, /تعذّر الاتصال/);
  assert.ok(h.logs.length > 0);
  assert.ok(h.calls.every(url => url === '/server-health'));
});

test('unreachable or blocked agent offers one preparation step without claiming cause', async () => {
  const h = await harness();
  await h.check();
  assert.match(h.message(), /لم نتمكن من الوصول/);
  assert.equal(h.nodes.get('deviceSetupHelp').hidden, false);
  assert.equal(h.nodes.get('showSetupHelp')['aria-expanded'], 'true');
  assert.equal(h.nodes.get('checkDevice').disabled, false);
});

test('missing NAPS2 and outdated agent both request preparation, not driver guessing', async () => {
  for (const agent of [
    { ok: true, version: '1.0.1', naps2_available: false },
    { ok: true, version: '1.0.0', naps2_available: true },
  ]) {
    const h = await harness({ agent });
    await h.check();
    assert.equal(h.nodes.get('deviceSetupHelp').hidden, false);
    assert.ok(!h.calls.some(url => url.endsWith('/agent/devices')));
  }
});

test('empty enumeration asks for cable/power/driver help, not reinstalling working tools', async () => {
  const h = await harness({ agent: readyAgent, devices: { ok: true, devices: [] } });
  await h.check();
  assert.match(h.message(), /لم يظهر ماسح/);
  assert.equal(h.nodes.get('deviceSetupHelp').hidden, true);
  assert.ok(!h.calls.some(url => url.includes('/agent/scan')));
});

test('enumeration warnings and malformed responses never count as readiness', async () => {
  for (const devices of [
    { ok: true, devices: [], warning: 'driver timed out' },
    { ok: true, devices: [{ name: '' }] },
    { ok: false, devices: [] },
  ]) {
    const h = await harness({ agent: readyAgent, devices });
    await h.check();
    assert.match(h.message(), /لا نعدّه جاهزاً/);
    assert.ok(h.logs.length > 0);
  }
});

test('real enumerated names are shown as text and paper scanning remains unclaimed', async () => {
  const h = await harness({ agent: readyAgent, devices: { ok: true, devices: [{ name: '<scanner>' }] } });
  await h.check();
  assert.match(h.message(), /<scanner>/);
  assert.match(h.message(), /جرّب ورقة/);
  assert.equal(h.nodes.get('deviceSetupHelp').hidden, true);
  assert.equal(h.nodes.get('checkDevice').disabled, false);
  assert.ok(!h.calls.some(url => url.includes('/agent/scan')));
});

test('pairing errors prefer the actionable Arabic server message over a technical code', async () => {
  const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'workstation_setup.js'), 'utf8');
  const start = script.indexOf('async function json(');
  const end = script.indexOf("document.addEventListener('lettersys:agent-detected'", start);
  assert.ok(start >= 0 && end > start);
  for (const data of [
    { ok: false, error: 'name_conflict', message: 'اسم الجهاز مستخدم. اختر اسماً آخر.' },
    { ok: false, error: 'Local agent pairing failed' },
  ]) {
    const context = vm.createContext({
      AbortController, setTimeout, clearTimeout,
      fetch: async () => ({ ok: false, status: 409, json: async () => data }),
    });
    vm.runInContext(script.slice(start, end), context);
    await assert.rejects(context.json('/fixture'), error => error.message === (data.message || data.error));
  }
});
