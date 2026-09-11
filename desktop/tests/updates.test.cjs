const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { EventEmitter } = require('node:events');
const crypto = require('node:crypto');
const { UpdateManager, nativeDownloader, nativeFetch, newer, releaseInfo, responseText } = require('../updates.cjs');

const content = Buffer.from('Verified synthetic installer bytes, never executable.');
const digest = crypto.createHash('sha256').update(content).digest('hex');
function release(version = '1.0.4') {
  const names = [`TeXGlot-${version}-macOS-arm64.dmg`, `TeXGlot-${version}-macOS-x64.dmg`, `TeXGlot-${version}-Windows-x64-Setup.exe`, 'SHA256SUMS.txt'];
  return { tag_name: `v${version}`, draft: false, prerelease: false,
    assets: names.map(name => ({ name, state: 'uploaded', size: content.length, digest: `sha256:${digest}`,
      browser_download_url: `https://github.com/Mengqi-Lei/texglot/releases/download/v${version}/${name}` })) };
}
async function manager(t, options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'texglot-update-test-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const installed = [], downloads = [];
  const value = new UpdateManager({
    version: '1.0.3', platform: 'darwin', arch: 'arm64', directory,
    fetch: async () => new Response(JSON.stringify(release())),
    download: async (url, file, size, progress) => { downloads.push(url); await fs.writeFile(file, content); progress(100); },
    install: async file => installed.push(file), ...options,
  });
  return { value, directory, installed, downloads };
}

test('stable versions compare numerically and never offer downgrades or prereleases', () => {
  assert(newer('v1.10.0', '1.9.9'));
  for (const v of ['v1.0.3', 'v1.0.2', 'v1.0.4-beta.1', '1.0', 'v01.0.4', 'v999999999999999999999.0.0']) assert.equal(newer(v, '1.0.3'), false);
  assert.equal(releaseInfo(release('1.0.2'), '1.0.3', 'darwin', 'arm64'), null);
  assert.throws(() => releaseInfo({ ...release(), prerelease: true }, '1.0.3', 'darwin', 'arm64'));
  assert.throws(() => releaseInfo({ ...release(), draft: true }, '1.0.3', 'darwin', 'arm64'));
});
test('platform and architecture select exact uploaded assets in the official repository', () => {
  for (const [platform, arch, suffix] of [['darwin', 'arm64', 'macOS-arm64.dmg'], ['darwin', 'x64', 'macOS-x64.dmg'], ['win32', 'x64', 'Windows-x64-Setup.exe']]) {
    assert(releaseInfo(release(), '1.0.3', platform, arch).asset.name.endsWith(suffix));
  }
  assert.equal(releaseInfo(release(), '1.0.3', 'win32', 'arm64').asset, null);
  for (const change of [{ browser_download_url: 'https://untrusted.example/update.dmg' }, { size: 3 * 1024 ** 3 }, { state: 'new' }, { name: '../../update.dmg' }]) {
    const r = release(); Object.assign(r.assets[0], change);
    assert.equal(releaseInfo(r, '1.0.3', 'darwin', 'arm64').asset, null);
  }
  const r = release(); r.assets.push(r.assets[0]);
  assert.equal(releaseInfo(r, '1.0.3', 'darwin', 'arm64').asset, null);
});
test('checking never downloads or installs; downloads and installation need separate actions', async t => {
  const { value, downloads, installed } = await manager(t);
  assert.equal((await value.check(true)).status, 'available');
  assert.equal(downloads.length, 0); assert.equal(installed.length, 0);
  await value.install(); assert.equal(installed.length, 0);
  assert.equal((await value.download()).status, 'ready');
  assert.equal(downloads.length, 1); assert.equal(installed.length, 0);
  await value.install(); assert.equal(installed.length, 1);
  assert.deepEqual(await fs.readFile(installed[0]), content);
});
test('auto checks respect the stored preference and coalesce concurrent requests', async t => {
  let count = 0, releaseFetch;
  const { value, directory } = await manager(t, { fetch: () => { count++; return new Promise(resolve => { releaseFetch = resolve; }); } });
  value.setAutoCheck(false);
  await value.check(); assert.equal(count, 0);
  const pending = value.check(true);
  assert.equal(value.check(true), pending);
  releaseFetch(new Response(JSON.stringify(release()))); await pending;
  assert.equal(count, 1);
  value.setAutoCheck(true); await value.check(); assert.equal(count, 1);
  value.setAutoCheck(false);
  assert.equal(JSON.parse(await fs.readFile(path.join(directory, 'preferences.json'), 'utf8')).autoCheck, false);
});
test('older releases without API digests use exactly matching SHA256SUMS entries', async t => {
  const r = release(); delete r.assets[0].digest;
  const { value } = await manager(t, { fetch: async url => new Response(url.endsWith('/latest') ? JSON.stringify(r) : `${digest}  ${r.assets[0].name}\n`) });
  await value.check(true);
  assert.equal((await value.download()).status, 'ready');
});
test('a verified download survives app restart and is rechecked before reuse', async t => {
  const { value, directory } = await manager(t);
  await value.check(true); await value.download();
  const restarted = new UpdateManager({ version: '1.0.3', platform: 'darwin', arch: 'arm64', directory,
    fetch: value.fetch, download: () => assert.fail('Unexpected second download'), install: async () => {} });
  assert.equal((await restarted.check(true)).status, 'ready');
  await restarted.install();
  restarted.state.currentVersion = '1.0.4';
  restarted.state.status = 'idle';
  assert.equal((await restarted.check(true)).status, 'current');
  assert.equal((await fs.readdir(directory)).filter(name => name.startsWith('download-')).length, 0);
});
test('native manual redirects expose Location without following or losing cancellation', async () => {
  let request;
  const net = { request: options => {
    assert.equal(options.method, 'HEAD'); assert.equal(options.credentials, 'omit');
    request = new EventEmitter();
    request.end = () => {};
    request.abort = () => request.emit('error', new Error('Redirect was cancelled'));
    return request;
  } };
  const pending = nativeFetch(net, 'https://github.com/latest', { redirect: 'manual' });
  request.emit('redirect', 302, 'HEAD', 'https://github.com/releases/tag/v1.0.4');
  const response = await pending;
  assert.equal(response.status, 302);
  assert.equal(response.headers.get('location'), 'https://github.com/releases/tag/v1.0.4');
  const controller = new AbortController();
  const aborted = nativeFetch(net, 'https://github.com/latest', { redirect: 'manual', signal: controller.signal });
  controller.abort(); await assert.rejects(aborted, /request-aborted/);
});
test('anonymous REST rate limits fall back to official release redirects and checksummed assets', async t => {
  const r = release();
  const { value } = await manager(t, { fetch: async (url, options) => {
    if (url.startsWith('https://api.github.com/')) return new Response('', { status: 403 });
    assert.equal(options.method, 'HEAD');
    const response = new Response(null, { headers: { 'content-length': String(content.length) } });
    Object.defineProperty(response, 'url', { value: url.endsWith('/latest') ? 'https://github.com/Mengqi-Lei/texglot/releases/tag/v1.0.4' : url });
    return response;
  } });
  const state = await value.check(true);
  assert.equal(state.status, 'available'); assert.equal(state.canDownload, true);
  assert.equal(value.release.asset.name, r.assets[0].name);
});
test('cached metadata never permits paths outside its private installer directory', async t => {
  const { value } = await manager(t);
  await fs.writeFile(value.readyPath, JSON.stringify({ folder: '../../outside', name: release().assets[0].name, size: content.length }));
  assert.equal(value.savedDownload(), null);
  assert.equal((await value.check(true)).status, 'available');
});
test('ambiguous checksums prevent downloading an installer', async t => {
  const r = release(); delete r.assets[0].digest;
  const { value, downloads } = await manager(t, { fetch: async url => new Response(url.endsWith('/latest') ? JSON.stringify(r) : `${digest}  ${r.assets[0].name}\n${digest}  ${r.assets[0].name}\n`) });
  await value.check(true);
  assert.equal((await value.download()).error, 'checksum');
  assert.equal(downloads.length, 0);
});
test('corrupt or truncated downloads are deleted and cannot be installed', async t => {
  const { value, directory, installed } = await manager(t, { download: async (_url, file) => fs.writeFile(file, 'corrupt') });
  await value.check(true);
  assert.equal((await value.download()).error, 'checksum');
  await value.install(); assert.equal(installed.length, 0);
  assert.equal((await fs.readdir(directory)).filter(name => name.startsWith('download-')).length, 0);
});
test('ready installer tampering is rejected, and a clean re-download recovers', async t => {
  let file;
  const { value, installed } = await manager(t, { download: async (_url, p) => { file = p; await fs.writeFile(p, content); } });
  await value.check(true); await value.download();
  await fs.writeFile(file, Buffer.alloc(content.length));
  assert.equal((await value.install()).error, 'checksum');
  assert.equal(installed.length, 0);
  assert.equal((await value.download()).status, 'ready');
});
test('busy translation service prevents installation without discarding verified download', async t => {
  const { value } = await manager(t, { install: async () => { throw new Error('jobs-active'); } });
  await value.check(true); await value.download();
  assert.equal((await value.install()).status, 'ready');
  assert.equal(value.snapshot().error, 'jobs-active');
});
test('cancelled downloads cannot publish a late successful result', async t => {
  let finish, started;
  const began = new Promise(resolve => { started = resolve; });
  const { value, directory } = await manager(t, { download: async (_url, file) => {
    await fs.writeFile(file, content); started(); await new Promise(resolve => { finish = resolve; });
  } });
  await value.check(true); const pending = value.download(); await began;
  const cancellation = value.cancel(); finish(); await pending; await cancellation;
  assert.equal(value.snapshot().status, 'available');
  assert.equal(value.snapshot().error, undefined);
  assert.equal((await fs.readdir(directory)).filter(name => name.startsWith('download-')).length, 0);
});
test('metadata has response limits and rate-limit errors remain recoverable', async t => {
  await assert.rejects(responseText(async () => new Response('x'.repeat(100)), 'https://example.org', undefined, 10), /invalid-release/);
  const { value } = await manager(t, { fetch: async () => new Response('', { status: 429 }) });
  assert.equal((await value.check(true)).error, 'rate-limit');
  value.fetch = async () => new Response(JSON.stringify(release('1.0.3')));
  assert.equal((await value.check(true)).status, 'current');
});
test('Chromium download cancellation rejects delayed items and isolates the next attempt', async () => {
  const session = new EventEmitter();
  let requestURL;
  session.downloadURL = url => { requestURL = url; };
  const download = nativeDownloader(session);
  const controller = new AbortController();
  const first = download('https://github.com/file.dmg', '/unused', 10, () => {}, controller.signal);
  const oldURL = requestURL;
  controller.abort(); await assert.rejects(first, /cancelled/);
  const second = download('https://github.com/file.dmg', '/unused', 10, () => {}, new AbortController().signal);
  let rejectedOld = false;
  session.emit('will-download', { preventDefault() { rejectedOld = true; } }, { getURLChain: () => [oldURL] });
  assert(rejectedOld);
  const item = new EventEmitter();
  Object.assign(item, { getURLChain: () => [requestURL], setSavePath: p => assert.equal(p, '/unused'), cancel() {}, getReceivedBytes: () => 10 });
  session.emit('will-download', { preventDefault() { assert.fail('Valid download rejected'); } }, item);
  item.emit('done', {}, 'completed'); await second;
  assert.equal(session.listenerCount('will-download'), 1);
});
