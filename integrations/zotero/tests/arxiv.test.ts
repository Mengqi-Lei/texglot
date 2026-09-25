import assert from "node:assert/strict";
import test from "node:test";
import { hasUnversionedArxiv, parseVersionedArxiv, readLatexSource } from "../src/arxiv.js";
import { resolveLocalSource } from "../src/source-resolution.js";
import { TeXGlotIntegrationError } from "../src/errors.js";
import { defaultComparisonForParent, translateItems } from "../src/menus.js";
import { TeXGlotBridge } from "../src/bridge.js";
import type { JobOptions, ZoteroLikeItem, ZoteroRuntime } from "../src/types.js";

function item(fields: Record<string, unknown>, attachment = false) {
  return { id: 1, key: "ABCD", libraryID: 1, isAttachment: () => attachment, getField: (name: string) => fields[name], getAttachments: () => [] };
}

test("requires and normalizes a complete arXiv version", () => {
  assert.equal(parseVersionedArxiv("https://arxiv.org/abs/2401.12345v2"), "2401.12345v2");
  assert.equal(parseVersionedArxiv("arXiv:cs.AI/0701001v3"), "cs.AI/0701001v3");
  assert.equal(parseVersionedArxiv("https://arxiv.org/abs/2401.12345"), null);
  assert.equal(hasUnversionedArxiv("doi:10.48550/arXiv.2401.12345"), true);
});

test("resolves explicit metadata and leaves bare IDs for automatic official resolution", async () => {
  const selected = await resolveLocalSource(item({ url: "https://arxiv.org/abs/1706.03762v7" }), {});
  assert.deepEqual(selected?.source, { type: "arxiv", id: "1706.03762v7" });
  const bare = await resolveLocalSource(item({ url: "https://arxiv.org/abs/1706.03762" }), {});
  assert.deepEqual(bare?.source, { type: "arxiv", id: "1706.03762" });
  assert.equal(bare?.useTaskOriginal, true);
});

test("does not select a generated TeXGlot child as the original PDF", async () => {
  const parent: ZoteroLikeItem = item({ url: "https://arxiv.org/abs/2602.21186v2", title: "Spa3R" });
  const original: ZoteroLikeItem = { id: 2, isAttachment: () => true, getParentID: () => 1, getField: (name: string) => name === "title" ? "Preprint PDF" : "" };
  const translated: ZoteroLikeItem = {
    id: 3,
    isAttachment: () => true,
    getParentID: () => 1,
    getField: (name: string) => name === "title" ? "[TeXGlot] 简体中文 · arXiv 2602.21186v2" : "https://arxiv.org/abs/2602.21186v2",
    getNote: () => JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2602.21186v2" }),
  };
  const items = new Map<number, ZoteroLikeItem>([[1, parent], [2, original], [3, translated]]);
  parent.getAttachments = () => [2, 3];
  const fromParent = await resolveLocalSource(parent, { resolveItem: (id) => items.get(id) });
  assert.equal(fromParent?.attachment, undefined);
  assert.deepEqual(fromParent?.source, { type: "arxiv", id: "2602.21186v2" });
  const fromTranslated = await resolveLocalSource(translated, { resolveItem: (id) => items.get(id) });
  assert.equal(fromTranslated?.attachment, undefined);
  assert.deepEqual(fromTranslated?.source, { type: "arxiv", id: "2602.21186v2" });
});

test("extracts a selected LaTeX attachment without treating PDFs as source", async () => {
  const source = await readLatexSource({ isAttachment: () => true, getFilePath: () => "/tmp/paper.tex", getField: () => "" }, undefined, async () => new Uint8Array([65, 66]));
  assert.equal(source.source.type, "latex");
  assert.equal(source.source.filename, "paper.tex");
  assert.equal(source.source.contentBase64, "QUI=");
  await assert.rejects(readLatexSource({ isAttachment: () => true, getFilePath: () => "/tmp/paper.pdf", getField: () => "" }), /LaTeX 源码附件/);
});

test("encodes large LaTeX attachments as one valid base64 stream", async () => {
  const bytes = new Uint8Array(32769).fill(65);
  const source = await readLatexSource(
    { isAttachment: () => true, getFilePath: () => "/tmp/paper.tex", getField: () => "" },
    undefined,
    async () => bytes,
  );
  assert.equal(source.source.type, "latex");
  if (source.source.type !== "latex") return;
  assert.deepEqual(Buffer.from(source.source.contentBase64 ?? "", "base64"), Buffer.from(bytes));
  assert.equal(source.source.contentBase64, Buffer.from(bytes).toString("base64"));
});

test("selected LaTeX source overrides the parent's arXiv metadata", async () => {
  const parent: ZoteroLikeItem = { id: 1, getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.12345v2" : "" };
  const archive: ZoteroLikeItem = {
    id: 2, isAttachment: () => true, getParentID: () => 1,
    getFilePath: () => "/tmp/paper.zip", getField: () => "",
  };
  const result = await readLatexSource(archive, (id) => id === 1 ? parent : undefined, async () => new Uint8Array([1, 2, 3]));
  assert.equal(result.source.type, "latex");
});

test("a non-PDF source attachment is never used as the original reader pane", async () => {
  const parent: ZoteroLikeItem = { id: 1, getField: () => "", getAttachments: () => [2] };
  const archive: ZoteroLikeItem = {
    id: 2, isAttachment: () => true, isFileAttachment: () => true, attachmentContentType: "application/zip",
    getParentID: () => 1, getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.12345v2" : "",
  };
  const result = await resolveLocalSource(parent, { resolveItem: (id) => id === 2 ? archive : undefined });
  assert.equal(result?.attachment, undefined);
});

function pdf(id: number, title: string, url: string, note = ""): ZoteroLikeItem {
  return {
    id, isAttachment: () => true, isFileAttachment: () => true, attachmentContentType: "application/pdf",
    parentItemID: 1, getField: (field) => field === "title" ? title : field === "url" ? url : "",
    getNote: () => note,
  };
}

test("default comparison uses one matching TeXGlot result without guessing another version", async () => {
  const parent: ZoteroLikeItem = {
    id: 1, isRegularItem: () => true,
    getField: (field) => field === "url" ? "https://arxiv.org/abs/1706.03762v7" : "",
    getAttachments: () => [2, 3, 4],
  };
  const original = pdf(2, "Preprint PDF", "https://arxiv.org/pdf/1706.03762v7");
  let noteLoaded = false;
  const translated = {
    ...pdf(3, "[TeXGlot] 简体中文", ""),
    loadDataType: async (type: string) => { if (type === "note") noteLoaded = true; },
    getNote: () => {
      if (!noteLoaded) throw new Error("note not loaded");
      return JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "1706.03762v7", language: "简体中文" });
    },
  };
  const otherVersion = pdf(4, "Preprint v6", "https://arxiv.org/pdf/1706.03762v6");
  const items = new Map<number, ZoteroLikeItem>([[2, original], [3, translated], [4, otherVersion]]);
  const runtime: ZoteroRuntime = { resolveItem: (id) => items.get(id), resolveItemAsync: async (id) => items.get(id) };
  assert.deepEqual(await defaultComparisonForParent(parent, runtime), { original, translated });

  const secondTranslation = pdf(5, "[TeXGlot] English", "", JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "1706.03762v7", language: "English" }));
  items.set(5, secondTranslation);
  parent.getAttachments = () => [2, 3, 5];
  assert.equal(await defaultComparisonForParent(parent, runtime), undefined, "multiple languages require an explicit choice");
  parent.getAttachments = () => [4, 3];
  assert.equal(await defaultComparisonForParent(parent, runtime), undefined, "a v6 original cannot be paired with a v7 translation");
});

test("reopens only a translation matching the selected original version and target language", async () => {
  const parent: ZoteroLikeItem = { id: 1, key: "PARENT", libraryID: 1, getField: () => "", getAttachments: () => [2, 3, 4, 5] };
  const originalV1 = pdf(2, "Preprint v1", "https://arxiv.org/pdf/2401.12345v1");
  const originalV2 = pdf(3, "Preprint v2", "https://arxiv.org/pdf/2401.12345v2");
  const translationV1 = pdf(4, "[TeXGlot] 简体中文", "", JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v1", language: "简体中文" }));
  const translationV2English = pdf(5, "[TeXGlot] English", "", JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v2", language: "English" }));
  const children = new Map<number, ZoteroLikeItem>([[1, parent], [2, originalV1], [3, originalV2], [4, translationV1], [5, translationV2English]]);
  const opened: number[][] = [];
  let created = 0;
  const runtime: ZoteroRuntime = {
    resolveItem: (id) => children.get(id),
    openSplitReader: async (original, translated) => { opened.push([original.id ?? 0, translated.id ?? 0]); },
  };
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true, latexUpload: true } }),
    createJob: async () => { created++; return { id: "job-v2", status: "queued" }; },
    pollJob: async () => ({ id: "job-v2", status: "needs_retry" }),
  } as unknown as TeXGlotBridge;
  const existing = await translateItems([originalV1], runtime, bridge);
  assert.deepEqual(existing, []);
  assert.deepEqual(opened, [[2, 4]]);
  const newVersion = await translateItems([originalV2], runtime, bridge);
  assert.deepEqual(newVersion, ["job-v2"]);
  assert.equal(created, 1);
  assert.deepEqual(opened, [[2, 4]]);
});

test("selecting a specific translated child opens that version even when another translation exists", async () => {
  const parent: ZoteroLikeItem = { id: 1, getField: () => "", getAttachments: () => [2, 3, 4, 5] };
  const originalV1 = pdf(2, "Preprint v1", "https://arxiv.org/pdf/2401.12345v1");
  const originalV2 = pdf(3, "Preprint v2", "https://arxiv.org/pdf/2401.12345v2");
  const translatedV1 = pdf(4, "[TeXGlot] v1", "", JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v1", language: "简体中文" }));
  const translatedV2 = pdf(5, "[TeXGlot] v2", "", JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v2", language: "简体中文" }));
  const children = new Map<number, ZoteroLikeItem>([[1, parent], [2, originalV1], [3, originalV2], [4, translatedV1], [5, translatedV2]]);
  const opened: number[][] = [];
  const runtime: ZoteroRuntime = {
    resolveItem: (id) => children.get(id),
    openSplitReader: async (left, right) => { opened.push([left.id ?? 0, right.id ?? 0]); },
  };
  assert.deepEqual(await translateItems([translatedV2], runtime, {} as TeXGlotBridge), []);
  assert.deepEqual(opened, [[3, 5]]);
});

test("does not pair a lone TeXGlot PDF with itself as the original", async () => {
  const translated = pdf(2, "[TeXGlot] 简体中文", "", JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v2", language: "简体中文" }));
  const parent: ZoteroLikeItem = { id: 1, getField: () => "", getAttachments: () => [2] };
  let opened = false;
  const messages: string[] = [];
  const runtime: ZoteroRuntime = {
    resolveItem: (id) => id === 1 ? parent : id === 2 ? translated : undefined,
    openSplitReader: async () => { opened = true; },
    notify: (message) => messages.push(message),
  };
  const offline = { health: async () => { throw new Error("offline"); } } as unknown as TeXGlotBridge;
  await assert.rejects(translateItems([translated], runtime, offline), /offline/);
  assert.equal(opened, false);
  assert.equal(await defaultComparisonForParent(parent, runtime), undefined);
});

test("reopens a unique marked translation when the parent only stores a bare arXiv ID", async () => {
  const parent: ZoteroLikeItem = {
    id: 1, getField: (field) => field === "url" ? "https://arxiv.org/abs/2602.21186" : "",
    getAttachments: () => [2, 3],
  };
  const original = pdf(2, "Preprint PDF", "");
  const translated = pdf(3, "[TeXGlot] 简体中文", "", JSON.stringify({
    provider: "texglot", artifact: "translated", arxiv_id: "2602.21186v2", language: "简体中文",
  }));
  const children = new Map<number, ZoteroLikeItem>([[1, parent], [2, original], [3, translated]]);
  const opened: number[][] = [];
  const runtime: ZoteroRuntime = {
    resolveItem: (id) => children.get(id),
    readPdfInfo: async () => ({ text: "arXiv:2602.21186v2 [cs.CV]", readable: true }),
    openSplitReader: async (left, right) => { opened.push([left.id ?? 0, right.id ?? 0]); },
  };
  assert.deepEqual(await translateItems([parent], runtime, {} as TeXGlotBridge), []);
  assert.deepEqual(opened, [[2, 3]]);
});

test("reopens Spa3R from a real Zotero parent whose getNote rejects bibliographic items", async () => {
  const parent: ZoteroLikeItem = {
    id: 1, key: "8846LWF4", libraryID: 1, isAttachment: () => false,
    getField: (field) => ({
      url: "http://arxiv.org/abs/2602.21186",
      DOI: "10.48550/arXiv.2602.21186",
      archiveID: "arXiv:2602.21186",
      extra: "arXiv:2602.21186 [cs.CV]",
      title: "Spa3R: Predictive spatial field modeling for 3D visual reasoning",
    } as Record<string, string>)[field] ?? "",
    getNote: () => { throw new Error("getNote() can only be called on notes and attachments"); },
    getAttachments: () => [2, 3],
  };
  const original = pdf(2, "Preprint PDF", "http://arxiv.org/pdf/2602.21186v2");
  original.getNote = () => { throw new Error("Item data not loaded"); };
  const translated = pdf(3, "[TeXGlot] 简体中文 · arXiv 2602.21186v2", "", JSON.stringify({
    provider: "texglot", arxiv_id: "2602.21186v2", language: "简体中文",
    task_id: "c6f93c31cefd470c", artifact: "translated", core_version: "unknown",
  }));
  const children = new Map<number, ZoteroLikeItem>([[1, parent], [2, original], [3, translated]]);
  const selection = await resolveLocalSource(parent, { resolveItem: (id) => children.get(id) });
  assert.deepEqual(selection?.source, { type: "arxiv", id: "2602.21186v2" });
  const opened: number[][] = [];
  const runtime: ZoteroRuntime = {
    resolveItem: (id) => children.get(id),
    openSplitReader: async (left, right) => { opened.push([left.id ?? 0, right.id ?? 0]); },
  };
  assert.deepEqual(await translateItems([parent], runtime, {} as TeXGlotBridge), []);
  assert.deepEqual(await translateItems([original], runtime, {} as TeXGlotBridge), []);
  assert.deepEqual(await translateItems([translated], runtime, {} as TeXGlotBridge), []);
  assert.deepEqual(opened, [[2, 3], [2, 3], [2, 3]]);
});

test("parent selection uses the highest verified local version and tolerates stale parent version metadata", async () => {
  const first = pdf(2, "First", "https://arxiv.org/pdf/2401.12345v1");
  const second = pdf(3, "Second", "https://arxiv.org/pdf/2401.12345v2");
  const parent: ZoteroLikeItem = { id: 1, getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.12345v1" : "", getAttachments: () => [2, 3] };
  const entries = new Map([[1, parent], [2, first], [3, second]]);
  const selection = await resolveLocalSource(parent, { resolveItem: (id) => entries.get(id) });
  assert.deepEqual(selection?.source, { type: "arxiv", id: "2401.12345v2" });
  assert.equal(selection?.attachment, second);
  assert.equal((await resolveLocalSource(first, { resolveItem: (id) => entries.get(id) }))?.attachment, first);
});

test("rejects a standalone attachment before starting a task that cannot import a child PDF", async () => {
  const standalone = pdf(80, "Standalone PDF", "https://arxiv.org/pdf/2401.12345v2");
  standalone.parentItemID = false;
  const messages: string[] = [];
  const runtime: ZoteroRuntime = { notify: (message) => messages.push(message) };
  assert.deepEqual(await translateItems([standalone], runtime, {} as TeXGlotBridge), []);
  assert.ok(messages.some((message) => message.includes("文献条目")));
});

test("asks for a concrete attachment when several matching translations exist", async () => {
  const parent: ZoteroLikeItem = { id: 1, getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.12345v2" : "", getAttachments: () => [2, 3, 4] };
  const original = pdf(2, "Preprint", "https://arxiv.org/pdf/2401.12345v2");
  const note = JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v2", language: "简体中文" });
  const first = pdf(3, "[TeXGlot] first", "", note);
  const second = pdf(4, "[TeXGlot] second", "", note);
  const items = new Map<number, ZoteroLikeItem>([[1, parent], [2, original], [3, first], [4, second]]);
  const messages: string[] = [];
  let opened = false;
  const runtime: ZoteroRuntime = { resolveItem: (id) => items.get(id), notify: (message) => messages.push(message), openSplitReader: async () => { opened = true; } };
  const jobs = await translateItems([parent], runtime, {} as TeXGlotBridge);
  assert.deepEqual(jobs, []);
  assert.equal(opened, false);
  assert.ok(messages.some((message) => message.includes("多个相同版本和语言的译文")));
});

test("a failed submission does not block the next selected paper", async () => {
  const first: ZoteroLikeItem = { id: 11, key: "FIRST", libraryID: 1, getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.12345v2" : "", getAttachments: () => [] };
  const second: ZoteroLikeItem = { id: 12, key: "SECOND", libraryID: 1, getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.12346v2" : "", getAttachments: () => [] };
  let calls = 0;
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true, latexUpload: true } }),
    createJob: async () => {
      if (++calls === 1) throw new Error("first submission failed");
      return { id: "second-job", status: "queued" };
    },
    pollJob: async () => ({ id: "second-job", status: "needs_retry" }),
  } as unknown as TeXGlotBridge;
  const messages: string[] = [];
  const runtime: ZoteroRuntime = { notify: (message) => messages.push(message) };
  const jobs = await translateItems([first, second], runtime, bridge);
  assert.deepEqual(jobs, ["second-job"]);
  assert.ok(messages.some((message) => message.includes("first submission failed")));
});

test("repeated menu actions do not submit the same active task twice", async () => {
  const parent: ZoteroLikeItem = {
    id: 101, key: "REPEAT", libraryID: 1,
    getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.99999v2" : "",
    getAttachments: () => [],
  };
  let finish!: (value: { id: string; status: string }) => void;
  const pending = new Promise<{ id: string; status: string }>((resolve) => { finish = resolve; });
  let submissions = 0;
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true, latexUpload: true } }),
    createJob: async () => { submissions++; return { id: "active-job", status: "queued" }; },
    pollJob: async () => pending,
  } as unknown as TeXGlotBridge;
  const runtime: ZoteroRuntime = { notify: () => undefined };
  assert.deepEqual(await translateItems([parent], runtime, bridge), ["active-job"]);
  assert.deepEqual(await translateItems([parent], runtime, bridge), []);
  assert.equal(submissions, 1);
  finish({ id: "active-job", status: "needs_retry" });
  await pending;
});

test("a partial translation is shown as requiring review after import", async () => {
  const parent: ZoteroLikeItem = {
    id: 201, key: "PARTIAL", libraryID: 1,
    getField: (field) => field === "url" ? "https://arxiv.org/abs/2401.12345v2" : "",
    getAttachments: () => [],
  };
  const messages: string[] = [];
  const runtime: ZoteroRuntime = {
    notify: (message) => messages.push(message),
    importAttachment: async () => ({ id: 202 }),
  };
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true, latexUpload: true } }),
    createJob: async () => ({ id: "partial-job", status: "queued" }),
    pollJob: async () => ({ id: "partial-job", status: "completed_with_warnings" }),
    artifact: async () => new Uint8Array([37, 80, 68, 70, 45]),
  } as unknown as TeXGlotBridge;
  assert.deepEqual(await translateItems([parent], runtime, bridge, { open: "none" }), ["partial-job"]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(messages.some((message) => message.includes("部分内容需检查")));
});

function reuseFixture() {
  const parent = { ...item({ url: "https://arxiv.org/abs/2401.12345v2" }), id: 701, getAttachments: () => [702] };
  const original = { ...pdf(702, "Original", "https://arxiv.org/abs/2401.12345v2"), parentItemID: 701 };
  const entries = new Map<number, ZoteroLikeItem>([[701, parent], [702, original]]);
  const messages: string[] = [];
  const importedNotes: string[] = [];
  const opened: Array<[number | undefined, number | undefined]> = [];
  const runtime: ZoteroRuntime = {
    resolveItem: (id) => entries.get(id),
    notify: (message) => messages.push(message),
    importAttachment: async (_bytes, options) => {
      importedNotes.push(options.note);
      const translated = { ...pdf(703, options.title, "", options.note), parentItemID: 701 };
      entries.set(703, translated);
      parent.getAttachments = () => [702, 703];
      return translated;
    },
    openSplitReader: async (left, right) => { opened.push([left.id, right.id]); },
  };
  return { parent, entries, runtime, messages, importedNotes, opened };
}

test("completed library reuse imports immediately, opens a split and then reopens offline", async () => {
  const fixture = reuseFixture();
  const paths: string[] = [];
  const bridge = new TeXGlotBridge({ fetch: async (url, init) => {
    const path = new URL(String(url)).pathname;
    paths.push(`${init?.method ?? "GET"} ${path}`);
    if (path.endsWith("/health")) return Response.json({ ok: true, name: "TeXGlot", capabilities: { library_reuse: true } });
    if (init?.method === "POST") return Response.json({ id: "app-job", status: "completed", reuse: "library" });
    assert.equal(path, "/api/integrations/zotero/jobs/app-job/artifacts/translated");
    return new Response("%PDF-1.7");
  } });
  assert.deepEqual(await translateItems([fixture.parent], fixture.runtime, bridge), ["app-job"]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(fixture.opened, [[702, 703]]);
  assert.equal(JSON.parse(fixture.importedNotes[0]).task_id, "app-job");
  assert.equal(paths.filter((path) => path.startsWith("POST")).length, 1);
  assert.equal(paths.some((path) => path === "GET /api/integrations/zotero/jobs/app-job"), false);
  assert.ok(fixture.messages.some((message) => message.includes("文献库中已有的译文")));
  assert.ok(!fixture.messages.some((message) => message.includes("已提交")));
  await translateItems([fixture.parent], fixture.runtime, {} as TeXGlotBridge);
  assert.equal(fixture.importedNotes.length, 1);
  assert.equal(fixture.opened.length, 2);
});

test("a reused running job is followed and imported only when it finishes", async () => {
  const fixture = reuseFixture();
  let finish!: (value: { id: string; status: string }) => void;
  const result = new Promise<{ id: string; status: string }>((resolve) => { finish = resolve; });
  let polls = 0;
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true } }),
    createJob: async () => ({ id: "cli-job", status: "translating", reuse: "active" }),
    pollJob: async (id: string) => { polls++; assert.equal(id, "cli-job"); return result; },
    artifact: async () => new TextEncoder().encode("%PDF-1.7"),
  } as unknown as TeXGlotBridge;
  await translateItems([fixture.parent], fixture.runtime, bridge);
  assert.equal(fixture.importedNotes.length, 0);
  assert.ok(fixture.messages.some((message) => message.includes("已关联")));
  assert.deepEqual(await translateItems([fixture.parent], fixture.runtime, bridge), []);
  finish({ id: "cli-job", status: "completed" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(polls, 1);
  assert.equal(fixture.importedNotes.length, 1);
  assert.deepEqual(fixture.opened, [[702, 703]]);
});

test("a missing older attachment does not prevent default comparison with its replacement", async () => {
  const fixture = reuseFixture();
  const note = JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v2", language: "简体中文" });
  fixture.entries.set(703, pdf(703, "recovered", "", note));
  fixture.entries.set(704, { ...pdf(704, "missing", "", note), fileExists: async () => false });
  fixture.parent.getAttachments = () => [702, 703, 704];
  const pair = await defaultComparisonForParent(fixture.parent, fixture.runtime);
  assert.equal(pair?.original.id, 702);
  assert.equal(pair?.translated.id, 703);
});

test("reused warning results retain a review marker after import", async () => {
  const fixture = reuseFixture();
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true } }),
    createJob: async () => ({ id: "warning-job", status: "completed", quality: "completed_with_warnings", reuse: "library" }),
    artifact: async () => new TextEncoder().encode("%PDF-1.7"),
  } as unknown as TeXGlotBridge;
  await translateItems([fixture.parent], fixture.runtime, bridge);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(JSON.parse(fixture.importedNotes[0]).translation_status, "completed_with_warnings");
  assert.ok(fixture.messages.some((message) => message.includes("需检查")));
});

test("missing Zotero translation files fall back to library reuse", async () => {
  const fixture = reuseFixture();
  fixture.parent.getAttachments = () => [702, 704];
  fixture.entries.set(704, { ...pdf(704, "missing", "", JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v2", language: "简体中文" })), fileExists: async () => false });
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true } }),
    createJob: async () => ({ id: "recover-job", status: "completed", reuse: "library" }),
    artifact: async () => new TextEncoder().encode("%PDF-1.7"),
  } as unknown as TeXGlotBridge;
  assert.deepEqual(await translateItems([fixture.parent], fixture.runtime, bridge), ["recover-job"]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(fixture.opened, [[702, 703]]);
});

test("explicit retranslation bypasses both local and library reuse without overwriting attachments", async () => {
  const fixture = reuseFixture();
  const note = JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2401.12345v2", language: "简体中文" });
  const existing = { ...pdf(704, "Existing translation", "", note), parentItemID: 701 };
  fixture.entries.set(704, existing);
  fixture.parent.getAttachments = () => [702, 704];
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true, libraryReuse: true } }),
    createJob: async (selection: any, options: JobOptions) => {
      assert.deepEqual(selection?.source, { type: "arxiv", id: "2401.12345v2" });
      assert.equal(options.reuseExisting, false);
      return { id: "new-job", status: "queued" };
    },
    pollJob: async () => ({ id: "new-job", status: "completed" }),
    artifact: async () => new TextEncoder().encode("%PDF-1.7"),
  } as unknown as TeXGlotBridge;
  assert.deepEqual(await translateItems([existing], fixture.runtime, bridge, { reuseExisting: false }), ["new-job"]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(fixture.opened, [[702, 703]]);
  assert.equal(existing.getNote?.(), note);
});
