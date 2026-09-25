import type { ZoteroLikeItem, ZoteroRuntime } from "./types.js";
import { NativeSplitReader } from "./split-reader.js";
import { setMenuIcon } from "./menu-icon.js";
import { installStatusColumn } from "./status-column.js";
import { defaultComparisonForParent } from "./menus.js";
import { hasAttachmentFile, isPdfAttachment } from "./arxiv.js";
import { readTranslationMetadata, sameTranslationArtifact } from "./translation-metadata.js";
import { createPdfSourceReader } from "./pdf-source.js";

export type ZoteroHost = {
  Zotero?: any;
  ZoteroPane?: any;
  document?: Document;
  window?: any;
  Services?: any;
  PathUtils?: any;
  IOUtils?: any;
  rootURI?: string;
};

const DOUBLE_CLICK_PREF = "extensions.texglot.openComparisonOnDoubleClick";

function comparisonOnDoubleClick(zotero: any): boolean {
  try { return zotero?.Prefs?.get?.(DOUBLE_CLICK_PREF, true) !== false; }
  catch { return true; }
}

/** Zotero normally reuses the first reader for a PDF, even if that reader is
 * an existing TeXGlot split. With auto comparison disabled, open a plain tab.
 */
async function openNativeWithoutExistingSplit(
  item: ZoteroLikeItem,
  zotero: any,
  mainWindow: any,
  openNormally: () => unknown,
): Promise<void> {
  const tabs = mainWindow?.Zotero_Tabs?._tabs;
  if (!Array.isArray(tabs) || !tabs.some((tab: any) => tab.data?.isSplitView)) {
    openNormally();
    return;
  }
  const attachment = item.isAttachment?.() ? item : await item.getBestAttachment?.();
  if (!attachment || !attachment.id) { openNormally(); return; }
  const matchingTabs = tabs.filter((tab: any) => Number(tab.data?.itemID) === attachment.id);
  if (!matchingTabs.some((tab: any) => tab.data?.isSplitView)) { openNormally(); return; }
  const plainTab = matchingTabs.find((tab: any) => !tab.data?.isSplitView && ["reader", "reader-unloaded"].includes(tab.type));
  if (plainTab) {
    mainWindow.Zotero_Tabs.select(plainTab.id, plainTab.type === "reader");
    return;
  }
  await zotero.Reader.open(attachment.id, null, { allowDuplicate: true });
}

function installDefaultComparison(pane: any, zotero: any, mainWindow: any, runtime: ZoteroRuntime): () => void {
  const nativeActivate = pane?.onItemTreeActivate;
  if (typeof nativeActivate !== "function") return () => undefined;
  let active = true;
  const activate = function (this: any, event: any, items: ZoteroLikeItem[]) {
    let nativeStarted = false;
    const openNormally = () => {
      if (nativeStarted) return;
      nativeStarted = true;
      return nativeActivate.call(this, event, items);
    };
    const item = items?.length === 1 ? items[0] : undefined;
    const regularItem = item?.isRegularItem?.() === true;
    const pdfChild = isPdfAttachment(item);
    if (!active || event?.type !== "dblclick" || event.button !== 0 ||
        event.shiftKey || event.altKey || event.ctrlKey || event.metaKey || !item || (!regularItem && !pdfChild) || !runtime.openSplitReader) {
      return openNormally();
    }
    if (pdfChild || !comparisonOnDoubleClick(zotero)) {
      void openNativeWithoutExistingSplit(item, zotero, mainWindow, openNormally)
        .catch((error) => {
          zotero?.debug?.(`[TeXGlot] plain PDF open failed: ${String(error)}`);
          openNormally();
        });
      return;
    }
    void defaultComparisonForParent(item, runtime).then(async (pair) => {
      if (!active || !pair) return openNormally();
      try { await runtime.openSplitReader!(pair.original, pair.translated); }
      catch (error) {
        if (active) runtime.notify?.(`TeXGlot 对照阅读未能打开：${String(error)}`, "error");
        openNormally();
      }
    }).catch((error) => {
      zotero?.debug?.(`[TeXGlot] default comparison lookup failed: ${String(error)}`);
      openNormally();
    });
  };
  pane.onItemTreeActivate = activate;
  return () => {
    active = false;
    if (pane.onItemTreeActivate === activate) pane.onItemTreeActivate = nativeActivate;
  };
}

function parentId(item: ZoteroLikeItem): number {
  if (item.id === undefined) throw new Error("当前 Zotero 条目没有可用的 ID。");
  return item.id;
}

function translationMarker(item: ZoteroLikeItem) {
  const value = readTranslationMetadata(item);
  return value?.artifact === "translated" ? value : null;
}

/** Adapt the small runtime surface used by the plugin to a real Zotero window. */
export function createZoteroRuntime(host: ZoteroHost = globalThis as unknown as ZoteroHost): ZoteroRuntime {
  const zotero = host.Zotero ?? (globalThis as any).Zotero;
  const mainWindow = host.window
    ?? zotero?.getMainWindow?.()
    ?? host.Services?.wm?.getMostRecentWindow?.("navigator:browser");
  const pane = host.ZoteroPane ?? mainWindow?.ZoteroPane ?? (globalThis as any).ZoteroPane;
  const document = host.document ?? mainWindow?.document ?? pane?.document ?? (globalThis as any).document;
  const iconURI = host.rootURI ? `${host.rootURI}icons/texglot.png` : undefined;
  const io = host.IOUtils ?? (globalThis as any).IOUtils;
  const hashBytes = async (bytes: Uint8Array): Promise<string> => {
    const crypto = mainWindow?.crypto ?? globalThis.crypto;
    const result = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
    return "sha256:" + Array.from(new Uint8Array(result), (byte) => byte.toString(16).padStart(2, "0")).join("");
  };
  const pdfSources = createPdfSourceReader({
    stat: (path) => io.stat(path), read: (path) => io.read(path), hash: hashBytes,
    extract: (id) => zotero.PDFWorker.getFullText(id, 1, true),
  });
  const prompt = host.Services?.prompt ?? (globalThis as any).Services?.prompt;
  const chinese = () => !zotero?.locale || String(zotero.locale).toLowerCase().startsWith("zh");
  let statusColumn: ReturnType<typeof installStatusColumn>;
  try { statusColumn = installStatusColumn(zotero, mainWindow, host.rootURI); }
  catch (error) { zotero?.debug?.(`[TeXGlot] status column failed to start: ${String(error)}`); }
  const splitReader = new NativeSplitReader({
    Zotero: zotero, window: mainWindow,
    Services: host.Services ?? (globalThis as any).Services,
    iconURI,
  });
  // Session restoration creates reader tabs before bootstrap finishes. Give
  // Zotero a short window to restore its tabs, then rebuild any TeXGlot split
  // tab from the persisted left/right attachment IDs.
  const scheduleRestore = mainWindow?.setTimeout ?? (globalThis as any).setTimeout;
  const cancelRestore = mainWindow?.clearTimeout ?? (globalThis as any).clearTimeout;
  let restoreTimer: ReturnType<typeof setTimeout> | undefined;
  if (mainWindow?.Zotero_Tabs && scheduleRestore) {
    restoreTimer = scheduleRestore(() => {
      restoreTimer = undefined;
      splitReader.restoreSavedSplits();
    }, 2500);
  }
  const resolveItem = (id: number): ZoteroLikeItem | undefined => {
    const value = zotero?.Items?.get?.(id);
    return value && typeof value.then !== "function" ? value : undefined;
  };
  const resolveItemAsync = async (id: number): Promise<ZoteroLikeItem | undefined> => {
    const value = await zotero?.Items?.getAsync?.(id);
    return value && typeof value.then !== "function" ? value : resolveItem(id);
  };
  const findAttachment = async (parent: ZoteroLikeItem, note: string): Promise<ZoteroLikeItem | undefined> => {
    const expected = readTranslationMetadata({ getNote: () => note });
    const attachmentIds = parent.getAttachments?.();
    const ids = Array.isArray(attachmentIds)
      ? attachmentIds
      : Object.values(attachmentIds ?? {}).map((id) => typeof id === "number" ? id : Number(id)).filter((id) => Number.isInteger(id) && id > 0);
    for (const id of ids) {
      const attachment = resolveItem(id);
      if (!attachment || attachment.deleted) continue;
      const actual = readTranslationMetadata(attachment);
      if (expected && actual && sameTranslationArtifact(actual, expected) && await hasAttachmentFile(attachment)) {
        if (actual.artifact === "original" && actual.artifact_fingerprint !== (await pdfSources.read(attachment)).fingerprint) continue;
        return attachment;
      }
    }
    return undefined;
  };
  const findPdfAttachment = (parent: ZoteroLikeItem): ZoteroLikeItem | undefined => {
    const attachmentIds = parent.getAttachments?.();
    const ids = Array.isArray(attachmentIds)
      ? attachmentIds
      : Object.values(attachmentIds ?? {}).map((id) => typeof id === "number" ? id : Number(id)).filter((id) => Number.isInteger(id) && id > 0);
    const candidates = ids
      .map((id) => resolveItem(id))
      .filter((item): item is ZoteroLikeItem => Boolean(
        item?.isFileAttachment?.()
        && item.attachmentContentType === "application/pdf"
        && !String(item.getField?.("title") ?? "").startsWith("[TeXGlot]")
        && !translationMarker(item),
      ));
    // A generated translation must never be used as the original. If the
    // parent has several source PDFs, the caller must select one explicitly.
    return candidates.length === 1 ? candidates[0] : undefined;
  };
  const findTranslatedPdf = (parent: ZoteroLikeItem, arxivId?: string): ZoteroLikeItem | undefined => {
    const attachmentIds = parent.getAttachments?.();
    const ids = Array.isArray(attachmentIds)
      ? attachmentIds
      : Object.values(attachmentIds ?? {}).map((id) => typeof id === "number" ? id : Number(id)).filter((id) => Number.isInteger(id) && id > 0);
    const matches: ZoteroLikeItem[] = [];
    for (const id of ids) {
      const attachment = resolveItem(id);
      if (!attachment?.isFileAttachment?.() || attachment.attachmentContentType !== "application/pdf") continue;
      const note = translationMarker(attachment);
      if (note && (!arxivId || note.arxiv_id === arxivId)) matches.push(attachment);
    }
    return matches.length === 1 ? matches[0] : undefined;
  };
  const registerContextMenu: ZoteroRuntime["registerContextMenu"] = (handler) => {
    const menuManager = zotero?.MenuManager;
    if (typeof menuManager?.registerMenu !== "function") return undefined;
    const registrationID = menuManager.registerMenu({
      menuID: "texglot-translate-menu",
      pluginID: "zotero@texglot.org",
      target: "main/library/item",
      menus: [{
        menuType: "menuitem",
        ...(iconURI ? { icon: iconURI } : {}),
        onShowing: (_event: unknown, context: { items?: ZoteroLikeItem[]; menuElem?: HTMLElement; setVisible?: (visible: boolean) => void }) => {
          context.menuElem?.setAttribute("label", "使用 TeXGlot 翻译并对照阅读");
          if (context.menuElem) setMenuIcon(context.menuElem, iconURI, Boolean(zotero?.isMac));
          const items = Array.isArray(context.items) ? context.items : (pane?.getSelectedItems?.() ?? []);
          context.setVisible?.(items.length > 0);
        },
        onCommand: (_event: unknown, context: { items?: ZoteroLikeItem[] }) => {
          const items = Array.isArray(context.items) ? context.items : (pane?.getSelectedItems?.() ?? []);
          handler(items);
        },
      }, {
        menuType: "menuitem",
        ...(iconURI ? { icon: iconURI } : {}),
        onShowing: (_event: unknown, context: { items?: ZoteroLikeItem[]; menuElem?: HTMLElement; setVisible?: (visible: boolean) => void }) => {
          const menuElem = context.menuElem;
          if (menuElem) {
            const enabled = comparisonOnDoubleClick(zotero);
            const chinese = !zotero?.locale || String(zotero.locale).toLowerCase().startsWith("zh");
            menuElem.setAttribute("label", chinese
              ? `TeXGlot：双击默认左右对照（${enabled ? "已开启" : "已关闭"}）`
              : `TeXGlot: Open comparison on double-click (${enabled ? "On" : "Off"})`);
            setMenuIcon(menuElem, iconURI, Boolean(zotero?.isMac));
          }
          const items = Array.isArray(context.items) ? context.items : (pane?.getSelectedItems?.() ?? []);
          context.setVisible?.(items.length > 0);
        },
        onCommand: () => zotero?.Prefs?.set?.(DOUBLE_CLICK_PREF, !comparisonOnDoubleClick(zotero), true),
      }, {
        menuType: "menuitem",
        ...(iconURI ? { icon: iconURI } : {}),
        onShowing: (_event: unknown, context: { items?: ZoteroLikeItem[]; menuElem?: HTMLElement; setVisible?: (visible: boolean) => void }) => {
          const chinese = !zotero?.locale || String(zotero.locale).toLowerCase().startsWith("zh");
          context.menuElem?.setAttribute("label", chinese
            ? "使用 TeXGlot 重新翻译（保留已有译文）"
            : "Retranslate with TeXGlot (keep existing translations)");
          if (context.menuElem) setMenuIcon(context.menuElem, iconURI, Boolean(zotero?.isMac));
          const items = Array.isArray(context.items) ? context.items : (pane?.getSelectedItems?.() ?? []);
          context.setVisible?.(items.length > 0);
        },
        onCommand: (_event: unknown, context: { items?: ZoteroLikeItem[] }) => {
          const items = Array.isArray(context.items) ? context.items : (pane?.getSelectedItems?.() ?? []);
          handler(items, { reuseExisting: false });
        },
      }],
    });
    return () => {
      if (registrationID !== undefined && registrationID !== null) menuManager.unregisterMenu?.(registrationID);
    };
  };
  let removeDefaultComparison: () => void = () => undefined;
  const runtime: ZoteroRuntime = {
    document,
    iconURI,
    isMac: Boolean(zotero?.isMac),
    dispose: () => {
      if (restoreTimer !== undefined) cancelRestore?.(restoreTimer);
      restoreTimer = undefined;
      removeDefaultComparison();
      pdfSources.clear();
      statusColumn?.dispose();
      splitReader.shutdown();
    },
    setTranslationActivity: statusColumn?.setActivity,
    registerContextMenu,
    resolveItem,
    resolveItemAsync,
    readPdfInfo: pdfSources.read,
    hashBytes,
    chooseAttachment: async (items) => {
      if (!prompt?.select) throw new Error("无法打开附件选择器，请直接选中要翻译的 PDF 附件。");
      const selected = { value: 0 };
      const labels = items.map(({ item, version }) => {
        let title = item.attachmentFilename || "PDF";
        try { title = String(item.getField?.("title") || title); } catch { /* optional */ }
        return `${title}${version ? ` · arXiv ${version}` : ""}`;
      });
      const accepted = prompt.select(mainWindow ?? null, "TeXGlot", chinese()
        ? "这篇文献有多个 PDF，请选择要翻译和对照阅读的原文。"
        : "Choose the original PDF to translate and compare.", labels, selected);
      return accepted ? items[selected.value]?.item : undefined;
    },
    confirmOfficialSource: async (id, canChoose) => {
      if (!prompt?.confirmEx) return "cancel";
      const flags = prompt.BUTTON_POS_0 * prompt.BUTTON_TITLE_IS_STRING
        + prompt.BUTTON_POS_1 * prompt.BUTTON_TITLE_IS_STRING
        + (canChoose ? prompt.BUTTON_POS_2 * prompt.BUTTON_TITLE_IS_STRING : 0);
      const version = id.match(/v\d+$/i)?.[0] ?? id;
      const result = prompt.confirmEx(mainWindow ?? null, "TeXGlot", chinese()
        ? `现有 PDF 未标明版本。使用 arXiv ${id} 的配套原文继续？原有 PDF 和批注会保留。`
        : `The PDF's version is unknown. Continue with the matching original for arXiv ${id}? Your existing PDF and annotations will be kept.`,
      flags, chinese() ? `使用 arXiv ${version}` : `Use arXiv ${version}`, chinese() ? "取消" : "Cancel",
      canChoose ? (chinese() ? "选择其他 PDF" : "Choose another PDF") : null, null, {});
      return result === 0 ? "official" : result === 2 ? "choose" : "cancel";
    },
    findAttachment,
    findPdfAttachment,
    findTranslatedPdf,
    openSplitReader: async (original, translated) => {
      await splitReader.open(original, translated, { primarySide: "right", activeSide: "right" });
    },
    readFile: async (path) => {
      const ioUtils = host.IOUtils ?? (globalThis as any).IOUtils;
      if (!ioUtils?.read) throw new Error("Zotero 文件读取 API 不可用。");
      return new Uint8Array(await ioUtils.read(path));
    },
    getSelectedItems: () => pane?.getSelectedItems?.() ?? [],
    notify: (message, level = "info") => {
      const prefix = `[TeXGlot${level === "error" ? " error" : ""}] ${message}`;
      zotero?.debug?.(prefix);

      // Poll updates arrive about once a second. Keep those in the debug log
      // rather than opening an always-on-top window for every update.
      const isPollUpdate = /^TeXGlot\s+[^\s:]+:\s/.test(message);
      if (level === "info" && isPollUpdate) return;

      // Zotero 7/8/9 removed the old pane error banner. Calling the legacy
      // displayErrorMessage() now invokes Zotero.crash(), which produces the
      // misleading "Please restart Zotero" dialog. Use the supported alert
      // API for actionable errors and keep informational updates non-modal.
      if (level === "error") {
        try {
          if (typeof zotero?.alert === "function") {
            zotero.alert(mainWindow ?? null, "TeXGlot", message);
            return;
          }
          if (typeof host.Services?.prompt?.alert === "function") {
            host.Services.prompt.alert(mainWindow ?? null, "TeXGlot", message);
            return;
          }
        } catch (error) {
          zotero?.debug?.(`[TeXGlot error] failed to show alert: ${String(error)}`);
        }
      }

      // Zotero 9 does not expose ZoteroPane.displayInfoMessage(). Show a
      // short, non-modal notification for submission and terminal outcomes.
      try {
        if (level === "info" && typeof zotero?.ProgressWindow === "function") {
          const progress = new zotero.ProgressWindow({ window: mainWindow ?? null });
          progress.changeHeadline("TeXGlot");
          const row = new progress.ItemProgress(null, message);
          row.setProgress(100);
          progress.show();
          progress.startCloseTimer(3200);
          return;
        }
        pane?.displayInfoMessage?.(message);
      } catch (error) {
        zotero?.debug?.(`[TeXGlot] failed to show notification: ${String(error)}`);
      }
    },
    openSettings: () => {
      try { zotero?.launchURL?.("http://127.0.0.1:8765/?settings=1"); } catch { /* optional */ }
    },
    openReader: (taskId, mode = "comparison", baseUrl = "http://127.0.0.1:8765") => {
      try { zotero?.launchURL?.(`${baseUrl.replace(/\/+$/, "")}/?reader=${encodeURIComponent(taskId)}&mode=${encodeURIComponent(mode)}`); } catch { /* optional */ }
    },
    importAttachment: async (bytes, options) => {
      if (!zotero?.Attachments?.importFromFile) throw new Error("Zotero 附件 API 不可用。");
      const tempRoot = zotero.getTempDirectory?.()?.path;
      const pathUtils = host.PathUtils ?? (globalThis as any).PathUtils;
      const ioUtils = host.IOUtils ?? (globalThis as any).IOUtils;
      if (!tempRoot || !pathUtils?.join || !ioUtils?.write) throw new Error("Zotero 临时文件 API 不可用。");
      const filename = `texglot-${Date.now()}-${Math.random().toString(16).slice(2)}.${options.extension}`;
      const path = pathUtils.join(tempRoot, filename);
      await ioUtils.write(path, bytes);
      try {
        const file = zotero.File?.pathToFile?.(path) ?? path;
        let attachment;
        try {
          attachment = await zotero.Attachments.importFromFile({ file, parentItemID: parentId(options.parent), title: options.title });
        } catch (error) {
          // Zotero 6-compatible fallback is harmless for hosts that expose the
          // older positional signature; Zotero 8 uses the object form above.
          attachment = await zotero.Attachments.importFromFile(file, parentId(options.parent));
        }
        if (attachment?.setField) attachment.setField("title", options.title.replace(/\.(pdf|zip)$/i, ""));
        if (attachment?.setNote) attachment.setNote(options.note);
        await attachment?.saveTx?.();
        return attachment;
      } finally {
        await ioUtils.remove?.(path, { ignoreAbsent: true });
      }
    },
  };
  removeDefaultComparison = installDefaultComparison(pane, zotero, mainWindow, runtime);
  return runtime;
}
