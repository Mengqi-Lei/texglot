const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const activeStatuses = new Set(['queued', 'downloading', 'preparing', 'translating', 'compiling']);
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
async function deadline(promise, ms) {
  let timer;
  try { return await Promise.race([promise, new Promise(resolve => { timer = setTimeout(resolve, ms); })]); }
  finally { clearTimeout(timer); }
}

function canonicalPath(value, platform = process.platform) {
  let resolved;
  try { resolved = fs.realpathSync.native(value); } catch { resolved = path.resolve(value); }
  return platform === 'win32' ? resolved.toLowerCase() : resolved;
}

function requestJSON(url, timeout = 1200) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout, headers: { Accept: 'application/json' } }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => {
        body += chunk;
        if (body.length > 4 * 1024 * 1024) req.destroy(new Error('Response too large'));
      });
      response.on('end', () => {
        if (response.statusCode !== 200) return reject(new Error(`HTTP ${response.statusCode}`));
        try { resolve(JSON.parse(body)); } catch { reject(new Error('Invalid service response')); }
      });
      response.on('error', reject);
    });
    req.on('timeout', () => req.destroy(new Error('Service timeout')));
    req.on('error', reject);
  });
}

function matchingService(health, dataDir) {
  return health && health.ok === true && health.name === 'TeXGlot' &&
    typeof health.data_dir === 'string' && canonicalPath(health.data_dir) === canonicalPath(dataDir);
}

async function portAvailable(port) {
  const net = require('node:net');
  return new Promise(resolve => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)));
  });
}

async function startService({ executable, dataDir, preferredPort = 8765, logPath, onExit, expectedVersion }) {
  if (!Number.isInteger(preferredPort) || preferredPort < 1 || preferredPort > 65535) {
    throw new Error('Invalid TEXGLOT_PORT');
  }
  fs.mkdirSync(dataDir, { recursive: true, mode: 0o700 });
  let port;
  for (let candidate = preferredPort; candidate <= Math.min(preferredPort + 20, 65535); candidate++) {
    const url = `http://127.0.0.1:${candidate}`;
    const health = await requestJSON(`${url}/api/health`).catch(() => null);
    if (matchingService(health, dataDir)) {
      if (expectedVersion && health.version !== expectedVersion) throw new Error('different-service-version');
      return { url, owned: false, close: async () => {} };
    }
    if (port === undefined && await portAvailable(candidate)) port = candidate;
  }
  if (!port) throw new Error('No local port is available');
  const url = `http://127.0.0.1:${port}`;
  const log = fs.openSync(logPath, 'a', 0o600);
  const child = spawn(executable, ['--engine-server', '--port', String(port), '--parent-pipe'], {
    cwd: dataDir,
    env: { ...process.env, TEXGLOT_DATA_DIR: dataDir, TEXGLOT_PORT: String(port), PYTHONUTF8: '1' },
    windowsHide: true,
    stdio: ['pipe', log, log],
  });
  fs.closeSync(log);
  let exited = false, spawnError, closing = false;
  const stopped = new Promise(resolve => child.once('close', () => { exited = true; resolve(); }));
  child.on('error', error => { spawnError = error; });
  child.stdin.on('error', () => {});
  async function close() {
    closing = true;
    if (exited || !child.pid) return;
    child.stdin.end(); // EOF requests graceful shutdown, including compiler cleanup.
    await deadline(stopped, 15000);
    if (!exited) {
      if (process.platform === 'win32') {
        const killer = spawn(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'taskkill.exe'),
          ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
        await deadline(once(killer, 'exit').catch(() => {}), 5000);
      } else { child.kill('SIGKILL'); }
      await deadline(stopped, 2000);
    }
  }
  try {
    for (let i = 0; i < 150; i++) {
      if (spawnError) throw spawnError;
      const health = await requestJSON(`${url}/api/health`).catch(() => null);
      if (matchingService(health, dataDir)) {
        if (expectedVersion && health.version !== expectedVersion) throw new Error('different-service-version');
        child.on('exit', (code, signal) => { if (!closing) onExit?.(code, signal); });
        return { url, owned: true, child, close };
      }
      if (exited) throw new Error(`The translation service stopped. See ${logPath}`);
      await delay(200);
    }
    throw new Error(`The translation service did not start. See ${logPath}`);
  } catch (error) { await close(); throw error; }
}

module.exports = { startService, matchingService, canonicalPath, requestJSON, activeStatuses };
