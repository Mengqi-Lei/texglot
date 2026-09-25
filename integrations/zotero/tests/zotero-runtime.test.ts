import assert from "node:assert/strict";
import test from "node:test";
import { installContextMenu } from "../src/menus.js";
import { createZoteroRuntime } from "../src/zotero-runtime.js";

test("maps the Zotero attachment API through the runtime adapter", async () => {
  const calls: string[] = [];
  const imported = { setField: (name: string, value: string) => calls.push(`${name}:${value}`), setNote: (value: string) => calls.push(`note:${value}`), saveTx: async () => calls.push("save") };
  const host = {
    Zotero: {
      Items: { get: (id: number) => ({ id, getField: () => "" }) },
      getTempDirectory: () => ({ path: "/tmp" }),
      File: { pathToFile: (path: string) => ({ path }) },
      Attachments: { importFromFile: async (value: { file: { path: string }; parentItemID: number; title: string }) => { calls.push(`import:${value.file.path}:${value.parentItemID}:${value.title}`); return imported; } },
      launchURL: (url: string) => calls.push(`url:${url}`),
      debug: (value: string) => calls.push(value),
    },
    ZoteroPane: { getSelectedItems: () => [{ id: 3 }], displayInfoMessage: (value: string) => calls.push(`info:${value}`) },
    PathUtils: { join: (root: string, name: string) => `${root}/${name}` },
    IOUtils: { write: async () => undefined, remove: async () => undefined, read: async () => new Uint8Array([1, 2]) },
  };
  const runtime = createZoteroRuntime(host);
  assert.equal(runtime.getSelectedItems?.()[0].id, 3);
  assert.deepEqual([...await runtime.readFile?.("/tmp/input.tex") ?? []], [1, 2]);
  await runtime.importAttachment?.(new Uint8Array([37, 80, 68, 70, 45]), { parent: { id: 7 }, title: "translated", note: "{}", extension: "pdf" });
  assert.ok(calls.some((value) => value.startsWith("import:/tmp/texglot-")));
  assert.ok(calls.includes("title:translated"));
  assert.ok(calls.includes("save"));
  runtime.openReader?.("task-1", "comparison", "http://127.0.0.1:8766");
  assert.ok(calls.includes("url:http://127.0.0.1:8766/?reader=task-1&mode=comparison"));
});

test("reports errors without invoking Zotero's deprecated crash API", () => {
  const calls: string[] = [];
  const runtime = createZoteroRuntime({
    Zotero: {
      alert: (_window: unknown, title: string, message: string) => calls.push(`alert:${title}:${message}`),
      debug: (value: string) => calls.push(`debug:${value}`),
    },
    ZoteroPane: {
      displayErrorMessage: () => { throw new Error("deprecated crash API must not be called"); },
    },
  });

  runtime.notify?.("无法连接 TeXGlot 本地服务。", "error");
  assert.ok(calls.includes("alert:TeXGlot:无法连接 TeXGlot 本地服务。"));
});

test("official-original confirmation uses short localized buttons and cancellation is harmless", async () => {
  let choice = 1;
  const runtime = createZoteroRuntime({
    Zotero: { locale: "zh-CN" },
    Services: { prompt: {
      BUTTON_POS_0: 1, BUTTON_POS_1: 256, BUTTON_POS_2: 65536, BUTTON_TITLE_IS_STRING: 127,
      confirmEx: (_window: unknown, _title: string, body: string, _flags: number, use: string, cancel: string, other: string | null) => {
        assert.ok(body.includes("原有 PDF 和批注会保留"));
        assert.equal(use, "使用 arXiv v7");
        assert.equal(cancel, "取消");
        assert.equal(other, null);
        return choice;
      },
    } },
  });
  assert.equal(await runtime.confirmOfficialSource?.("1706.03762v7", false), "cancel");
  choice = 0;
  assert.equal(await runtime.confirmOfficialSource?.("1706.03762v7", false), "official");
  runtime.dispose?.();
});

test("updated translation metadata reuses the older attachment for the same task", async () => {
  const metadata = { provider: "texglot", artifact: "translated", task_id: "task-1", arxiv_id: "1706.03762v7", language: "简体中文", core_version: "unknown" };
  const existing = { id: 2, getNote: () => JSON.stringify(metadata) };
  const runtime = createZoteroRuntime({ Zotero: { Items: { get: () => existing } } });
  assert.equal(await runtime.findAttachment?.({ getAttachments: () => [2] }, JSON.stringify({ ...metadata, translation_status: "completed" })), existing);
  assert.equal(await runtime.findAttachment?.({ getAttachments: () => [2] }, JSON.stringify({ ...metadata, artifact: "source" })), undefined);
});

test("a missing imported file does not block recovery from the TeXGlot library", async () => {
  const note = JSON.stringify({ provider: "texglot", artifact: "translated", task_id: "task-1", language: "简体中文" });
  const runtime = createZoteroRuntime({ Zotero: { Items: { get: () => ({ id: 2, getNote: () => note, fileExists: async () => false }) } } });
  assert.equal(await runtime.findAttachment?.({ getAttachments: () => [2] }, note), undefined);
});

test("shows visible one-shot notifications but does not popup on every poll", () => {
  const calls: string[] = [];
  class ProgressWindow {
    ItemProgress = class {
      constructor(_icon: unknown, message: string) { calls.push(`row:${message}`); }
      setProgress(value: number) { calls.push(`progress:${value}`); }
    };
    changeHeadline(value: string) { calls.push(`headline:${value}`); }
    show() { calls.push("show"); }
    startCloseTimer(value: number) { calls.push(`close:${value}`); }
  }
  const runtime = createZoteroRuntime({ Zotero: { ProgressWindow, debug: () => undefined } });
  runtime.notify?.("TeXGlot 已提交 2602.21186v2。", "info");
  runtime.notify?.("TeXGlot task-1: 正在翻译", "info");
  assert.ok(calls.includes("row:TeXGlot 已提交 2602.21186v2。"));
  assert.equal(calls.filter((value) => value === "show").length, 1);
  assert.ok(calls.some((value) => value.startsWith("close:")));
});

test("never mistakes a translated PDF for an original or guesses among versions", () => {
  const items: Record<number, any> = {
    1: { id: 1, isFileAttachment: () => true, attachmentContentType: "application/pdf", getField: () => "Preprint PDF", getNote: () => "" },
    2: { id: 2, isFileAttachment: () => true, attachmentContentType: "application/pdf", getField: () => "[TeXGlot] 中文", getNote: () => JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2602.21186v1" }) },
    3: { id: 3, isFileAttachment: () => true, attachmentContentType: "application/pdf", getField: () => "[TeXGlot] 英文", getNote: () => JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "2602.21186v2" }) },
  };
  const runtime = createZoteroRuntime({ Zotero: { Items: { get: (id: number) => items[id] } } });
  const parent = { getAttachments: () => [1, 2, 3] };
  assert.equal(runtime.findPdfAttachment?.(parent), items[1]);
  assert.equal(runtime.findTranslatedPdf?.(parent), undefined);
  assert.equal(runtime.findTranslatedPdf?.(parent, "2602.21186v2"), items[3]);
  assert.equal(runtime.findTranslatedPdf?.(parent, "2602.21186v3"), undefined);
  assert.equal(runtime.findPdfAttachment?.({ getAttachments: () => [2] }), undefined);
  assert.equal(runtime.findPdfAttachment?.({ getAttachments: () => [1, 3, 4] }), items[1]);
  items[4] = { id: 4, isFileAttachment: () => true, attachmentContentType: "application/pdf", getField: () => "Another original PDF", getNote: () => "" };
  assert.equal(runtime.findPdfAttachment?.({ getAttachments: () => [1, 4] }), undefined);
});

test("registers the native Zotero menu API when available", () => {
  const calls: string[] = [];
  let automaticComparison = true;
  let registration: any;
  const host = {
    rootURI: "file:///texglot-test-addon/",
    Zotero: {
      isMac: true,
      Prefs: {
        get: () => automaticComparison,
        set: (_key: string, value: boolean) => { automaticComparison = value; },
      },
      MenuManager: {
        registerMenu: (value: any) => {
          registration = value;
          return 42;
        },
        unregisterMenu: (value: number) => calls.push(`unregister:${value}`),
      },
    },
    ZoteroPane: { getSelectedItems: () => [{ id: 9 }] },
  };
  const runtime = createZoteroRuntime(host);
  const cleanup = runtime.registerContextMenu?.((items, options) => calls.push(options?.reuseExisting === false ? `retranslate:${items.length}` : `command:${items.length}`));
  assert.equal(registration.target, "main/library/item");
  assert.equal(registration.menus[0].menuType, "menuitem");
  assert.equal(registration.menus[0].icon, "file:///texglot-test-addon/icons/texglot.png");
  const classes = new Set(["zotero-custom-menu-item", "menuitem-iconic"]);
  const menuElem = {
    setAttribute: (name: string, value: string) => calls.push(`${name}:${value}`),
    classList: { toggle: (name: string, enabled: boolean) => enabled ? classes.add(name) : classes.delete(name) },
    style: { setProperty: (name: string, value: string) => calls.push(`style:${name}:${value}`) },
  };
  registration.menus[0].onShowing({}, { items: [{ id: 1 }], menuElem, setVisible: (value: boolean) => calls.push(`visible:${value}`) });
  assert.ok(!classes.has("menuitem-iconic"), "macOS library CSS hides icons with this class");
  assert.ok(classes.has("zotero-custom-menu-item"));
  assert.ok(calls.includes('style:list-style-image:url("file:///texglot-test-addon/icons/texglot.png")'));
  registration.menus[0].onCommand({}, { items: [{ id: 1 }, { id: 2 }] });
  registration.menus[1].onShowing({}, { items: [{ id: 1 }], menuElem, setVisible: () => undefined });
  assert.ok(calls.some((value) => value.includes("双击默认左右对照（已开启）")));
  registration.menus[1].onCommand();
  assert.equal(automaticComparison, false);
  registration.menus[2].onShowing({}, { items: [{ id: 1 }], menuElem, setVisible: () => undefined });
  registration.menus[2].onCommand({}, { items: [{ id: 1 }] });
  assert.ok(calls.includes("label:使用 TeXGlot 重新翻译（保留已有译文）"));
  assert.ok(calls.includes("retranslate:1"));
  cleanup?.();
  assert.ok(calls.includes("label:使用 TeXGlot 翻译并对照阅读"));
  assert.ok(calls.includes("visible:true"));
  assert.ok(calls.includes("command:2"));
  assert.ok(calls.includes("unregister:42"));
});

test("leaves native registration to the menu installer when MenuManager is not ready", () => {
  const runtime = createZoteroRuntime({ Zotero: { MenuManager: undefined } });
  assert.equal(runtime.registerContextMenu?.(() => undefined), undefined);
});

test("unloading before delayed split restoration cannot revive the old add-on", () => {
  let restore: (() => void) | undefined;
  let cancelled = 0;
  let observers = 0;
  const window = {
    Zotero_Tabs: { selectedID: "zotero-pane", _tabs: [] },
    setTimeout: (callback: () => void) => { restore = callback; return 41; },
    clearTimeout: (id: number) => { cancelled = id; },
  };
  const runtime = createZoteroRuntime({
    window,
    Zotero: { Notifier: { registerObserver: () => { observers++; return "observer"; } } },
  });
  runtime.dispose?.();
  assert.equal(cancelled, 41);
  restore?.(); // Also protect against a callback already queued when cancelled.
  assert.equal(observers, 0);
});

test("double-click opens a unique comparison by default and a saved toggle restores native opening", async () => {
  const calls: string[] = [];
  const preferences = new Map<string, boolean>();
  const parent: any = {
    id: 1, isRegularItem: () => true, getAttachments: () => [2, 3],
    getField: (field: string) => field === "url" ? "https://arxiv.org/abs/1706.03762v7" : "",
  };
  const original: any = {
    id: 2, isAttachment: () => true, isFileAttachment: () => true, attachmentContentType: "application/pdf",
    getField: (field: string) => field === "title" ? "Preprint PDF" : field === "url" ? "https://arxiv.org/pdf/1706.03762v7" : "",
  };
  const translated: any = {
    id: 3, isAttachment: () => true, isFileAttachment: () => true, attachmentContentType: "application/pdf",
    getField: (field: string) => field === "title" ? "[TeXGlot] 中文" : "",
    getNote: () => JSON.stringify({ provider: "texglot", artifact: "translated", arxiv_id: "1706.03762v7", language: "简体中文" }),
  };
  const items = new Map([[1, parent], [2, original], [3, translated]]);
  const pane = { onItemTreeActivate: (_event: unknown, selected: any[]) => calls.push(`native:${selected[0].id}`) };
  const nativeActivate = pane.onItemTreeActivate;
  let contextMenu: any;
  const runtime = createZoteroRuntime({
    ZoteroPane: pane,
    Zotero: {
      Prefs: {
        get: (key: string) => preferences.get(key),
        set: (key: string, value: boolean) => preferences.set(key, value),
      },
      Items: { get: (id: number) => items.get(id), getAsync: async (id: number) => items.get(id) },
      MenuManager: {
        registerMenu: (value: any) => { contextMenu = value; return 7; },
        unregisterMenu: () => undefined,
      },
    },
  });
  runtime.readPdfInfo = async () => ({ text: "arXiv:1706.03762v7 [cs.CL]", readable: true });
  runtime.openSplitReader = async (left, right) => { calls.push(`split:${left.id}:${right.id}`); };
  const menuCleanup = runtime.registerContextMenu?.(() => undefined);
  const event = { type: "dblclick", button: 0 };
  pane.onItemTreeActivate(event, [parent]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, ["split:2:3"]);

  const untranslated = { ...parent, id: 4, getAttachments: () => [2] };
  pane.onItemTreeActivate(event, [untranslated]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls.at(-1), "native:4");
  pane.onItemTreeActivate({ ...event, shiftKey: true }, [parent]);
  assert.equal(calls.at(-1), "native:1");

  assert.equal(contextMenu.target, "main/library/item");
  const labels: string[] = [];
  const menuElem: any = { setAttribute: (name: string, value: string) => { if (name === "label") labels.push(value); } };
  contextMenu.menus[1].onShowing({}, { items: [parent], menuElem });
  assert.ok(labels.at(-1)?.includes("已开启"));
  contextMenu.menus[1].onCommand();
  contextMenu.menus[1].onShowing({}, { items: [parent], menuElem });
  assert.ok(labels.at(-1)?.includes("已关闭"));
  pane.onItemTreeActivate(event, [parent]);
  pane.onItemTreeActivate(event, [original]);
  assert.deepEqual(calls, ["split:2:3", "native:4", "native:1", "native:1", "native:2"]);

  runtime.dispose?.();
  menuCleanup?.();
  assert.equal(pane.onItemTreeActivate, nativeActivate);
  pane.onItemTreeActivate(event, [parent]);
  assert.equal(calls.at(-1), "native:1");
});

test("turning off automatic comparison does not reuse an already open split tab", async () => {
  const calls: string[] = [];
  const original = { id: 2, isAttachment: () => true, isFileAttachment: () => true, attachmentContentType: "application/pdf" };
  const parent = { id: 1, isRegularItem: () => true, getBestAttachment: async () => original };
  const tabs: any[] = [
    { id: "zotero-pane", type: "library", data: {} },
    { id: "split-tab", type: "reader", data: { itemID: 2, isSplitView: true } },
  ];
  const window = { Zotero_Tabs: { _tabs: tabs, select: (id: string) => calls.push(`select:${id}`) } };
  const pane = { onItemTreeActivate: (_event: unknown, _items: unknown[]) => calls.push("native") };
  let enabled = false;
  const runtime = createZoteroRuntime({
    window, ZoteroPane: pane,
    Zotero: {
      Prefs: { get: () => enabled },
      Reader: { open: async (id: number, _location: unknown, options: { allowDuplicate: boolean }) => calls.push(`plain:${id}:${options.allowDuplicate}`) },
    },
  });
  runtime.openSplitReader = async () => { throw new Error("must not open comparison"); };
  pane.onItemTreeActivate({ type: "dblclick", button: 0 }, [parent]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, ["plain:2:true"]);

  tabs.push({ id: "plain-tab", type: "reader", data: { itemID: 2 } });
  pane.onItemTreeActivate({ type: "dblclick", button: 0 }, [parent]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, ["plain:2:true", "select:plain-tab"]);

  enabled = true;
  pane.onItemTreeActivate({ type: "dblclick", button: 0 }, [original]);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, ["plain:2:true", "select:plain-tab", "select:plain-tab"], "explicit PDF child opens the plain tab even while auto comparison is on");
  runtime.dispose?.();
});

test("upgrades the legacy menu to native registration after Zotero initialization", async () => {
  const menu = {
    children: [] as any[],
    querySelector: () => null,
    appendChild(node: any) { node.isConnected = true; this.children.push(node); },
  };
  const document = {
    querySelector: (selector: string) => selector === "#zotero-itemmenu" ? menu : null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    createXULElement: () => {
      const node: any = { isConnected: false, setAttribute: () => undefined, addEventListener: () => undefined };
      node.remove = () => {
        node.isConnected = false;
        const index = menu.children.indexOf(node);
        if (index >= 0) menu.children.splice(index, 1);
      };
      return node;
    },
    createElement: () => ({ isConnected: false, setAttribute: () => undefined, addEventListener: () => undefined, remove: () => undefined }),
  } as unknown as Document;
  const host: any = { Zotero: { MenuManager: undefined }, ZoteroPane: { getSelectedItems: () => [] }, document };
  setTimeout(() => {
    host.Zotero.MenuManager = {
      registerMenu: (value: any) => { host.registration = value; return 8; },
      unregisterMenu: () => undefined,
    };
  }, 5);
  const cleanup = installContextMenu(createZoteroRuntime(host));
  await new Promise((resolve) => setTimeout(resolve, 150));
  assert.equal(host.registration?.target, "main/library/item");
  assert.equal(menu.children.length, 0);
  cleanup();
});
