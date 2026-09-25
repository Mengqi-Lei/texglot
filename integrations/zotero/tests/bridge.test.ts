import assert from "node:assert/strict";
import test from "node:test";
import { TeXGlotBridge } from "../src/bridge.js";
import { TeXGlotIntegrationError } from "../src/errors.js";

function response(body: unknown, status = 200, headers: Record<string, string> = { "content-type": "application/json" }) {
  const payload = body instanceof Uint8Array ? body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength) : JSON.stringify(body);
  return new Response(payload as BodyInit, { status, headers });
}

test("both reuse and explicit retranslation require a core with library lookup", async () => {
  const bodies: any[] = [];
  let supported = false;
  const bridge = new TeXGlotBridge({ fetch: async (_url, init) => {
    if (init?.method !== "POST") return response({ ok: true, name: "TeXGlot", capabilities: { library_reuse: supported } });
    bodies.push(JSON.parse(String(init.body)));
    return response({ id: "new-job", status: "queued" }, 202);
  } });
  const selection = { source: { type: "arxiv" as const, id: "2401.12345v2" }, parent: {}, warnings: [] };
  await assert.rejects(bridge.createJob(selection),
    (error: unknown) => error instanceof TeXGlotIntegrationError && error.code === "CORE_UPGRADE_REQUIRED");
  await assert.rejects(bridge.createJob(selection, { reuseExisting: false }),
    (error: unknown) => error instanceof TeXGlotIntegrationError && error.code === "CORE_UPGRADE_REQUIRED");
  assert.equal(bodies.length, 0, "an old core must never receive a task submission");
  supported = true;
  await bridge.createJob(selection);
  assert.equal("reuse_existing" in bodies[0], false);
  await bridge.createJob(selection, { reuseExisting: false });
  assert.equal(bodies[1].reuse_existing, false);
});

test("legacy health is readable but cannot silently fall back to a new translation", async () => {
  const paths: string[] = [];
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(url).pathname;
    paths.push(`${init?.method ?? "GET"} ${path}`);
    if (path === "/api/integrations/zotero/health") return response({ detail: "not found" }, 404);
    if (path === "/api/health") return response({ ok: true, name: "TeXGlot", version: "1.1.3" });
    if (path === "/api/integrations/zotero/jobs") return response({ detail: "not found" }, 404);
    return response({ id: "task-1", status: "queued" }, 202);
  };
  const bridge = new TeXGlotBridge({ fetch: fetcher });
  await assert.rejects(bridge.createJob({ source: { type: "arxiv", id: "2401.12345v2" }, parent: {}, warnings: [] }),
    (error: unknown) => error instanceof TeXGlotIntegrationError && error.code === "CORE_UPGRADE_REQUIRED");
  assert.deepEqual(paths, ["GET /api/integrations/zotero/health", "GET /api/health"]);
});

test("a missing integration endpoint never falls back to legacy POST even after a positive health check", async () => {
  const paths: string[] = [];
  const bridge = new TeXGlotBridge({ fetch: async (url, init) => {
    const path = new URL(String(url)).pathname;
    paths.push(`${init?.method ?? "GET"} ${path}`);
    if (path.endsWith("/health")) return response({ ok: true, name: "TeXGlot", capabilities: { library_reuse: true } });
    return response({ detail: "not found" }, 404);
  } });
  await assert.rejects(bridge.createJob({ source: { type: "arxiv", id: "2601.22054v1" }, parent: {}, warnings: [] }),
    (error: unknown) => error instanceof TeXGlotIntegrationError && error.code === "CORE_UPGRADE_REQUIRED");
  assert.deepEqual(paths, ["GET /api/integrations/zotero/health", "POST /api/integrations/zotero/jobs"]);
});

test("polls until a terminal status and downloads bytes", async () => {
  let count = 0;
  const fetcher = async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(url).pathname;
    if (path.includes("/integrations/zotero/jobs/")) return response({ detail: "not found" }, 404);
    if (path === "/api/jobs/task") return response({ id: "task", status: ++count === 1 ? "translating" : "completed" });
    if (path.endsWith("/artifacts/translated")) return response(new Uint8Array([37, 80, 68, 70, 45]), 200, { "content-type": "application/pdf" });
    return response({ ok: true, name: "TeXGlot" });
  };
  const bridge = new TeXGlotBridge({ fetch: fetcher, timeoutMs: 100 });
  const task = await bridge.pollJob("task", { intervalMs: 0, maxAttempts: 3 });
  assert.equal(task.status, "completed");
  assert.deepEqual([...await bridge.artifact("task", "translated")], [37, 80, 68, 70, 45]);
});

test("works in a Zotero host without a constructible AbortController", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "AbortController");
  Object.defineProperty(globalThis, "AbortController", { configurable: true, value: undefined });
  try {
    const bridge = new TeXGlotBridge({ fetch: async () => response({ ok: true, name: "TeXGlot" }), timeoutMs: 50 });
    assert.equal((await bridge.health()).name, "TeXGlot");
  } finally {
    if (previous) Object.defineProperty(globalThis, "AbortController", previous);
    else delete (globalThis as { AbortController?: unknown }).AbortController;
  }
});

test("a foreign service on 8765 cannot receive jobs; verified desktop service on 8766 is used throughout", async () => {
  const requests: Array<{ port: string; path: string; method: string }> = [];
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    requests.push({ port: url.port, path: url.pathname, method: init?.method ?? "GET" });
    if (url.port === "8765") return response({ ok: true, name: "Another App" });
    if (url.pathname.endsWith("/health")) return response({ ok: true, name: "TeXGlot", integration_api: "zotero.v1", capabilities: { library_reuse: true } });
    if (url.pathname.endsWith("/artifacts/translated")) {
      return response(new Uint8Array([37, 80, 68, 70, 45]), 200, { "content-type": "application/pdf" });
    }
    return response({ id: "desktop-job", status: "queued" }, 202);
  };
  const bridge = new TeXGlotBridge({ fetch: fetcher });
  const health = await bridge.health();
  assert.equal(health.name, "TeXGlot");
  assert.equal(bridge.baseUrl, "http://127.0.0.1:8766");
  const job = await bridge.createJob({ source: { type: "arxiv", id: "2401.12345v2" }, parent: {}, warnings: [] });
  assert.equal(job.id, "desktop-job");
  assert.deepEqual([...await bridge.artifact(job.id, "translated")], [37, 80, 68, 70, 45]);
  assert.equal(bridge.readerUrl(job.id).startsWith("http://127.0.0.1:8766/"), true);
  assert.deepEqual(requests.filter((request) => request.method === "POST").map((request) => request.port), ["8766"]);
  assert.deepEqual(requests.filter((request) => request.path.includes("/artifacts/")).map((request) => request.port), ["8766"]);
  assert.deepEqual([...new Set(requests.map((request) => request.port))], ["8765", "8766"]);
});

test("an unreachable 8765 falls back only to a verified 8766", async () => {
  const ports: string[] = [];
  const fetcher = async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    ports.push(url.port);
    if (url.port === "8765") throw new TypeError("connection refused");
    return response({ ok: true, name: "TeXGlot" });
  };
  const bridge = new TeXGlotBridge({ fetch: fetcher });
  assert.equal((await bridge.health()).name, "TeXGlot");
  assert.equal(bridge.baseUrl, "http://127.0.0.1:8766");
  assert.deepEqual(ports, ["8765", "8766"]);
});

test("neither default port can receive a job when both health probes fail", async () => {
  const requests: Array<{ port: string; method: string }> = [];
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    requests.push({ port: url.port, method: init?.method ?? "GET" });
    throw new TypeError("connection refused");
  };
  const bridge = new TeXGlotBridge({ fetch: fetcher });
  await assert.rejects(bridge.createJob({ source: { type: "arxiv", id: "2401.12345v2" }, parent: {}, warnings: [] }),
    (error: unknown) => error instanceof TeXGlotIntegrationError && error.code === "SERVICE_UNAVAILABLE");
  assert.deepEqual(requests.map((request) => request.port), ["8765", "8766"]);
  assert.equal(requests.some((request) => request.method === "POST"), false);
});

test("an explicit base URL is verified but never triggers automatic port discovery", async () => {
  const ports: string[] = [];
  const fetcher = async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    ports.push(url.port);
    return response({ ok: true, name: "Another App" });
  };
  const bridge = new TeXGlotBridge({ baseUrl: "http://127.0.0.1:9876/", fetch: fetcher });
  await assert.rejects(bridge.health(),
    (error: unknown) => error instanceof TeXGlotIntegrationError && error.code === "NOT_TEXGLOT_SERVICE");
  assert.deepEqual(ports, ["9876"]);
  assert.equal(bridge.baseUrl, "http://127.0.0.1:9876");
});

test("health rediscovers a verified desktop service that restarts on 8766", async () => {
  let runningPort = "8765";
  const requests: string[] = [];
  const fetcher = async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    requests.push(url.port + url.pathname);
    if (url.port !== runningPort) throw new TypeError("connection refused");
    return response({ ok: true, name: "TeXGlot" });
  };
  const bridge = new TeXGlotBridge({ fetch: fetcher });
  assert.equal((await bridge.health()).name, "TeXGlot");
  assert.equal(bridge.baseUrl, "http://127.0.0.1:8765");
  runningPort = "8766";
  assert.equal((await bridge.health()).name, "TeXGlot");
  assert.equal(bridge.baseUrl, "http://127.0.0.1:8766");
  assert.deepEqual(requests.map((request) => request.slice(0, 4)), ["8765", "8765", "8766"]);
});

test("health leaves a port taken over by another app and fixes subsequent reads to 8766", async () => {
  let replaced = false;
  const requests: Array<{ port: string; path: string }> = [];
  const fetcher = async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    requests.push({ port: url.port, path: url.pathname });
    if (url.pathname.endsWith("/health")) {
      return response({ ok: true, name: url.port === "8765" && replaced ? "Another App" : "TeXGlot" });
    }
    if (url.port === "8765" && replaced) return response({ detail: "not found" }, 404);
    return response({ id: "existing-job", status: "completed" });
  };
  const bridge = new TeXGlotBridge({ fetch: fetcher });
  await bridge.health();
  replaced = true;
  assert.equal((await bridge.health()).name, "TeXGlot");
  assert.equal(bridge.baseUrl, "http://127.0.0.1:8766");
  assert.equal((await bridge.getJob("existing-job")).status, "completed");
  assert.equal(requests.at(-1)?.port, "8766");
});

test("polling GET recovers once after a port switch without repeating a POST", async () => {
  let runningPort = "8765";
  const requests: Array<{ port: string; method: string; path: string }> = [];
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    requests.push({ port: url.port, method: init?.method ?? "GET", path: url.pathname });
    if (url.port !== runningPort) throw new TypeError("connection refused");
    if (url.pathname.endsWith("/health")) return response({ ok: true, name: "TeXGlot" });
    if (url.pathname.endsWith("/jobs/existing-job")) return response({ id: "existing-job", status: "completed" });
    return response({ id: "existing-job", status: "queued" }, 202);
  };
  const bridge = new TeXGlotBridge({ fetch: fetcher });
  await bridge.health();
  runningPort = "8766";
  assert.equal((await bridge.pollJob("existing-job", { maxAttempts: 1 })).status, "completed");
  assert.equal(bridge.baseUrl, "http://127.0.0.1:8766");
  assert.deepEqual(requests.filter((request) => request.path.endsWith("/jobs/existing-job")).map((request) => request.port), ["8765", "8766"]);
  assert.equal(requests.some((request) => request.method === "POST"), false);
});

test("an explicit base URL remains fixed after its verified service stops", async () => {
  let running = true;
  const ports: string[] = [];
  const fetcher = async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    ports.push(url.port);
    if (!running) throw new TypeError("connection refused");
    return response({ ok: true, name: "TeXGlot" });
  };
  const bridge = new TeXGlotBridge({ baseUrl: "http://127.0.0.1:8765", fetch: fetcher });
  await bridge.health();
  running = false;
  await assert.rejects(bridge.health(), (error: unknown) =>
    error instanceof TeXGlotIntegrationError && error.code === "SERVICE_UNAVAILABLE");
  assert.equal(bridge.baseUrl, "http://127.0.0.1:8765");
  assert.deepEqual(ports, ["8765", "8765"]);
});
