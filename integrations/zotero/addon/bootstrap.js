/*
 * TeXGlot Zotero bootstrap entry point.
 * The generated dist/addon.js is loaded only after Zotero has created the
 * add-on scope. This keeps the source bundle independent of Zotero globals
 * and makes shutdown safe when Zotero is closing.
 */
var texglotScope = null;
var texglotData = null;
var texglotStopped = false;
var texglotWindowStarts = new WeakMap();

function loadBundle(data) {
  if (texglotScope) return texglotScope;
  // loadSubScript executes in the supplied scope, so copy the standard web
  // primitives used by the bridge explicitly. Zotero's chrome global exposes
  // these, but an empty sandbox object would otherwise hide them from
  // `globalThis` inside the bundled IIFE.
  texglotScope = {
    rootURI: data.rootURI ?? data.resourceURI?.spec,
    fetch: globalThis.fetch,
    Headers: globalThis.Headers,
    AbortController: globalThis.AbortController,
    TextDecoder: globalThis.TextDecoder,
    Blob: globalThis.Blob,
    atob: globalThis.atob,
    btoa: globalThis.btoa,
    Components: globalThis.Components,
    ChromeUtils: globalThis.ChromeUtils,
    IOUtils: globalThis.IOUtils,
    PathUtils: globalThis.PathUtils,
    Services: globalThis.Services,
    console: globalThis.console,
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    setInterval: globalThis.setInterval,
    clearInterval: globalThis.clearInterval
  };
  // Zotero's supported bootstrap pattern makes the supplied object the
  // bundle's global root. Without this self-reference, `globalThis` inside
  // the compiled IIFE can resolve to the parent chrome scope instead.
  texglotScope._globalThis = texglotScope;
  const uri = `${texglotScope.rootURI}dist/addon.js`;
  try {
    Services.scriptloader.loadSubScript(uri, texglotScope, "UTF-8");
    return texglotScope;
  } catch (error) {
    texglotScope = null;
    throw error;
  }
}

function ensureServices() {
  if (typeof Services === "undefined") {
    const imported = ChromeUtils.importESModule("resource://gre/modules/Services.sys.mjs");
    globalThis.Services = imported.Services;
  }
}

function getMainWindow(explicitWindow) {
  return explicitWindow
    ?? (typeof Zotero !== "undefined" && Zotero.getMainWindow ? Zotero.getMainWindow() : null)
    ?? Services.wm.getMostRecentWindow("navigator:browser");
}

async function startForWindow(data, mainWindow) {
  if (texglotStopped || !data || !mainWindow) return;
  const existing = texglotWindowStarts.get(mainWindow);
  if (existing) return existing;
  const start = Promise.resolve().then(async () => {
    const bundle = loadBundle(data);
    const api = bundle.TeXGlotZotero || bundle;
    await api.startup?.({
      Zotero: typeof Zotero !== "undefined" ? Zotero : undefined,
      Services: typeof Services !== "undefined" ? Services : undefined,
      ZoteroPane: mainWindow.ZoteroPane,
      document: mainWindow.document,
      window: mainWindow,
      PathUtils: typeof PathUtils !== "undefined" ? PathUtils : undefined,
      IOUtils: typeof IOUtils !== "undefined" ? IOUtils : undefined,
      rootURI: texglotScope.rootURI
    });
  });
  texglotWindowStarts.set(mainWindow, start);
  try {
    await start;
  } catch (error) {
    texglotWindowStarts.delete(mainWindow);
    // A startup error must not make Zotero disable the whole add-on. Keep the
    // failure visible in the parent process so it can be diagnosed safely.
    console.error("[TeXGlot] startup failed", error);
  }
}

async function startup(data, reason) {
  const rootURI = data?.rootURI ?? data?.resourceURI?.spec;
  texglotData = { ...data, rootURI };
  texglotStopped = false;
  ensureServices();
  if (typeof Zotero !== "undefined" && Zotero.initializationPromise) {
    await Zotero.initializationPromise;
  }
  await startForWindow(texglotData, getMainWindow());
}

async function onMainWindowLoad({ window }) {
  ensureServices();
  await startForWindow(texglotData, getMainWindow(window));
}

function onMainWindowUnload({ window }) {
  const api = texglotScope?.TeXGlotZotero || texglotScope;
  api?.shutdownWindow?.(window);
  texglotWindowStarts.delete(window);
}

function shutdown(data, reason) {
  if (typeof APP_SHUTDOWN !== "undefined" && reason === APP_SHUTDOWN) return;
  texglotStopped = true;
  const api = texglotScope?.TeXGlotZotero || texglotScope;
  api?.shutdown?.();
  texglotWindowStarts = new WeakMap();
  texglotScope = null;
  texglotData = null;
}

function install() {}
function uninstall() {}
