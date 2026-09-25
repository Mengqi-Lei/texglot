import vm from "node:vm";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const bootstrap = await readFile(join(root, "addon/bootstrap.js"), "utf8");
const bundle = await readFile(join(root, ".scaffold/package/dist/addon.js"), "utf8");
const menu = {
  children: [],
  querySelector(selector) { return this.children.find((node) => `#${node.id}` === selector) ?? null; },
  appendChild(node) { node.isConnected = true; this.children.push(node); },
};
let menuItemsCreated = 0;
const document = {
  querySelector(selector) { return selector === "#zotero-itemmenu" ? menu : null; },
  addEventListener() {},
  removeEventListener() {},
  createXULElement() {
    menuItemsCreated++;
    return {
      attrs: {},
      classList: { toggle() {} },
      style: { setProperty(key, value) { this[key] = value; } },
      isConnected: false,
      setAttribute(key, value) { this.attrs[key] = value; },
      addEventListener() {},
      remove() { menu.children = menu.children.filter((node) => node !== this); this.isConnected = false; },
    };
  },
  createElement() { return this.createXULElement(); },
};
const window = { document, ZoteroPane: { getSelectedItems: () => [] } };
const zotero = { getMainWindow: () => window, debug() {} };
const sandbox = {
  Services: {
    scriptloader: { loadSubScript(_uri, scope) { vm.runInNewContext(bundle, scope); } },
    wm: { getMostRecentWindow: () => window },
  },
  Zotero: zotero,
  ZoteroPane: window.ZoteroPane,
  document,
  PathUtils: { join: (...parts) => parts.join("/") },
  IOUtils: {},
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  AbortController,
  Headers,
  fetch,
  TextDecoder,
  Blob,
  atob,
  btoa,
};

vm.runInNewContext(bootstrap, sandbox);
await sandbox.startup({ resourceURI: { spec: "file:///texglot-test-addon/" } }, 1);
if (typeof sandbox.texglotScope?.atob !== "function") throw new Error("Image decoding was not exposed to the add-on scope");
if (typeof sandbox.texglotScope?.Blob !== "function") throw new Error("Image annotation storage was not exposed to the add-on scope");
if (menu.children.length !== 2 || menu.children[0].attrs.label !== "使用 TeXGlot 翻译并对照阅读"
    || menu.children[1].attrs.label !== "使用 TeXGlot 重新翻译（保留已有译文）") {
  throw new Error("Zotero context menu was not registered");
}
if (menu.children[0].style["list-style-image"] !== 'url("file:///texglot-test-addon/icons/texglot.png")') {
  throw new Error("Zotero context menu did not receive the shared TeXGlot icon");
}
await sandbox.onMainWindowLoad({ window });
if (menuItemsCreated !== 2) throw new Error("Repeated window startup recreated the menu and disposed live readers");
await sandbox.onMainWindowUnload({ window });
if (menu.children.length !== 0) throw new Error("Window shutdown did not remove its menu");
await sandbox.onMainWindowLoad({ window });
if (menuItemsCreated !== 4 || menu.children.length !== 2) throw new Error("Window reopen did not register one fresh menu");
sandbox.shutdown({}, 1);
if (menu.children.length !== 0) throw new Error("Add-on shutdown left a Zotero menu behind");
console.log("Zotero bootstrap smoke: passed");
