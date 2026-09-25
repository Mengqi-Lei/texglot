const { test } = require("node:test");
const assert = require("node:assert/strict");
const { parseJobDeepLink, resolveJobDeepLink } = require("../../tmp/reader-tests/jobDeepLink.js");

test("TeXGlot task links select details and reader links request the reader", () => {
  assert.deepEqual(parseJobDeepLink("?job=abcdef0123456789"), {
    id: "abcdef0123456789", view: "details",
  });
  assert.deepEqual(parseJobDeepLink("?reader=abcdef0123456789&mode=comparison"), {
    id: "abcdef0123456789", view: "reader",
  });
  assert.deepEqual(parseJobDeepLink("?job=abcdef0123456789&view=reader"), {
    id: "abcdef0123456789", view: "reader",
  });
  assert.equal(parseJobDeepLink("?job="), null);
  assert.equal(parseJobDeepLink("?job=../../other"), null);
});

test("reader links fall back to task details until a translated PDF exists", () => {
  const queued = { id: "task-queued", artifacts: { translated: false } };
  const completed = { id: "task-complete", artifacts: { translated: true } };
  const jobs = [queued, completed];
  assert.deepEqual(resolveJobDeepLink(jobs, { id: queued.id, view: "reader" }), {
    kind: "details", job: queued,
  });
  assert.deepEqual(resolveJobDeepLink(jobs, { id: completed.id, view: "reader" }), {
    kind: "reader", job: completed,
  });
  assert.deepEqual(resolveJobDeepLink(jobs, { id: completed.id, view: "details" }), {
    kind: "details", job: completed,
  });
  assert.deepEqual(resolveJobDeepLink(jobs, { id: "unknown", view: "details" }), {
    kind: "missing",
  });
});
