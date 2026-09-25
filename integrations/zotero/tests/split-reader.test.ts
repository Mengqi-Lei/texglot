import assert from "node:assert/strict";
import test from "node:test";
import { NativeSplitReader } from "../src/split-reader.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("either pane can drive page synchronization without a feedback loop", async () => {
  const leftViewer = new EventTarget();
  const rightViewer = new EventTarget();
  const leftDocument = new EventTarget();
  const rightDocument = new EventTarget();
  const leftBrowser = { contentWindow: { document: leftDocument } };
  const rightBrowser = { contentWindow: { document: rightDocument } };
  const window = {
    requestAnimationFrame: (callback: () => void) => { queueMicrotask(callback); return 1; },
    setTimeout,
    clearTimeout,
  };
  const split = new NativeSplitReader({ window });
  const subject = split as any;
  const calls: string[] = [];
  subject.getViewerContainer = (browser: unknown) => browser === leftBrowser ? leftViewer : rightViewer;
  subject.syncPageLocalPosition = (source: unknown, target: unknown) => {
    calls.push(`${source === leftBrowser ? "left" : "right"}->${target === leftBrowser ? "left" : "right"}`);
    (target === leftBrowser ? leftViewer : rightViewer).dispatchEvent(new Event("scroll"));
  };
  const state: any = {
    tabID: "tab-1", leftBrowser, rightBrowser, leftViewer: null, rightViewer: null,
    syncEnabled: true, syncPaused: false, cleaning: false, inputSide: "right",
    suppressSide: null, scrollRAF: null, pendingSourceSide: null, listeners: [], timers: [],
  };
  subject.states.set(state.tabID, state);
  subject.installSyncListeners(state);

  leftViewer.dispatchEvent(new Event("wheel"));
  leftViewer.dispatchEvent(new Event("scroll"));
  await tick();
  assert.deepEqual(calls, ["left->right"]);

  rightViewer.dispatchEvent(new Event("wheel"));
  rightViewer.dispatchEvent(new Event("scroll"));
  await tick();
  assert.deepEqual(calls, ["left->right", "right->left"]);

  for (const listener of state.listeners) listener.target.removeEventListener(listener.type, listener.listener, listener.options);
});

test("restoration reuses the selected Zotero tab and its saved split ratio", async () => {
  const item = (id: number) => ({ id, isFileAttachment: () => true, attachmentContentType: "application/pdf" });
  const tabs = [
    { id: "tab-a", type: "reader", data: { isSplitView: true, leftItemID: 1, rightItemID: 2, splitRatio: 0.37 } },
    { id: "tab-b", type: "reader-unloaded", data: { isSplitView: true, leftItemID: 3, rightItemID: 4 } },
  ];
  const calls: Array<{ original: number; translated: number; tabID?: string; splitRatio?: number }> = [];
  const split = new NativeSplitReader({
    window: { Zotero_Tabs: { _tabs: tabs, selectedID: "tab-a" } },
    Zotero: { Items: { get: (id: number) => item(id) } },
  });
  (split as any).open = async (original: any, translated: any, options: any) => {
    calls.push({ original: original.id, translated: translated.id, tabID: options.tabID, splitRatio: options.splitRatio });
  };
  split.restoreSavedSplits();
  await tick();
  assert.deepEqual(calls, [{ original: 1, translated: 2, tabID: "tab-a", splitRatio: 0.37 }]);
});

test("converting a reader tab does not remove its native Zotero registration", async () => {
  const reader = {
    _blockingObserver: { unregister: () => undefined },
    _iframe: {},
    uninit: () => { throw new Error("native reader was unregistered"); },
  };
  const split = new NativeSplitReader();
  await (split as any).closeReaderWithoutClosingTab(reader);
});

test("a missing translated attachment fails before an empty reader is shown", async () => {
  const split = new NativeSplitReader({ window: { IOUtils: { exists: async () => false } } });
  const item = { getFilePathAsync: async () => "/missing/translation.pdf" };
  await assert.rejects(
    (split as any).initializeReader({}, "right", item, {}, {}, null),
    /译文 PDF 本地文件不存在/,
  );
  // Zotero.Item.getFilePathAsync() returns false for a missing/unavailable
  // attachment. It does not always return a path that IOUtils can inspect.
  await assert.rejects(
    (split as any).initializeReader({}, "right", { getFilePathAsync: async () => false }, {}, {}, null),
    /译文 PDF 本地文件不存在/,
  );
});

test("annotation save errors are reported instead of acknowledged as success", async () => {
  const alerts: string[] = [];
  const split = new NativeSplitReader({
    window: {},
    Zotero: {
      API: { getLibraryPrefix: () => "users/1" },
      Annotations: { saveFromJSON: async () => { throw new Error("disk unavailable"); } },
      alert: (_window: unknown, _title: string, message: string) => alerts.push(message),
    },
  });
  const item = {
    id: 5, key: "ABCD1234", libraryID: 1,
    getAnnotations: () => [], isEditable: () => true,
  };
  const state = { tabID: "tab-a", nativeReader: null };
  const browser = { contentWindow: {} };
  const config = await (split as any).buildReaderConfig(state, "left", item, browser, {}, null, null);
  let callbackCount = 0;
  await assert.rejects(
    config.onSaveAnnotations([{ id: "ANNO1234" }], () => callbackCount++),
    /disk unavailable/,
  );
  assert.equal(callbackCount, 1);
  assert.ok(alerts.some((value) => value.includes("批注未能保存")));
});

test("embedded reader confirmation uses the Zotero host prompt", async () => {
  let result = 0;
  const split = new NativeSplitReader({
    window: {},
    Zotero: { API: { getLibraryPrefix: () => "users/1" } },
    Services: { prompt: {
      BUTTON_POS_0: 1, BUTTON_TITLE_IS_STRING: 1,
      BUTTON_POS_1: 1, BUTTON_TITLE_CANCEL: 1,
      confirmEx: () => result,
    } },
  });
  const item = { id: 5, key: "PDF1", libraryID: 1, getAnnotations: () => [], isEditable: () => true };
  const config = await (split as any).buildReaderConfig({ tabID: "tab-a" }, "left", item, { contentWindow: {} }, {}, null, null);
  assert.equal(config.onConfirm("Confirm", "Action", "OK"), true);
  result = 1;
  assert.equal(config.onConfirm("Confirm", "Action", "OK"), false);
});

test("startup registers a tab listener even when the library is selected", () => {
  let notifier: any;
  const split = new NativeSplitReader({
    window: { Zotero_Tabs: { selectedID: "zotero-pane", _tabs: [] } },
    Zotero: { Notifier: { registerObserver: (value: any) => { notifier = value; return "observer-1"; } } },
  });
  split.restoreSavedSplits();
  assert.equal(typeof notifier?.notify, "function");
});

test("closed split tabs cannot keep an orphaned reader that hijacks PDF opening", () => {
  const window: any = { Zotero_Tabs: { selectedID: "zotero-pane", _tabs: [{ id: "zotero-pane" }, { id: "live-tab" }] } };
  const closed = { tabID: "closed-tab", _window: window, uninitCalls: 0, uninit() { this.uninitCalls++; } };
  const oldWindow = { closed: true, Zotero_Tabs: { _tabs: [{ id: "old-tab" }] } };
  const closedWindowReader = { tabID: "old-tab", _window: oldWindow, uninitCalls: 0, uninit() { this.uninitCalls++; throw new Error("detached browser"); } };
  const live = { tabID: "live-tab", _window: window, uninitCalls: 0, uninit() { this.uninitCalls++; } };
  const readers = [closed, closedWindowReader, live];
  const split = new NativeSplitReader({ window, Zotero: { Reader: { _readers: readers }, debug: () => undefined } });
  split.restoreSavedSplits();
  assert.deepEqual(readers, [live]);
  assert.equal(closed.uninitCalls, 1);
  assert.equal(closedWindowReader.uninitCalls, 1);
  assert.equal(live.uninitCalls, 0);

  window.Zotero_Tabs._tabs.pop();
  (split as any).states.set("live-tab", {
    tabID: "live-tab", nativeReader: live, cleaning: false,
    listeners: [], syncListeners: [], timers: [], persistTimer: null, scrollRAF: null,
    dragOverlay: null, finishDrag: null, leftBrowser: {}, rightBrowser: {}, controlBar: null,
  });
  (split as any).cleanup("live-tab");
  assert.deepEqual(readers, []);
  assert.equal(live.uninitCalls, 1);
});

test("an in-progress PDF open cannot rebuild a split after the add-on unloads", async () => {
  let finishOpen: (reader: any) => void = () => undefined;
  const nativeOpen = new Promise<any>((resolve) => { finishOpen = resolve; });
  const window = { Zotero_Tabs: { selectedID: "zotero-pane", _tabs: [{ id: "zotero-pane" }] } };
  const split = new NativeSplitReader({ window, Zotero: { Reader: { _readers: [], open: () => nativeOpen } } });
  const pdf = (id: number) => ({ id, isFileAttachment: () => true, attachmentContentType: "application/pdf" });
  const pending = split.open(pdf(1), pdf(2));
  split.shutdown();
  finishOpen({ tabID: "native-tab" });
  await assert.rejects(pending, /分屏阅读器已关闭/);
  assert.equal((split as any).states.size, 0);
});

test("image saving writes the selected PDF image bytes", async () => {
  let saved: number[] = [];
  class FakePicker {
    modeSave = 0;
    returnOK = 1;
    returnReplace = 2;
    file = "/tmp/test-image.png";
    init() {}
    appendFilter() {}
    async show() { return this.returnOK; }
  }
  const split = new NativeSplitReader({
    window: {
      ChromeUtils: { importESModule: () => ({ FilePicker: FakePicker }) },
      IOUtils: { write: async (_path: string, bytes: Uint8Array) => { saved = [...bytes]; } },
    },
  });
  await (split as any).saveImageAs("data:image/png;base64,iVBORw==", { contentWindow: {} });
  assert.deepEqual(saved, [137, 80, 78, 71]);
});

test("divider has a usable hit target and dragging changes the split only until release", async () => {
  const doc = new EventTarget() as any;
  let overlay: any;
  const resizer = new EventTarget() as any;
  resizer.style = {};
  resizer.setAttribute = () => undefined;
  resizer.getBoundingClientRect = () => ({ width: 12 });
  doc.createXULElement = () => resizer;
  doc.createElement = () => {
    overlay = new EventTarget() as any;
    overlay.style = {};
    overlay.remove = () => { overlay.removed = true; };
    return overlay;
  };
  doc.documentElement = { appendChild: () => undefined };
  const window = new EventTarget() as any;
  window.document = doc;
  window.requestAnimationFrame = (callback: () => void) => { queueMicrotask(callback); return 1; };
  window.cancelAnimationFrame = () => undefined;
  const split = new NativeSplitReader({ window });
  const handle = (split as any).createResizer();
  assert.equal(handle.style.width, "12px");
  assert.equal(handle.style.borderLeft, "5px solid transparent");
  const state: any = {
    leftBrowser: { style: {} }, rightBrowser: { style: {} }, splitRatio: 0.5,
    dragOverlay: null, finishDrag: null, listeners: [], cleaning: false,
  };
  const row = { getBoundingClientRect: () => ({ left: 0, width: 1000 }) };
  (split as any).installResizer(state, handle, row);
  const mouse = (type: string, x: number, button = 0) => {
    const event = new Event(type) as any;
    event.clientX = x;
    event.button = button;
    return event;
  };

  handle.dispatchEvent(mouse("mousedown", 500, 2));
  assert.equal(state.dragOverlay, null, "secondary click must not start a drag");
  handle.dispatchEvent(mouse("mousedown", 500));
  overlay.dispatchEvent(mouse("mousemove", 720));
  await tick();
  assert.ok(state.splitRatio > 0.7);
  overlay.dispatchEvent(mouse("mouseup", 720));
  assert.equal(state.dragOverlay, null);
  assert.equal(overlay.removed, true);
  const settled = state.splitRatio;
  window.dispatchEvent(mouse("mousemove", 300));
  assert.equal(state.splitRatio, settled, "movement after release must not resize");

  handle.dispatchEvent(mouse("mousedown", 720));
  overlay.dispatchEvent(mouse("mousemove", 300));
  await tick();
  const escape = new Event("keydown") as any;
  escape.key = "Escape";
  doc.dispatchEvent(escape);
  assert.equal(state.splitRatio, settled, "Escape must restore the starting width");
});

test("Zotero title refresh keeps the split title and restores its original hook on shutdown", async () => {
  const getNativeTitle = async (_tab: { id: string }) => "Paper title";
  const hooks = { reader: getNativeTitle };
  const split = new NativeSplitReader({
    window: { Zotero_Tabs: { selectedID: "zotero-pane", _tabs: [], tabHooks: { getTitle: hooks } } },
    Zotero: {
      Notifier: { registerObserver: () => "observer", unregisterObserver: () => undefined },
    },
  });
  split.restoreSavedSplits();
  (split as any).states.set("split-1", {
    tabID: "split-1", cleaning: false,
    leftItem: { getField: () => "Original PDF" },
    rightItem: { getField: () => "Translated PDF" },
  });
  assert.equal(await hooks.reader({ id: "split-1" }), "Original PDF | Translated PDF");
  assert.equal(await hooks.reader({ id: "plain-tab" }), "Paper title");
  (split as any).states.clear();
  split.shutdown();
  assert.equal(hooks.reader, getNativeTitle);
});

test("page editing targets only the selected attachment, confirms deletion, reloads its pane, and unfreezes", async () => {
  const calls: string[] = [];
  const host = {
    Zotero: {
      API: { getLibraryPrefix: () => "users/1" },
      PDFWorker: {
        rotatePages: async (id: number, pages: number[], degrees: number, priority: boolean) =>
          calls.push(`rotate:${id}:${pages.join(",")}:${degrees}:${priority}`),
        deletePages: async (id: number, pages: number[], priority: boolean) =>
          calls.push(`delete:${id}:${pages.join(",")}:${priority}`),
      },
    },
  };
  const split = new NativeSplitReader(host);
  const subject = split as any;
  const internal = {
    freeze: () => calls.push("freeze"),
    unfreeze: () => calls.push("unfreeze"),
    reload: (_data: unknown) => calls.push("reload"),
  };
  subject.internalReader = () => internal;
  subject.waitForInternalReader = async () => calls.push("ready");
  subject.refreshSyncListeners = () => calls.push("listeners");
  subject.syncFromSide = () => calls.push("sync");
  const original = { id: 1, key: "ORIGINAL", libraryID: 1 };
  const translated = { id: 2, key: "TRANSLATED", libraryID: 1 };
  const leftBrowser = { contentWindow: {} };
  const rightBrowser = { contentWindow: {} };
  let confirmed = false;
  const state = {
    cleaning: false, syncEnabled: true, syncPaused: false,
    nativeReader: { _promptToDeletePages: (count: number) => { calls.push(`confirm:${count}`); return confirmed; } },
  };

  await subject.editPages(state, "left", original, leftBrowser, [0, 2], "rotate", 90);
  assert.deepEqual(calls, ["freeze", "rotate:1:0,2:90:true", "reload", "ready", "listeners", "sync", "unfreeze"]);

  calls.length = 0;
  await subject.editPages(state, "right", translated, rightBrowser, [1], "delete");
  assert.deepEqual(calls, ["confirm:1"], "cancelled deletion must not touch the worker");

  calls.length = 0;
  confirmed = true;
  await subject.editPages(state, "right", translated, rightBrowser, [1], "delete");
  assert.deepEqual(calls, ["confirm:1", "freeze", "delete:2:1:true", "reload", "ready", "listeners", "sync", "unfreeze"]);
});

test("failed PDF worker operations unfreeze the pane and restore scroll synchronization", async () => {
  const calls: string[] = [];
  const split = new NativeSplitReader({
    Zotero: {
      PDFWorker: { rotatePages: async () => { throw new Error("worker failed"); } },
      alert: (_window: unknown, _title: string, text: string) => calls.push(text),
    },
  });
  const subject = split as any;
  subject.internalReader = () => ({ freeze: () => calls.push("freeze"), unfreeze: () => calls.push("unfreeze"), reload: () => calls.push("reload") });
  subject.waitForInternalReader = async () => calls.push("ready");
  subject.refreshSyncListeners = () => calls.push("listeners");
  const state = { cleaning: false, syncPaused: false, nativeReader: {} };
  await subject.editPages(state, "left", { id: 1 }, { contentWindow: {} }, [0], "rotate", 90);
  assert.equal(state.syncPaused, false);
  assert.ok(calls.includes("unfreeze"));
  assert.ok(calls.some((value) => value.includes("PDF 页面操作失败")));
  assert.ok(calls.includes("reload"), "reload even when the worker reports a partial-write failure");
  assert.ok(calls.includes("ready"));
});

test("a failing image callback reports the error without an unhandled rejection", async () => {
  const alerts: string[] = [];
  const split = new NativeSplitReader({
    window: {},
    Zotero: { alert: (_window: unknown, _title: string, message: string) => alerts.push(message) },
  });
  await (split as any).copyImage("not-a-data-url");
  assert.ok(alerts.some((message) => message.includes("复制图片失败")));
});

test("image annotations store their cache image as well as the Zotero item", async () => {
  const calls: string[] = [];
  let cached: Blob | undefined;
  const split = new NativeSplitReader({
    Zotero: {
      Items: { getByLibraryAndKey: () => undefined },
      Notifier: {
        Queue: class {},
        commit: async () => calls.push("commit"),
      },
      Annotations: {
        saveFromJSON: async (_item: unknown, annotation: any, options: any) => {
          assert.ok(options.notifierQueue);
          calls.push(`save:${annotation.key}`);
          return { key: annotation.key, libraryID: 1 };
        },
        saveCacheImage: async (_annotation: unknown, blob: Blob) => { calls.push("cache"); cached = blob; },
      },
    },
  });
  await (split as any).saveAnnotations({ id: 4, libraryID: 1 }, [{ id: "IMGKEY", image: "data:image/png;base64,iVBORw==" }]);
  assert.deepEqual(calls, ["save:IMGKEY", "cache", "commit"]);
  assert.equal(cached?.type, "image/png");
  assert.deepEqual([...new Uint8Array(await cached!.arrayBuffer())], [137, 80, 78, 71]);
});

test("annotation deletion commits the notifier queue and reports failures", async () => {
  const calls: string[] = [];
  const annotation = {
    parentID: 4, isAnnotation: () => true,
    eraseTx: async (options: any) => { assert.ok(options.notifierQueue); calls.push("erase"); throw new Error("erase failed"); },
  };
  const split = new NativeSplitReader({
    window: {},
    Zotero: {
      Items: { getByLibraryAndKey: () => annotation },
      Notifier: { Queue: class {}, commit: async () => calls.push("commit") },
      alert: (_window: unknown, _title: string, message: string) => calls.push(message),
    },
  });
  await assert.rejects((split as any).deleteAnnotations({ id: 4, libraryID: 1 }, ["ANNKEY"]), /erase failed/);
  assert.deepEqual(calls.slice(0, 2), ["erase", "删除批注失败：Error: erase failed"]);
  assert.equal(calls.at(-1), "commit");
});

test("both PDF attachments persist their own page and viewport state", async () => {
  const writes: Record<string, any> = {};
  const pages: Record<number, number> = { 1: 0, 2: 0 };
  const item = (id: number) => ({
    id,
    getAttachmentLastPageIndex: () => pages[id],
    setAttachmentLastPageIndex: async (page: number) => { pages[id] = page; },
  });
  const left = item(1);
  const right = item(2);
  const split = new NativeSplitReader({
    window: { IOUtils: { exists: async () => true, writeJSON: async (path: string, value: any) => { writes[path] = value; } } },
    Zotero: {
      Items: { get: (id: number) => id === 1 ? left : right },
      Attachments: { getStorageDirectory: (attachment: any) => ({
        path: `/virtual/${attachment.id}`,
        clone: () => ({ path: `/virtual/${attachment.id}`, append(name: string) { this.path += `/${name}`; } }),
      }) },
      Notifier: { trigger: () => undefined },
    },
  });
  await (split as any).persistSplitViewStates({
    leftItem: left, rightItem: right,
    leftViewState: { pageIndex: 3, top: 0.2 }, rightViewState: { pageIndex: 4, top: 0.6 },
  });
  assert.deepEqual(pages, { 1: 3, 2: 4 });
  assert.deepEqual(writes["/virtual/1/.zotero-reader-state"], { pageIndex: 3, top: 0.2 });
  assert.deepEqual(writes["/virtual/2/.zotero-reader-state"], { pageIndex: 4, top: 0.6 });
});

test("short source pages map to the same page-local fraction without jumping to the target bottom", () => {
  const leftBrowser = { side: "left" };
  const rightBrowser = { side: "right" };
  const sourceViewer = { currentPageNumber: 2, pagesCount: 4 };
  const targetViewer = { currentPageNumber: 1, pagesCount: 4 };
  const sourcePage = { offsetHeight: 600, offsetTop: 100 };
  const targetPage = { offsetHeight: 1200, offsetTop: 200 };
  const sourceContainer = { clientHeight: 800, scrollTop: 250, querySelector: () => sourcePage };
  const targetContainer = { clientHeight: 800, scrollTop: 0, querySelector: () => targetPage };
  const split = new NativeSplitReader();
  const subject = split as any;
  subject.internalReader = (browser: unknown) => ({
    _primaryView: { _iframe: { contentWindow: { PDFViewerApplication: { pdfViewer: browser === leftBrowser ? sourceViewer : targetViewer } } } },
  });
  subject.getViewerContainer = (browser: unknown) => browser === leftBrowser ? sourceContainer : targetContainer;
  subject.syncPageLocalPosition(leftBrowser, rightBrowser);
  assert.equal(targetViewer.currentPageNumber, 2);
  assert.equal(targetContainer.scrollTop, 500);
});

test("Zotero context pane events reach both embedded PDF readers", () => {
  const container = new EventTarget() as any;
  const calls: string[] = [];
  const leftBrowser = { contentWindow: {} };
  const rightBrowser = { contentWindow: {} };
  const split = new NativeSplitReader();
  const subject = split as any;
  subject.internalReader = (browser: unknown) => ({
    setContextPaneOpen: (open: boolean) => calls.push(`${browser === leftBrowser ? "left" : "right"}:open:${open}`),
    setBottomPlaceholderHeight: (height: number) => calls.push(`${browser === leftBrowser ? "left" : "right"}:height:${height}`),
  });
  const state: any = {
    container, nativeReader: {}, leftBrowser, rightBrowser,
    leftPopupset: {}, listeners: [],
  };
  subject.rebindNativeReader(state);
  const event = (type: string, detail: any) => {
    const value = new Event(type) as any;
    value.detail = detail;
    container.dispatchEvent(value);
  };
  event("tab-context-pane-toggle", { open: true });
  event("tab-bottom-placeholder-resize", { height: 42 });
  assert.deepEqual(calls, ["left:open:true", "right:open:true", "left:height:42", "right:height:42"]);
});

test("annotation drag keeps Zotero's native payload and adds safely escaped plain and HTML text", async () => {
  const split = new NativeSplitReader({ Zotero: { API: { getLibraryPrefix: () => "users/1" } } });
  const config = await (split as any).buildReaderConfig(
    { tabID: "split", nativeReader: null }, "right",
    { id: 7, key: "PDFKEY", libraryID: 1, getAnnotations: () => [], isEditable: () => true },
    { contentWindow: {} }, { children: [] }, null, null,
  );
  const data = new Map<string, string>();
  const transfer = { setData: (type: string, value: string) => data.set(type, value) };
  config.onSetDataTransferAnnotations(transfer, [{ id: "ANN", text: "A < B", comment: "Use & verify" }], false);
  assert.equal(JSON.parse(data.get("zotero/annotation")!)[0].attachmentItemID, 7);
  assert.equal(data.get("text/plain"), "A < B\nUse & verify");
  assert.equal(data.get("text/html"), "<p>A &lt; B<br>Use &amp; verify</p>");

  data.clear();
  config.onSetDataTransferAnnotations(transfer, [{ id: "ANN", text: "Selected text" }], true);
  assert.ok(data.has("zotero/annotation"));
  assert.equal(data.has("text/plain"), false, "do not overwrite a real PDF text selection");
});

test("an embedded secondary view never overwrites its attachment's primary reading position", async () => {
  const split = new NativeSplitReader({ Zotero: { API: { getLibraryPrefix: () => "users/1" } } });
  const subject = split as any;
  const state: any = {
    tabID: "split", cleaning: false,
    leftViewState: { pageIndex: 1 }, rightViewState: { pageIndex: 3 },
    leftSecondaryViewState: null, rightSecondaryViewState: { pageIndex: 2 },
  };
  subject.states.set("split", state);
  let attachmentSaveCount = 0;
  let tabSaveCount = 0;
  subject.scheduleTabDataSave = () => attachmentSaveCount++;
  subject.updateTabData = () => tabSaveCount++;
  const config = await subject.buildReaderConfig(
    state, "right",
    { id: 7, key: "PDFKEY", libraryID: 1, getAnnotations: () => [], isEditable: () => true },
    { contentWindow: {} }, { children: [] }, state.rightViewState, null,
  );
  assert.deepEqual(config.secondaryViewState, { pageIndex: 2 });
  config.onChangeViewState({ pageIndex: 9 }, false);
  assert.deepEqual(state.rightViewState, { pageIndex: 3 });
  assert.deepEqual(state.rightSecondaryViewState, { pageIndex: 9 });
  assert.equal(attachmentSaveCount, 0);
  assert.equal(tabSaveCount, 1);
  config.onChangeViewState({ pageIndex: 4 }, true);
  assert.deepEqual(state.rightViewState, { pageIndex: 4 });
  assert.equal(attachmentSaveCount, 1);
});

test("adding a selection to a note explains when no Zotero note editor is open", () => {
  const alerts: string[] = [];
  const split = new NativeSplitReader({
    Zotero: {
      getMainWindow: () => ({ ZoteroContextPane: { activeEditor: null } }),
      alert: (_window: unknown, _title: string, message: string) => alerts.push(message),
    },
  });
  (split as any).addToActiveNote({ id: 7 }, [{ text: "A result" }]);
  assert.ok(alerts.some((message) => message.includes("请先在 Zotero 中打开或创建一篇笔记")));
});

test("right pane receives external annotation changes by Zotero item ID and key", async () => {
  const calls: string[] = [];
  let annotations: any[] = [{ id: 10, key: "OLDKEY", isAnnotation: () => true, text: "old" }];
  const rightItem = { id: 2, getAnnotations: () => annotations };
  const rightBrowser = { contentWindow: {} };
  const split = new NativeSplitReader({
    Zotero: { Annotations: { toJSON: async (annotation: any) => ({ key: annotation.key, text: annotation.text }) } },
  });
  const subject = split as any;
  subject.internalReader = () => ({
    setAnnotations: (values: any[]) => calls.push(`set:${values.map((value) => value.id).join(",")}`),
    unsetAnnotations: (keys: string[]) => calls.push(`unset:${keys.join(",")}`),
  });
  const state: any = {
    tabID: "split", cleaning: false, rightItem, rightBrowser,
    nativeReader: { _instanceID: "self" },
    rightAnnotationIds: new Map([[10, "OLDKEY"]]),
    rightAnnotationRefresh: Promise.resolve(),
  };
  subject.states.set("split", state);
  subject.handleRightItemNotification("modify", [10], { 10: { instanceID: "other" } });
  await state.rightAnnotationRefresh;
  assert.deepEqual(calls, ["set:OLDKEY"]);

  subject.handleRightItemNotification("modify", [10], { 10: { instanceID: "self" } });
  await state.rightAnnotationRefresh;
  assert.deepEqual(calls, ["set:OLDKEY"], "do not echo this split reader's own save");

  annotations = [];
  subject.handleRightItemNotification("delete", [10], { 10: { key: "OLDKEY" } });
  await state.rightAnnotationRefresh;
  assert.deepEqual(calls, ["set:OLDKEY", "unset:OLDKEY"]);

  annotations = [{ id: 11, key: "NEWKEY", isAnnotation: () => true, text: "new" }];
  subject.handleRightItemNotification("add", [11], { 11: { instanceID: "other" } });
  await state.rightAnnotationRefresh;
  assert.deepEqual(calls, ["set:OLDKEY", "unset:OLDKEY", "set:NEWKEY"]);
});
