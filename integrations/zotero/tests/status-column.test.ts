import assert from "node:assert/strict";
import test from "node:test";
import { installStatusColumn, renderStatusCell, statusColumnOrdinal, translationStatus } from "../src/status-column.js";
import { translateItems } from "../src/menus.js";
import type { TeXGlotBridge } from "../src/bridge.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));
function pdf(id: number, note = "", url = "", title = "PDF"): any {
  return { id, parentItemID: 1, isAttachment: () => true, isFileAttachment: () => true,
    attachmentContentType: "application/pdf", getNote: () => note,
    getField: (name: string) => name === "title" ? title : name === "url" ? url : "" };
}
const marker = (extra = {}) => JSON.stringify({ provider: "texglot", artifact: "translated", task_id: "job-1", language: "简体中文", arxiv_id: "1706.03762v7", ...extra });
const parent = (ids: number[] = [2, 3]): any => ({ id: 1, key: "PARENT", libraryID: 1, isRegularItem: () => true, getAttachments: () => ids, getField: (name: string) => name === "url" ? "https://arxiv.org/abs/1706.03762" : "" });

test("recognized PDFs stay translated after renaming; names and source archives cannot claim a translation", () => {
  const original = pdf(2, "", "https://arxiv.org/pdf/1706.03762v7");
  assert.equal(translationStatus(parent(), [original, pdf(3, marker(), "", "My Chinese copy")]).kind, "translated");
  assert.equal(translationStatus(parent(), [original, pdf(3, "", "", "[TeXGlot] renamed")]).kind, "review");
  assert.equal(translationStatus(parent(), [original, { ...pdf(3, marker()), attachmentContentType: "application/zip" }]).kind, "untranslated");
  assert.equal(translationStatus(parent(), [original, { ...pdf(3, marker()), deleted: true }]).kind, "untranslated");
});

test("warnings and uncovered original versions are visible without contacting the service", () => {
  const original = pdf(2, "", "https://arxiv.org/pdf/1706.03762v7");
  const old = pdf(3, marker({ arxiv_id: "1706.03762v6" }));
  assert.equal(translationStatus(parent(), [original, old]).kind, "review");
  assert.match(translationStatus(parent(), [original, old]).details.join(" "), /1706\.03762v7/);
  assert.equal(translationStatus(parent(), [original, pdf(3, marker({ translation_status: "completed_with_warnings" }))]).kind, "review");
  const both = translationStatus(parent(), [original, pdf(3, marker()), pdf(4, marker({ language: "English", task_id: "job-2" }))]);
  assert.equal(both.kind, "translated");
  assert.equal(both.details.length, 2);
});

test("status follows a saved PDF binding instead of stale parent or attachment URLs", () => {
  const stale = { ...parent(), getField: (name: string) => name === "url" ? "https://arxiv.org/abs/1706.03762v6" : "" };
  const original = { ...pdf(2, "", "https://arxiv.org/pdf/1706.03762v6"), key: "ORIGINAL" };
  const translated = pdf(3, marker({ source_attachment_key: "ORIGINAL", source_fingerprint: "sha256:verified" }));
  assert.equal(translationStatus(stale, [original, translated]).kind, "translated");
  assert.equal(translationStatus(stale, [original, translated, pdf(4, "", "https://arxiv.org/pdf/1706.03762v5")]).kind, "review");
  assert.equal(translationStatus(stale, [pdf(3, marker())]).kind, "review", "parent identity still matters when no original establishes its version");
});

test("column default ordering follows the current Title position", () => {
  assert.equal(statusColumnOrdinal([{ dataKey: "title", ordinal: 4 }, { dataKey: "creator", ordinal: 5 }]), 4.5);
  assert.equal(statusColumnOrdinal([{ dataKey: "title", ordinal: 4 }, { dataKey: "creator", ordinal: 4.2 }]), 4.1);
  assert.equal(statusColumnOrdinal([]), 0.5);
});

function host() {
  let descriptor: any;
  let observer: any;
  let registered = 0;
  let removed = 0;
  const redraws: number[][] = [];
  const items = new Map<number, any>([[1, parent()], [2, pdf(2, "", "https://arxiv.org/pdf/1706.03762v7")], [3, pdf(3, marker())]]);
  const zotero = {
    locale: "zh-CN",
    Items: { get: (id: number) => items.get(id), getAsync: async (ids: number[]) => ids.map((id) => items.get(id)).filter(Boolean) },
    ItemTreeManager: {
      registerColumn: (value: any) => { registered++; descriptor = value; return "zotero-texglot-translationStatus"; },
      unregisterColumn: () => { removed++; },
    },
    Notifier: {
      registerObserver: (value: any) => { observer = value; return "observer"; },
      unregisterObserver: () => undefined,
      trigger: async (event: string, _type: string, ids: number[]) => { assert.equal(event, "refresh"); redraws.push(ids); },
    },
  };
  return { zotero, items, get descriptor() { return descriptor; }, get observer() { return observer; }, get registered() { return registered; }, get removed() { return removed; }, redraws };
}

test("lazy note data loads before status resolution and deleted attachments invalidate the cached parent", async () => {
  const h = host();
  let noteLoaded = false;
  h.items.get(3).getNote = () => { if (!noteLoaded) throw new Error("note not loaded"); return marker(); };
  h.items.get(3).loadDataType = async (type: string) => { if (type === "note") noteLoaded = true; };
  const installation = installStatusColumn(h.zotero)!;
  assert.match(h.descriptor.dataProvider(h.items.get(1)), /^…/);
  await tick();
  assert.match(h.descriptor.dataProvider(h.items.get(1)), /^✓.*已有译文/);
  assert.equal(h.descriptor.dataProvider(h.items.get(3)), "", "child rows should not repeat the parent's status");
  h.items.delete(3);
  h.items.get(1).getAttachments = () => [2];
  h.observer.notify("delete", "item", [3]);
  h.descriptor.dataProvider(h.items.get(1));
  await tick();
  assert.match(h.descriptor.dataProvider(h.items.get(1)), /^○.*未翻译/);
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.deepEqual(h.redraws, [[1]], "batch row invalidations without scanning or redrawing the whole library");
  installation.dispose();
});

test("column registration is shared by main windows and preserves native user configuration", async () => {
  const h = host();
  const window = { ZoteroPane: { itemsView: { _getColumns: () => [{ dataKey: "title", ordinal: 3 }, { dataKey: "creator", ordinal: 4 }] } } };
  const first = installStatusColumn(h.zotero, window, "file:///addon/")!;
  const second = installStatusColumn(h.zotero)!;
  assert.equal(h.registered, 1);
  assert.equal(h.descriptor.ordinal, 3.5);
  assert.equal(h.descriptor.hidden, false);
  assert.equal(h.descriptor.showInColumnPicker, true);
  assert.ok(h.descriptor.zoteroPersist.includes("hidden"));
  assert.equal(h.descriptor.iconPath, "file:///addon/icons/texglot.png");
  first.dispose(); first.dispose();
  assert.equal(h.removed, 0);
  second.dispose();
  assert.equal(h.removed, 1);
});

test("adding the column refreshes the current rows even if Zotero cached them before installation", async () => {
  const h = host();
  const installation = installStatusColumn(h.zotero, { ZoteroPane: { itemsView: { getSortedItems: () => [1, 4] } } })!;
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.deepEqual(h.redraws, [[1, 4]]);
  installation.dispose();
});

test("a hot update preserves column neighbours, width and visibility after Zotero renumbers columns", () => {
  const h: any = host();
  const preferences = new Map<string, string>();
  h.zotero.Prefs = { get: (key: string) => preferences.get(key), set: (key: string, value: string) => preferences.set(key, value) };
  const key = "zotero-texglot-translationStatus";
  let cols = [{ dataKey: "title", ordinal: 0 }, { dataKey: key, ordinal: 1, hidden: true, width: 48 }, { dataKey: "creator", ordinal: 2 }];
  let stored: any = { [key]: { ordinal: 1, hidden: true, width: 48 } };
  const window = { ZoteroPane: { itemsView: { _getColumns: () => cols, _getColumnPrefs: () => stored, _storeColumnPrefs: (value: any) => { stored = value; } } } };
  installStatusColumn(h.zotero, window)!.dispose();
  cols = [{ dataKey: "title", ordinal: 0 }, { dataKey: "creator", ordinal: 1 }];
  const next = installStatusColumn(h.zotero, window)!;
  assert.deepEqual(stored[key], { ordinal: 0.5, hidden: true, width: 48 });
  next.dispose();
});

test("activity is combined with attachment state and clears after a successful import", async () => {
  const h = host();
  const column = installStatusColumn(h.zotero)!;
  column.setActivity(h.items.get(1), "job-2", { state: "processing", message: "10 / 20" });
  assert.match(h.descriptor.dataProvider(h.items.get(1)), /^◷.*处理中\n10 \/ 20/);
  await tick();
  column.setActivity(h.items.get(1), "job-2", { state: "review", message: "Service unavailable" });
  assert.match(h.descriptor.dataProvider(h.items.get(1)), /^!/);
  column.setActivity(h.items.get(1), "job-2", null);
  assert.match(h.descriptor.dataProvider(h.items.get(1)), /^✓/);
  column.dispose();
});

test("icon-only cells retain safe tooltips and accessible status text", () => {
  class Element {
    className = ""; title = ""; style = { cssText: "" }; dataset: any = {}; attrs: any = {}; children: Element[] = [];
    setAttribute(key: string, value: string) { this.attrs[key] = value; }
    appendChild(child: Element) { this.children.push(child); }
  }
  const doc: any = { createElement: () => new Element(), createElementNS: () => new Element() };
  const cell: any = renderStatusCell("✓ TeXGlot · 已有译文\n<English>", { className: "status" }, doc);
  assert.equal(cell.title, "TeXGlot · 已有译文\n<English>");
  assert.equal(cell.attrs["aria-label"], cell.title);
  assert.equal(cell.attrs.role, "img");
  assert.equal(cell.children[0].attrs["aria-hidden"], "true");
  assert.equal(cell.children[0].children.length, 1);
});

test("translation workflow publishes processing then durable completion and clears transient activity", async () => {
  let finish!: (value: any) => void;
  const pending = new Promise<any>((resolve) => { finish = resolve; });
  const activities: Array<string | null> = [];
  let note = "";
  const item = { ...parent([]), id: 993, getField: (name: string) => name === "url" ? "https://arxiv.org/abs/1706.03762v7" : "" };
  const bridge = {
    health: async () => ({ capabilities: { arxivLatex: true } }),
    createJob: async () => ({ id: "status-job", status: "queued" }),
    pollJob: async (_id: string, options: any) => { options.onUpdate({ status: "translating", message: "1 / 2" }); return pending; },
    artifact: async () => new TextEncoder().encode("%PDF-"),
  } as unknown as TeXGlotBridge;
  await translateItems([item], {
    setTranslationActivity: (_parent, _key, activity) => activities.push(activity?.state ?? null),
    importAttachment: async (_bytes, options) => { note = options.note; return { id: 994 }; },
  }, bridge, { open: "none" });
  assert.equal(activities[0], "processing");
  assert.equal(activities.at(-1), "processing");
  finish({ id: "status-job", status: "completed_with_warnings" });
  await tick();
  assert.equal(activities.at(-1), null);
  assert.equal(JSON.parse(note).translation_status, "completed_with_warnings");
});
