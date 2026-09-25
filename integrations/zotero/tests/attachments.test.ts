import assert from "node:assert/strict";
import test from "node:test";
import { importArtifact } from "../src/attachments.js";
import { TeXGlotBridge } from "../src/bridge.js";

function bridgeWithArtifact(bytes: Uint8Array): TeXGlotBridge {
  return new TeXGlotBridge({ fetch: async (input) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/integrations/zotero/health") {
      return new Response(JSON.stringify({ ok: true, name: "TeXGlot" }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    const body = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
    return new Response(body, { status: 200 });
  } });
}

test("imports a validated PDF through the Zotero runtime adapter", async () => {
  let called: unknown;
  const bridge = bridgeWithArtifact(new Uint8Array([37, 80, 68, 70, 45]));
  const result = await importArtifact(bridge, { id: "task-1", status: "completed" }, { source: { type: "arxiv", id: "2401.12345v2" }, parent: {}, warnings: [] }, {
    importAttachment: async (bytes, options) => { called = { bytes: [...bytes], options }; return { id: 2 }; },
  });
  assert.equal(result.imported, true);
  assert.deepEqual((called as { bytes: number[] }).bytes, [37, 80, 68, 70, 45]);
  assert.match((called as { options: { title: string } }).options.title, /2401\.12345v2/);
});

test("reuses an attachment with the same TeXGlot marker", async () => {
  let imported = false;
  const bridge = bridgeWithArtifact(new Uint8Array([37, 80, 68, 70, 45]));
  const result = await importArtifact(bridge, { id: "task-1", status: "completed" }, { source: { type: "arxiv", id: "2401.12345v2" }, parent: {}, warnings: [] }, {
    findAttachment: () => ({ id: 2 }),
    importAttachment: async () => { imported = true; return { id: 3 }; },
  });
  assert.equal(result.imported, false);
  assert.equal(imported, false);
});

test("does not treat arbitrary bytes as a PDF", async () => {
  const bridge = bridgeWithArtifact(new TextEncoder().encode("oops"));
  await assert.rejects(importArtifact(bridge, { id: "task-1", status: "completed" }, { source: { type: "arxiv", id: "2401.12345v2" }, parent: {}, warnings: [] }, { importAttachment: async () => undefined }), /有效 PDF/);
});
