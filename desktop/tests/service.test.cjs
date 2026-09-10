const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const os = require('node:os');
const { matchingService, requestJSON } = require('../service.cjs');

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
