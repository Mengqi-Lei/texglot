// Explicit, verified installer downloads. macOS installation remains an OS action
// until Developer ID signing allows the standard native automatic updater.
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

const REPOSITORY = 'https://github.com/Mengqi-Lei/texglot';
const LATEST = 'https://api.github.com/repos/Mengqi-Lei/texglot/releases/latest';
const CHECK_INTERVAL = 12 * 60 * 60 * 1000;
const MAX_INSTALLER_BYTES = 2 * 1024 * 1024 * 1024;

function versionParts(value) {
  const match = /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(value || '');
  const parts = match?.slice(1).map(Number);
  return parts?.every(Number.isSafeInteger) ? parts : null;
}
function newer(candidate, current) {
  const a = versionParts(candidate), b = versionParts(current);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}
function installerName(version, platform, arch) {
  return platform === 'darwin' && ['arm64', 'x64'].includes(arch)
    ? `TeXGlot-${version}-macOS-${arch}.dmg`
    : platform === 'win32' && arch === 'x64' ? `TeXGlot-${version}-Windows-x64-Setup.exe` : '';
}
function assetFor(release, name, limit = MAX_INSTALLER_BYTES) {
  const matches = release.assets?.filter(asset => asset.name === name) || [];
  if (matches.length !== 1) return null;
  const asset = matches[0];
  const url = `${REPOSITORY}/releases/download/${release.tag_name}/${name}`;
  return asset.state === 'uploaded' && asset.browser_download_url === url &&
    Number.isSafeInteger(asset.size) && asset.size > 0 && asset.size <= limit
    ? { name, url, size: asset.size, digest: asset.digest } : null;
}
function releaseInfo(release, current, platform, arch) {
  if (!release || release.draft !== false || release.prerelease !== false || !versionParts(release.tag_name)) {
    throw new Error('invalid-release');
  }
  if (!newer(release.tag_name, current)) return null;
  const version = release.tag_name.replace(/^v/, '');
  const filename = installerName(version, platform, arch);
  return {
    version, url: `${REPOSITORY}/releases/tag/${release.tag_name}`,
    asset: filename ? assetFor(release, filename) : null,
    checksum: assetFor(release, 'SHA256SUMS.txt', 128 * 1024),
  };
}
async function releaseRedirect(fetch, current, platform, arch) {
  // Public release redirects remain usable when a shared network exhausts the
  // anonymous REST quota. Only official URLs and exact byte lengths are accepted.
  const options = { method: 'HEAD', credentials: 'omit', signal: AbortSignal.timeout(15000) };
  const latest = await fetch(`${REPOSITORY}/releases/latest`, { ...options, redirect: 'manual' });
  const redirected = [301, 302, 303, 307, 308].includes(latest.status);
  if (!latest.ok && !redirected) throw new Error('rate-limit');
  const prefix = `${REPOSITORY}/releases/tag/`;
  // Electron's net.fetch does not populate Response.url on followed redirects.
  const destination = redirected ? new URL(latest.headers.get('location'), REPOSITORY).href : latest.url;
  if (!destination?.startsWith(prefix)) throw new Error('invalid-release');
  const tag = destination.slice(prefix.length);
  if (!versionParts(tag)) throw new Error('invalid-release');
  const info = releaseInfo({ tag_name: tag, draft: false, prerelease: false, assets: [] }, current, platform, arch);
  if (!info) return null;
  const name = installerName(info.version, platform, arch);
  async function head(filename, limit) {
    if (!filename) return null;
    const url = `${REPOSITORY}/releases/download/${tag}/${filename}`;
    const response = await fetch(url, options);
    const size = Number(response.headers.get('content-length'));
    return response.ok && Number.isSafeInteger(size) && size > 0 && size <= limit ? { name: filename, url, size } : null;
  }
  [info.asset, info.checksum] = await Promise.all([head(name, MAX_INSTALLER_BYTES), head('SHA256SUMS.txt', 128 * 1024)]);
  return info;
}
async function responseText(fetch, url, signal, limit = 512 * 1024) {
  const response = await fetch(url, {
    signal, credentials: 'omit', headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'TeXGlot-Updates' },
  });
  if (!response.ok) throw new Error([403, 429].includes(response.status) ? 'rate-limit' : 'network');
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error('invalid-release');
      chunks.push(Buffer.from(value));
    }
    return Buffer.concat(chunks).toString('utf8');
  } finally { await reader.cancel().catch(() => {}); }
}
async function sha256(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

class UpdateManager {
  constructor({ version, platform, arch, directory, fetch, download, install, onChange = () => {} }) {
    Object.assign(this, { directory, fetch, downloadFile: download, openInstaller: install, onChange });
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    this.preferencePath = path.join(directory, 'preferences.json');
    this.readyPath = path.join(directory, 'downloaded.json');
    let autoCheck = true;
    try { autoCheck = JSON.parse(fs.readFileSync(this.preferencePath, 'utf8')).autoCheck !== false; } catch {}
    this.state = { revision: 0, status: 'idle', currentVersion: version, platform, arch, autoCheck };
    this.lastCheck = 0;
    this.release = null;
    this.readyFile = null;
    this.operation = null;
    this.controller = null;
  }
  snapshot() { return { ...this.state }; }
  change(values) { this.state = { ...this.state, ...values, revision: this.state.revision + 1 }; this.onChange(this.snapshot()); return this.snapshot(); }
  setAutoCheck(value) {
    if (typeof value !== 'boolean') throw new Error('invalid-action');
    const temporary = this.preferencePath + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify({ autoCheck: value }), { mode: 0o600 });
    fs.renameSync(temporary, this.preferencePath);
    return this.change({ autoCheck: value });
  }
  async expectedDigest(release, signal) {
    const direct = /^sha256:([a-f0-9]{64})$/.exec(release.asset.digest || '')?.[1];
    if (direct) return direct;
    const text = await responseText(this.fetch, release.checksum.url, signal, 128 * 1024);
    const matches = text.split(/\r?\n/).map(line => /^([a-f0-9]{64}) [ *](.+)$/.exec(line))
      .filter(match => match && match[2] === release.asset.name);
    if (matches.length !== 1) throw new Error('checksum');
    return matches[0][1];
  }
  savedDownload() {
    try {
      const saved = JSON.parse(fs.readFileSync(this.readyPath, 'utf8'));
      if (/^download-[A-Za-z0-9]+$/.test(saved.folder) && typeof saved.name === 'string' &&
          /^TeXGlot-[\d.]+-(?:macOS-(?:arm64|x64)\.dmg|Windows-x64-Setup\.exe)$/.test(saved.name)) return saved;
    } catch {}
    return null;
  }
  async restoreDownload() {
    const saved = this.savedDownload(), asset = this.release?.asset;
    if (!saved || !asset || saved.name !== asset.name || saved.size !== asset.size) return false;
    try {
      const file = path.join(this.directory, saved.folder, saved.name);
      const expected = await this.expectedDigest(this.release, AbortSignal.timeout(15000));
      if ((await fsp.stat(file)).size !== asset.size || await sha256(file) !== expected) return false;
      this.readyFile = { path: file, size: asset.size, digest: expected };
      return true;
    } catch { return false; }
  }
  check(manual = false) {
    if (this.operation) return this.operation;
    if (['ready', 'opening'].includes(this.state.status)) return Promise.resolve(this.snapshot());
    if (!manual && (!this.state.autoCheck || Date.now() - this.lastCheck < CHECK_INTERVAL)) return Promise.resolve(this.snapshot());
    this.lastCheck = Date.now();
    this.change({ status: 'checking', error: undefined });
    this.operation = (async () => {
      try {
        try {
          const raw = await responseText(this.fetch, LATEST, AbortSignal.timeout(15000));
          this.release = releaseInfo(JSON.parse(raw), this.state.currentVersion, this.state.platform, this.state.arch);
        } catch (error) {
          if (error.message !== 'rate-limit') throw error;
          this.release = await releaseRedirect(this.fetch, this.state.currentVersion, this.state.platform, this.state.arch);
        }
        this.change(this.release ? {
          status: 'available', version: this.release.version, url: this.release.url,
          canDownload: !!this.release.asset && (!!this.release.checksum || /^sha256:[a-f0-9]{64}$/.test(this.release.asset.digest || '')),
        } : { status: 'current', version: undefined, url: undefined, canDownload: false });
        if (this.release && await this.restoreDownload()) this.change({ status: 'ready', progress: 100 });
        if (!this.release) {
          const saved = this.savedDownload();
          if (saved) await fsp.rm(path.join(this.directory, saved.folder), { recursive: true, force: true }).catch(() => {});
          await fsp.rm(this.readyPath, { force: true }).catch(() => {});
        }
      } catch (error) { this.change({ status: 'error', error: error.message === 'rate-limit' ? 'rate-limit' : 'check-failed' }); }
      return this.snapshot();
    })().finally(() => { this.operation = null; });
    return this.operation;
  }
  download() {
    if (this.operation) return this.operation;
    if (!this.release?.asset || !this.state.canDownload || this.state.status !== 'available') return Promise.resolve(this.snapshot());
    const release = this.release, asset = release.asset;
    const controller = new AbortController();
    this.controller = controller;
    this.change({ status: 'downloading', progress: 0, error: undefined });
    this.operation = (async () => {
      let folder;
      try {
        const expected = await this.expectedDigest(release, AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]));
        controller.signal.throwIfAborted();
        folder = await fsp.mkdtemp(path.join(this.directory, 'download-'));
        const file = path.join(folder, asset.name);
        await this.downloadFile(asset.url, file, asset.size, progress => {
          if (!controller.signal.aborted) this.change({ progress: Math.min(99, Math.max(0, Math.floor(progress))) });
        }, controller.signal);
        controller.signal.throwIfAborted();
        if ((await fsp.stat(file)).size !== asset.size || await sha256(file) !== expected) throw new Error('checksum');
        controller.signal.throwIfAborted();
        this.readyFile = { path: file, size: asset.size, digest: expected };
        const previous = this.savedDownload();
        await fsp.writeFile(this.readyPath + '.tmp', JSON.stringify({ folder: path.basename(folder), name: asset.name, size: asset.size }), { mode: 0o600 });
        await fsp.rename(this.readyPath + '.tmp', this.readyPath);
        if (previous && previous.folder !== path.basename(folder)) await fsp.rm(path.join(this.directory, previous.folder), { recursive: true, force: true }).catch(() => {});
        controller.signal.throwIfAborted();
        this.change({ status: 'ready', progress: 100 });
      } catch (error) {
        if (folder) {
          this.readyFile = null;
          if (this.savedDownload()?.folder === path.basename(folder)) await fsp.rm(this.readyPath, { force: true }).catch(() => {});
          await fsp.rm(folder, { recursive: true, force: true }).catch(() => {});
        }
        this.change({ status: 'available', progress: 0, error: controller.signal.aborted ? undefined : error.message === 'checksum' ? 'checksum' : 'download-failed' });
      }
      return this.snapshot();
    })().finally(() => { this.operation = null; this.controller = null; });
    return this.operation;
  }
  cancel() { this.controller?.abort(); return this.operation || Promise.resolve(this.snapshot()); }
  async install() {
    if (this.operation || this.state.status !== 'ready' || !this.readyFile) return this.snapshot();
    this.change({ status: 'opening', error: undefined });
    try {
      // Recheck after an arbitrarily long pause before the user chooses Install.
      let valid = false;
      try { valid = (await fsp.stat(this.readyFile.path)).size === this.readyFile.size &&
          await sha256(this.readyFile.path) === this.readyFile.digest; } catch {}
      if (!valid) throw new Error('checksum');
      await this.openInstaller(this.readyFile.path);
    } catch (error) {
      if (error.message === 'checksum') {
        await fsp.rm(path.dirname(this.readyFile.path), { recursive: true, force: true }).catch(() => {});
        this.readyFile = null;
      }
      this.change({ status: this.readyFile ? 'ready' : 'available', error: ['jobs-active', 'service-unavailable', 'checksum'].includes(error.message) ? error.message : 'install-failed' });
    }
    return this.snapshot();
  }
}

// A dedicated Chromium download session preserves the normal OS download flow.
// No shell commands, quarantine removal or system security changes are used.
function nativeDownloader(session) {
  // Keep a single guard even after cancellation: a delayed response must never
  // become an unhandled download dialog, or be mistaken for the next request.
  let pending;
  session.on('will-download', (event, item) => {
    if (!pending || !item.getURLChain().includes(pending.url)) { event.preventDefault(); return; }
    const accept = pending.accept;
    pending = null;
    accept(event, item);
  });
  return (url, file, size, progress, signal) => new Promise((resolve, reject) => {
    const requestURL = new URL(url);
    requestURL.searchParams.set('texglot_download', crypto.randomUUID());
    let item, settled = false;
    const timer = setTimeout(() => finish(new Error('download-timeout')), 30 * 60 * 1000);
    const abort = () => finish(new Error('cancelled'));
    const finish = error => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      if (pending?.accept === started) pending = null;
      if (error) { item?.cancel(); reject(error); } else resolve();
    };
    const started = (event, download) => {
      if (signal.aborted) { event.preventDefault(); finish(new Error('cancelled')); return; }
      item = download;
      item.setSavePath(file);
      item.on('updated', () => {
        const bytes = item.getReceivedBytes();
        if (bytes > size) finish(new Error('size-limit'));
        else progress(bytes / size * 100);
      });
      item.once('done', (_event, state) => finish(state === 'completed' ? null : new Error('download-failed')));
    };
    if (signal.aborted) { finish(new Error('cancelled')); return; }
    signal.addEventListener('abort', abort, { once: true });
    pending = { url: requestURL.href, accept: started };
    try { session.downloadURL(requestURL.href); } catch (error) { finish(error); }
  });
}

function nativeFetch(net, url, options) {
  if (options.redirect !== 'manual') return net.fetch(url, options);
  // net.fetch cancels manual redirects instead of returning a fetch Response.
  // Capture the native redirect event while retaining system proxy/TLS behavior.
  return new Promise((resolve, reject) => {
    const request = net.request({ url, method: 'HEAD', redirect: 'manual', credentials: 'omit' });
    let settled = false;
    const finish = (response, error) => {
      if (settled) return;
      settled = true;
      options.signal?.removeEventListener('abort', abort);
      request.abort();
      if (error) reject(error); else resolve(response);
    };
    const abort = () => finish(null, new Error('request-aborted'));
    request.on('error', error => finish(null, error));
    request.on('redirect', (status, _method, location) => finish(new Response(null, { status, headers: { location } })));
    request.on('response', response => {
      response.on('error', error => finish(null, error));
      const headers = new Headers();
      for (const [key, value] of Object.entries(response.headers)) headers.set(key, Array.isArray(value) ? value.join(', ') : value);
      const result = new Response(null, { status: response.statusCode, headers });
      Object.defineProperty(result, 'url', { value: url });
      finish(result);
    });
    if (options.signal?.aborted) { abort(); return; }
    options.signal?.addEventListener('abort', abort, { once: true });
    request.end();
  });
}

module.exports = { UpdateManager, nativeDownloader, nativeFetch, newer, releaseInfo, responseText };
