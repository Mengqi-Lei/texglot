const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const os = require('node:os');
const { matchingService, requestJSON, startService } = require('../service.cjs');

test('a desktop window only reuses a service owning its data directory', () => {
  const dataDir = path.join(os.tmpdir(), 'texglot-library');
  assert.equal(matchingService({ ok: true, name: 'TeXGlot', data_dir: dataDir }, dataDir), true);
  assert.equal(matchingService({ ok: true, name: 'TeXGlot', data_dir: dataDir + '-other' }, dataDir), false);
  assert.equal(matchingService({ ok: true, name: 'other', data_dir: dataDir }, dataDir), false);
  assert.equal(matchingService({}, dataDir), false);
});

test('service probing rejects non-JSON responses and returns health JSON', async () => {
  const server = http.createServer((req, res) => res.end(req.url === '/health' ? '{"ok":true}' : '<html>other service</html>'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const base = `http://127.0.0.1:${server.address().port}`;
    assert.deepEqual(await requestJSON(base + '/health'), { ok: true });
    await assert.rejects(requestJSON(base + '/'), /Invalid service response/);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

test('upgraded apps do not silently reuse an old engine for the same library', async () => {
  const fs = require('node:fs/promises');
  const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'texglot-service-version-'));
  const server = http.createServer((_req, res) => res.end(JSON.stringify({ ok: true, name: 'TeXGlot', data_dir: dataDir, version: '1.0.3' })));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const options = { executable: '/must-not-spawn', dataDir, preferredPort: server.address().port, expectedVersion: '1.0.4' };
  try {
    await assert.rejects(startService(options), /different-service-version/);
    const service = await startService({ ...options, expectedVersion: '1.0.3' });
    assert.equal(service.owned, false);
  } finally { await new Promise(resolve => server.close(resolve)); await fs.rm(dataDir, { recursive: true }); }
});
