const test = require("node:test");
const assert = require("node:assert/strict");
const {
  parseHeaderDraft,
  headerDraftForAddress,
  settingsPayload,
} = require("../../tmp/reader-tests/requestHeaders.js");

test("headers parse strings, normalize names, preserve empty values and prototype-like names", () => {
  const parsed = parseHeaderDraft(
    '{"X-Org-ID":"org-A","__proto__":"literal","x-empty":""}',
  );
  assert.equal(parsed.error, undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(parsed.headers)), {
    "x-org-id": "org-A",
    ["__proto__"]: "literal",
    "x-empty": "",
  });
});

test("invalid JSON and header values produce actionable errors without quoting input", () => {
  const cases = [
    "{private-value",
    "null",
    "[]",
    '"string"',
    '{"x-org-id":1}',
    '{"x-org-id":true}',
    '{"x-org-id":null}',
    JSON.stringify({ " x-org-id": "value" }),
    JSON.stringify({ "x\n": "value" }),
    JSON.stringify({ "x:org": "value" }),
    JSON.stringify({ "x-org-id": "one\r\nHost: evil" }),
    JSON.stringify({ "x-org-id": "one\x00two" }),
    JSON.stringify({ "x-org-id": "one\ttwo" }),
    JSON.stringify({ "x-org-id": "组织" }),
    '{"x-org-id":"one","X-Org-Id":"two"}',
  ];
  for (const value of cases) {
    const { error } = parseHeaderDraft(value);
    assert.ok(error, value);
    assert.ok(!error.includes("private-value"));
  }
  for (const name of [
    "Authorization",
    "HOST",
    "content-length",
    "Content-Type",
    "Content-Encoding",
    "Accept-Encoding",
    "Connection",
    "Keep-Alive",
    "Proxy-Authorization",
    "Proxy-Connection",
    "TE",
    "Trailer",
    "Transfer-Encoding",
    "Upgrade",
    "Expect",
  ])
    assert.ok(
      parseHeaderDraft(JSON.stringify({ [name]: "value" })).error,
      name,
    );
});

test("both count, per-value and aggregate limits are enforced at their boundaries", () => {
  const headers = Object.fromEntries(
    Array.from({ length: 16 }, (_, i) => [`x-${i}`, ""]),
  );
  assert.ok(!parseHeaderDraft(JSON.stringify(headers)).error);
  assert.ok(parseHeaderDraft(JSON.stringify({ ...headers, "x-16": "" })).error);
  assert.ok(!parseHeaderDraft(JSON.stringify({ x: "a".repeat(4096) })).error);
  assert.ok(parseHeaderDraft(JSON.stringify({ x: "a".repeat(4097) })).error);
  assert.ok(
    !parseHeaderDraft(JSON.stringify({ ["x".repeat(128)]: "a" })).error,
  );
  assert.ok(parseHeaderDraft(JSON.stringify({ ["x".repeat(129)]: "a" })).error);
  const full = Object.fromEntries(
    Array.from({ length: 4 }, (_, i) => [`x-${i}`, "a".repeat(4089)]),
  );
  assert.ok(!parseHeaderDraft(JSON.stringify(full)).error);
  full["x-0"] += "a";
  assert.ok(parseHeaderDraft(JSON.stringify(full)).error);
});

test("keep, replace, clear and address changes have distinct request semantics", () => {
  const form = {
    base_url: "https://gateway.example/team-a/v1",
    extra_header_names: ["x-org-id"],
  };
  assert.equal(
    Object.hasOwn(settingsPayload(form, null), "extra_headers"),
    false,
  );
  assert.equal(
    Object.hasOwn(settingsPayload(form, null), "extra_header_names"),
    false,
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(settingsPayload(form, ""))).extra_headers,
    {},
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(settingsPayload(form, "{}"))).extra_headers,
    {},
  );
  assert.equal(
    settingsPayload(form, '{"X-Org-ID":"org-B"}').extra_headers["x-org-id"],
    "org-B",
  );
  assert.throws(() => settingsPayload(form, '{"bad":null}'));
  const draft = '{"x-org-id":"org-A"}';
  assert.equal(
    headerDraftForAddress(
      form.base_url,
      form.base_url + "/chat/completions/",
      draft,
    ),
    draft,
  );
  assert.equal(
    headerDraftForAddress(
      form.base_url,
      "https://gateway.example/team-b/v1",
      draft,
    ),
    "",
  );
  assert.equal(
    headerDraftForAddress(form.base_url, "https://other.example/v1", null),
    "",
  );
  assert.deepEqual(
    JSON.parse(
      JSON.stringify(
        settingsPayload(
          { base_url: "https://api.deepl.com" },
          "invalid hidden draft",
        ),
      ),
    ).extra_headers,
    {},
  );
  assert.deepEqual(form.extra_header_names, ["x-org-id"]);
});

test("pasted header values normalize outer spaces without changing internal content", () => {
  const value = parseHeaderDraft(
    JSON.stringify({
      "x-org-id": " org-A ",
      "x-note": "two words",
      "x-quoted": '\" keep spaces \"',
    }),
  );
  assert.equal(value.headers["x-org-id"], "org-A");
  assert.equal(value.headers["x-note"], "two words");
  assert.equal(value.headers["x-quoted"], '\" keep spaces \"');
});
