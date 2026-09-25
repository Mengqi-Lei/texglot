import assert from "node:assert/strict";
import test from "node:test";
import { completeSourceSelection, pdfArxivVersion, resolveLocalSource } from "../src/source-resolution.js";
import { createPdfSourceReader } from "../src/pdf-source.js";
import { defaultComparisonForParent, translateItems } from "../src/menus.js";
import type { ZoteroLikeItem, ZoteroRuntime } from "../src/types.js";
import type { TeXGlotBridge } from "../src/bridge.js";

function fixture() {
  const files = new Map<number, { text: string; fingerprint: string; readable: boolean }>();
  const parent: ZoteroLikeItem = { id: 8001, key: "PAPER", libraryID: 1, getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.12345" : "", getAttachments: () => [8002] };
  const original: ZoteroLikeItem = { id: 8002, key: "ORIGINAL", libraryID: 1, parentItemID: 8001,
    isAttachment: () => true, isFileAttachment: () => true, attachmentContentType: "application/pdf",
    getField: (field) => field === "title" ? "Original PDF" : "", fileExists: async () => true };
  files.set(8002, { text: "arXiv:2401.12345v3 [cs.CL] 1 Jan 2024", fingerprint: "file-A", readable: true });
  const entries = new Map<number, ZoteroLikeItem>([[8001, parent], [8002, original]]);
  const runtime: ZoteroRuntime = { resolveItem: (id) => entries.get(id), readPdfInfo: async (item) => files.get(item.id!)! };
  return { files, entries, parent, original, runtime };
}

test("a normal versionless Zotero item resolves from its PDF without a prompt or service", async () => {
  const h = fixture();
  h.runtime.confirmOfficialSource = async () => { throw new Error("unexpected prompt"); };
  const selection = await resolveLocalSource(h.parent, h.runtime);
  assert.deepEqual(selection?.source, { type: "arxiv", id: "2401.12345v3" });
  assert.equal(selection?.attachment, h.original);
  assert.equal(selection?.sourceFingerprint, "file-A");
  assert.equal(selection?.sourceEvidence, "pdf");
  await completeSourceSelection(selection!, h.runtime, async () => { throw new Error("unexpected network"); });
});

test("page-one citations are not mistaken for a stamp and old identifiers stay supported", () => {
  assert.equal(pdfArxivVersion("See arXiv:2501.11111v2 in the references.", "2401.12345"), undefined);
  assert.equal(pdfArxivVersion("See arXiv:2501.11111v2.\narXiv:2401.12345\nv3 [cs.CL] 1 Jan 2024", "2401.12345"), "2401.12345v3");
  assert.equal(pdfArxivVersion("arXiv:hep-th/9901001v2 [hep-th] 1 Jan 1999"), "hep-th/9901001v2");
  assert.equal(pdfArxivVersion("arXiv:2401. 12345 v 3 [cs.CL]"), "2401.12345v3");
  assert.throws(() => pdfArxivVersion("arXiv:2501.11111v2 [cs.CL]", "2401.12345"), /编号/);
});

test("PDF evidence wins over stale versions and filenames supply missing attachment metadata", async () => {
  const h = fixture();
  h.original.getField = (field) => field === "url" ? "https://arxiv.org/pdf/2401.12345v1" : "";
  assert.equal((await resolveLocalSource(h.original, h.runtime))?.sourceEvidence, "pdf");
  h.files.get(8002)!.text = "";
  h.original.getField = () => "";
  h.original.attachmentFilename = "2401.12345v2.pdf";
  assert.deepEqual((await resolveLocalSource(h.original, h.runtime))?.source, { type: "arxiv", id: "2401.12345v2" });
});

test("a separate Zotero version field can be used with a verified base ID", async () => {
  const h = fixture();
  h.parent.getAttachments = () => [];
  h.parent.getField = (field) => field === "extra" ? "arXiv:2401.12345\nversion: 3" : "";
  const source = await resolveLocalSource(h.parent, h.runtime);
  assert.deepEqual(source?.source, { type: "arxiv", id: "2401.12345v3" });
  assert.equal(source?.useTaskOriginal, true);
});

test("ambiguous PDFs offer a file choice and cancellation is not an error", async () => {
  const h = fixture();
  const second = { ...h.original, id: 8003, key: "OTHER" };
  h.entries.set(8003, second); h.files.set(8003, { text: "", fingerprint: "other", readable: true });
  h.parent.getAttachments = () => [8002, 8003];
  let choices = 0;
  h.runtime.chooseAttachment = async (items) => { choices++; assert.equal(items.length, 2); return undefined; };
  assert.equal(await resolveLocalSource(h.parent, h.runtime), undefined);
  assert.equal(choices, 1);
  h.runtime.chooseAttachment = async () => h.original;
  assert.equal((await resolveLocalSource(h.parent, h.runtime))?.attachment, h.original);
});

test("unknown local version requires consent and never relabels the old PDF", async () => {
  const h = fixture(); h.files.get(8002)!.text = "";
  let prompts = 0;
  h.runtime.confirmOfficialSource = async (id) => { prompts++; assert.equal(id, "2401.12345v4"); return "official"; };
  const raw = await resolveLocalSource(h.parent, h.runtime);
  const completed = await completeSourceSelection(raw!, h.runtime, async () => ({ id: "2401.12345v4" }));
  assert.equal(completed?.attachment, undefined);
  assert.equal(completed?.useTaskOriginal, true);
  assert.equal(completed?.sourceEvidence, "official");
  assert.equal(prompts, 1);
  assert.equal(h.original.getField?.("url"), "");
  h.runtime.confirmOfficialSource = async () => "cancel";
  assert.equal(await completeSourceSelection(raw!, h.runtime, async () => ({ id: "2401.12345v4" })), undefined);
  await assert.rejects(completeSourceSelection(raw!, h.runtime, async () => ({ id: "2501.11111v2" })), /不一致/);
});

test("official pairing remains the default next time while the old unknown PDF is kept", async () => {
  const h = fixture(); h.files.get(8002)!.text = "";
  h.runtime.confirmOfficialSource = async () => "official";
  h.runtime.hashBytes = async () => "official-fingerprint";
  h.runtime.findAttachment = (parent, note) => {
    const expected = JSON.parse(note);
    return [...h.entries.values()].find((item) => { try { const actual = JSON.parse(item.getNote?.() || ""); return actual.artifact === expected.artifact && actual.task_id === expected.task_id; } catch { return false; } });
  };
  let nextID = 8003;
  h.runtime.importAttachment = async (_bytes, options) => {
    const item = { ...h.original, id: nextID++, key: `IMPORTED${nextID}`, getField: () => options.title, getNote: () => options.note };
    h.entries.set(item.id, item);
    h.files.set(item.id, { text: "", fingerprint: "official-fingerprint", readable: true });
    h.parent.getAttachments = () => [8002, ...[...h.entries.keys()].filter((id) => id >= 8003)];
    return item;
  };
  const opened: number[][] = [];
  h.runtime.openSplitReader = async (left, right) => { opened.push([left.id!, right.id!]); };
  const downloads: string[] = [];
  const bridge = {
    resolveArxiv: async () => ({ id: "2401.12345v4" }),
    health: async () => ({ capabilities: { arxivLatex: true } }),
    createJob: async () => ({ id: "library-job", status: "completed", reuse: "library" }),
    artifact: async (_id: string, kind: string) => { downloads.push(kind); return new TextEncoder().encode("%PDF-1.7"); },
  } as unknown as TeXGlotBridge;
  await translateItems([h.parent], h.runtime, bridge);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(downloads, ["original", "translated"]);
  assert.deepEqual(opened, [[8003, 8004]]);
  const pair = await defaultComparisonForParent(h.parent, h.runtime);
  assert.equal(pair?.original.id, 8003);
  assert.equal(pair?.translated.id, 8004);
  await translateItems([h.parent], h.runtime, {} as TeXGlotBridge);
  assert.deepEqual(opened, [[8003, 8004], [8003, 8004]]);
  assert.equal(h.original.key, "ORIGINAL");
  assert.ok(h.entries.has(8002));
});

test("file replacement invalidates a saved relationship instead of guessing its new version", async () => {
  const h = fixture(); h.files.get(8002)!.text = "";
  const translated = { ...h.original, id: 8003, key: "TRANSLATED", getNote: () => JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v3", language: "简体中文", source_attachment_key: "ORIGINAL", source_fingerprint: "file-A" }) };
  h.entries.set(8003, translated); h.parent.getAttachments = () => [8002, 8003];
  assert.equal((await defaultComparisonForParent(h.parent, h.runtime))?.original.id, 8002);
  h.files.get(8002)!.fingerprint = "file-B";
  assert.equal(await defaultComparisonForParent(h.parent, h.runtime), undefined);
});

test("cancelled source selection creates no tasks and releases the repeat-click lock", async () => {
  const h = fixture(); h.files.get(8002)!.text = "";
  let prompts = 0;
  h.runtime.confirmOfficialSource = async () => { prompts++; return "cancel"; };
  const bridge = { resolveArxiv: async () => ({ id: "2401.12345v3" }), health: async () => { throw new Error("must not submit"); } } as unknown as TeXGlotBridge;
  assert.deepEqual(await translateItems([h.parent], h.runtime, bridge), []);
  assert.deepEqual(await translateItems([h.parent], h.runtime, bridge), []);
  assert.equal(prompts, 2);
});

test("PDF extraction is cached, concurrent reads coalesce and replacements are inspected again", async () => {
  let calls = 0, revision = 1;
  const reader = createPdfSourceReader({
    stat: async () => ({ size: 100, lastModified: revision }),
    read: async () => new TextEncoder().encode("%PDF-1.7"), hash: async () => `hash${revision}`,
    extract: async () => { calls++; return { text: `arXiv:2401.12345v${revision} [cs.CL]` }; },
  });
  const item = { id: 1, getFilePath: () => "/test.pdf" };
  const results = await Promise.all([reader.read(item), reader.read(item), reader.read(item)]);
  assert.equal(calls, 1); assert.equal(results[0].fingerprint, "hash1");
  revision++;
  assert.equal((await reader.read(item)).fingerprint, "hash2"); assert.equal(calls, 2);
  reader.clear();
  await reader.read(item); assert.equal(calls, 3);
});

test("PDF timeout and extraction failures stay recoverable for all concurrent callers", async () => {
  let fail = true;
  const reader = createPdfSourceReader({
    stat: async () => ({ size: 100, lastModified: 1 }), read: async () => new TextEncoder().encode("%PDF-1.7"), hash: async () => "hash", timeoutMs: 5,
    extract: async () => { if (fail) return new Promise(() => {}); return { text: "restored" }; },
  });
  const item = { id: 1, getFilePath: () => "/test.pdf" };
  const results = await Promise.all([reader.read(item), reader.read(item)]);
  assert.ok(results.every((result) => result.readable === false));
  fail = false;
  assert.equal((await reader.read(item)).text, "restored");
});
