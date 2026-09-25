import type { ZoteroLikeItem } from "./types.js";
import { setMenuIcon } from "./menu-icon.js";

/**
 * A small, clean-room native Zotero split reader.
 *
 * The implementation uses Zotero's public reader entry point and the same
 * embedded-reader contract exposed by Zotero's own reader.html. It is kept
 * separate from the translation bridge so the reader can be tested and
 * replaced without changing source selection or task semantics.
 */

type Side = "left" | "right";

export interface SplitReaderHost {
  Zotero?: any;
  window?: any;
  Services?: any;
  iconURI?: string;
}

export interface SplitReaderOptions {
  primarySide?: Side;
  activeSide?: Side;
  sync?: boolean;
  splitRatio?: number;
  tabID?: string;
}

interface SplitState {
  tabID: string;
  container: any;
  leftBrowser: any;
  rightBrowser: any;
  leftPopupset: any;
  rightPopupset: any;
  leftItem: any;
  rightItem: any;
  nativeReader: any;
  primarySide: Side;
  activeSide: Side;
  syncEnabled: boolean;
  syncPaused: boolean;
  leftViewState: any;
  rightViewState: any;
  leftSecondaryViewState: any;
  rightSecondaryViewState: any;
  leftViewer: Element | null;
  rightViewer: Element | null;
  syncControl: any;
  primaryControl: any;
  controlBar: any;
  scrollRAF: number | null;
  pendingSourceSide: Side | null;
  inputSide: Side;
  suppressSide: Side | null;
  persistTimer: number | null;
  positionSaveFailed: boolean;
  rightAnnotationIds: Map<number, string>;
  rightAnnotationRefresh: Promise<void>;
  splitRatio: number;
  dragOverlay: HTMLElement | null;
  finishDrag: (() => void) | null;
  listeners: Array<{ target: EventTarget; type: string; listener: EventListener; options?: any }>;
  syncListeners: Array<{ target: EventTarget; type: string; listener: EventListener; options?: any }>;
  timers: number[];
  cleaning: boolean;
}

function isPdf(item: any): boolean {
  return Boolean(
    item?.isFileAttachment?.() &&
      String(item.attachmentContentType || "") === "application/pdf",
  );
}

function itemTitle(item: any): string {
  return String(item?.getField?.("title") || item?.attachmentFilename || "PDF").trim();
}

function escapeHTML(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function safePref(zotero: any, key: string, fallback: any): any {
  try {
    const value = zotero?.Prefs?.get?.(key);
    return value === undefined || value === null ? fallback : value;
  } catch {
    return fallback;
  }
}

export class NativeSplitReader {
  private readonly states = new Map<string, SplitState>();
  private notifierID: string | null = null;
  private restoreTitleHook: (() => void) | null = null;
  private restoreStarted = false;
  private stopped = false;
  private readonly opening = new Map<string, Promise<void>>();
  private readonly attachmentWrites = new Map<number, Promise<void>>();
  private readonly reportedErrors = new WeakSet<object>();

  constructor(private readonly host: SplitReaderHost = {}) {}

  private assertActive(): void {
    if (this.stopped) throw new Error("TeXGlot 分屏阅读器已关闭。");
  }

  private get zotero(): any {
    return this.host.Zotero ?? (globalThis as any).Zotero;
  }

  private get mainWindow(): any {
    return this.host.window ?? this.zotero?.getMainWindow?.() ?? (globalThis as any).window;
  }

  async open(
    original: ZoteroLikeItem,
    translated: ZoteroLikeItem,
    options: SplitReaderOptions = {},
  ): Promise<void> {
    this.assertActive();
    if (!isPdf(original) || !isPdf(translated)) {
      throw new Error("分屏阅读需要两个有效的 PDF 附件。");
    }
    if (!original.id || !translated.id) {
      throw new Error("分屏阅读附件缺少 Zotero 条目 ID。");
    }

    const pairKey = `${original.id}:${translated.id}:${options.tabID ?? "new"}`;
    const pending = this.opening.get(pairKey);
    if (pending) return pending;
    const operation = this.openPair(original, translated, options);
    this.opening.set(pairKey, operation);
    try { await operation; } finally { this.opening.delete(pairKey); }
  }

  private async openPair(original: ZoteroLikeItem, translated: ZoteroLikeItem, options: SplitReaderOptions): Promise<void> {
    const existingState = [...this.states.values()].find((candidate) =>
      String(candidate.leftItem?.id) === String(original.id)
      && String(candidate.rightItem?.id) === String(translated.id)
      && (!options.tabID || candidate.tabID === options.tabID),
    );
    if (existingState) {
      this.mainWindow.Zotero_Tabs?.select?.(existingState.tabID, true);
      this.focusSide(existingState, existingState.activeSide);
      return;
    }

    this.ensureNotifier();
    this.ensureTitleHook();

    // If the translated reader is the tab currently visible to the user,
    // preserve its position when entering comparison. Otherwise the source
    // reader's saved position is the best available anchor.
    const selectedTabID = this.mainWindow?.Zotero_Tabs?.selectedID;
    const selectedReader = this.zotero?.Reader?._readers?.find?.((candidate: any) =>
      String(candidate?.tabID) === String(selectedTabID) && String(candidate?.itemID) === String(translated.id),
    );
    const selectedTranslatedState = selectedReader ? await this.getReaderViewState(selectedReader) : null;
    this.assertActive();

    // Zotero.Reader.open() returns undefined when a reader tab for the
    // attachment is already loaded (it merely selects that tab). Reuse that
    // live instance instead of treating normal tab de-duplication as failure.
    const existingReader = this.zotero?.Reader?._readers?.find?.((candidate: any) =>
      String(candidate?.itemID) === String(original.id) && candidate?.tabID
      && (!options.tabID || String(candidate.tabID) === options.tabID),
    );
    const reader = existingReader ?? await this.zotero?.Reader?.open?.(original.id, null, { allowDuplicate: true, ...(options.tabID ? { tabID: options.tabID } : {}) });
    this.assertActive();
    if (!reader) throw new Error("无法打开原文 PDF 阅读器。");
    await this.waitForReaderReady(reader);
    this.assertActive();

    const tabID = String(reader.tabID);
    if (this.states.has(tabID)) this.cleanup(tabID);

    const container = this.mainWindow?.document?.getElementById?.(tabID);
    if (!container) throw new Error("找不到 Zotero 阅读器标签页容器。");
    const nativeSnapshot = {
      _tabContainer: reader._tabContainer,
      _iframe: reader._iframe,
      _iframeWindow: reader._iframeWindow,
      _internalReader: reader._internalReader,
      _popupset: reader._popupset,
    };

    const leftViewState = options.tabID ? this.savedViewState(options.tabID, "left") ?? await this.getReaderViewState(reader) : await this.getReaderViewState(reader);
    const comparisonViewState = (options.tabID ? this.savedViewState(options.tabID, "right") : null) ?? selectedTranslatedState ?? leftViewState;
    this.assertActive();
    await this.closeReaderWithoutClosingTab(reader);
    this.assertActive();

    const newContainer = container.cloneNode(false) as any;
    container.parentNode?.replaceChild(newContainer, container);
    this.installContainerMethods(newContainer);

    const leftBrowser = this.createBrowser();
    const rightBrowser = this.createBrowser();
    const leftPopupset = this.mainWindow.document.createXULElement("popupset");
    const rightPopupset = this.mainWindow.document.createXULElement("popupset");
    const resizer = this.createResizer();
    const row = this.mainWindow.document.createXULElement("hbox");
    row.style.display = "flex";
    row.style.flexDirection = "row";
    row.style.flex = "1 1 auto";
    row.style.width = "100%";
    row.style.height = "calc(100% - 30px)";
    row.style.minWidth = "0";
    row.style.overflow = "hidden";
    row.append(leftBrowser, resizer, rightBrowser);
    newContainer.style.display = "flex";
    newContainer.style.flexDirection = "column";
    newContainer.append(row, leftPopupset, rightPopupset);

    const state: SplitState = {
      tabID,
      container: newContainer,
      leftBrowser,
      rightBrowser,
      leftPopupset,
      rightPopupset,
      leftItem: original,
      rightItem: translated,
      nativeReader: reader,
      primarySide: options.primarySide ?? "right",
      activeSide: options.activeSide ?? "right",
      syncEnabled: options.sync !== false,
      syncPaused: false,
      leftViewState,
      rightViewState: null,
      leftSecondaryViewState: options.tabID ? this.savedViewState(options.tabID, "left", true) : null,
      rightSecondaryViewState: options.tabID ? this.savedViewState(options.tabID, "right", true) : null,
      leftViewer: null,
      rightViewer: null,
      syncControl: null,
      primaryControl: null,
      controlBar: null,
      scrollRAF: null,
      pendingSourceSide: null,
      inputSide: options.activeSide ?? options.primarySide ?? "right",
      suppressSide: null,
      persistTimer: null,
      positionSaveFailed: false,
      rightAnnotationIds: this.annotationIdMap(translated),
      rightAnnotationRefresh: Promise.resolve(),
      splitRatio: Math.min(0.8, Math.max(0.2, options.splitRatio ?? 0.5)),
      dragOverlay: null,
      finishDrag: null,
      listeners: [],
      syncListeners: [],
      timers: [],
      cleaning: false,
    };
    this.states.set(tabID, state);
    this.installControls(state, newContainer, row);
    this.installResizer(state, resizer, row);
    this.applySplitRatio(state);

    try {
      await Promise.all([
        this.initializeReader(state, "left", original, leftBrowser, leftPopupset, leftViewState),
        this.initializeReader(state, "right", translated, rightBrowser, rightPopupset, comparisonViewState),
      ]);
      this.assertActive();
      this.rebindNativeReader(state);
      this.installFocusListeners(state);
      this.cacheViewerContainers(state);
      this.installSyncListeners(state);
      this.updateTabData(state);
      this.renameTab(state);
      if (state.syncEnabled) {
        await this.syncFromPrimary(state);
      }
      // Reader.open() may have reused a background tab. Selecting the native
      // split tab here makes the command's result immediately visible.
      if (!options.tabID) this.mainWindow.Zotero_Tabs?.select?.(tabID, true);
      this.focusSide(state, state.activeSide);
    } catch (error) {
      // A newer add-on instance may have taken over this tab after shutdown.
      // Only the instance that still owns the split may restore native fields.
      if (this.states.get(tabID) === state) {
        this.cleanup(tabID);
        try {
          newContainer.parentNode?.replaceChild(container, newContainer);
          Object.assign(reader, nativeSnapshot);
          reader._blockingObserver?.register?.(nativeSnapshot._iframe);
        } catch {
          // The original tab may already have been closed during loading.
        }
      }
      throw error;
    }
  }

  shutdown(): void {
    if (this.stopped) return;
    this.stopped = true;
    // During an add-on reload, leave already opened PDFs visible. The next
    // instance can rebuild a selected split from tab metadata; blanking the
    // browsers here would strand the user in an empty reader tab.
    for (const tabID of [...this.states.keys()]) this.cleanup(tabID, false);
    if (this.notifierID) {
      try {
        this.zotero?.Notifier?.unregisterObserver?.(this.notifierID);
      } catch {
        // Zotero may already be shutting down.
      }
      this.notifierID = null;
    }
    this.restoreTitleHook?.();
    this.restoreTitleHook = null;
  }

  /** A detached ReaderTab can outlive its Zotero tab and intercept later PDF opens. */
  private pruneOrphanedReaders(only?: any): void {
    const readers = this.zotero?.Reader?._readers;
    if (!Array.isArray(readers)) return;
    for (const reader of only ? [only] : [...readers]) {
      try {
        if (!reader?.tabID || !reader._window) continue;
        const readerWindow = reader._window;
        let orphaned = false;
        try {
          if (readerWindow.closed) orphaned = true;
          else {
            const tabs = readerWindow.Zotero_Tabs?._tabs;
            orphaned = Array.isArray(tabs) && !tabs.some((tab: any) => String(tab.id) === String(reader.tabID));
          }
        } catch { orphaned = true; /* a dead window cannot own a live tab */ }
        if (!orphaned) continue;
        const index = readers.indexOf(reader);
        if (index < 0) continue;
        readers.splice(index, 1);
        try { reader.uninit?.(); }
        catch (error) { this.zotero?.debug?.(`[TeXGlot] stale PDF reader cleanup: ${String(error)}`); }
      } catch (error) {
        this.zotero?.debug?.(`[TeXGlot] stale PDF reader inspection: ${String(error)}`);
      }
    }
  }

  /** Rebuild split tabs restored by Zotero's session manager after startup. */
  restoreSavedSplits(): void {
    if (this.stopped || this.restoreStarted) return;
    this.pruneOrphanedReaders();
    this.ensureNotifier();
    this.ensureTitleHook();
    this.restoreStarted = true;
    const tabs = this.mainWindow?.Zotero_Tabs?._tabs;
    if (!Array.isArray(tabs)) return;
    // Zotero restores reader tabs as unloaded. Rebuilding every tab here
    // creates extra loaded tabs and races Zotero's own tab loader. Rebuild the
    // selected split only; other tabs are restored when Zotero loads them.
    const selectedID = String(this.mainWindow?.Zotero_Tabs?.selectedID || "");
    const selected = tabs.find((tab: any) => String(tab?.id) === selectedID);
    if (selected?.data?.isSplitView && selected.type === "reader") {
      void this.restoreTab(selectedID).catch((error) => this.zotero?.debug?.(`[TeXGlot] 恢复分屏阅读失败：${String(error)}`));
    }
  }

  private async restoreTab(tabID: string): Promise<void> {
    if (this.stopped || this.states.has(tabID)) return;
    const tab = this.mainWindow?.Zotero_Tabs?._tabs?.find?.((candidate: any) => String(candidate.id) === tabID);
    const data = tab?.data;
    if (!data?.isSplitView || tab?.type !== "reader" || !data.leftItemID || !data.rightItemID) return;
    const original = this.zotero?.Items?.get?.(data.leftItemID);
    const translated = this.zotero?.Items?.get?.(data.rightItemID);
    if (!isPdf(original) || !isPdf(translated)) return;
    await this.open(original, translated, {
      primarySide: data.primarySide === "left" ? "left" : "right",
      activeSide: data.activeSide === "left" ? "left" : "right",
      sync: data.syncEnabled !== false,
      splitRatio: Number(data.splitRatio) || 0.5,
      tabID,
    });
  }

  private ensureNotifier(): void {
    if (this.stopped || this.notifierID || typeof this.zotero?.Notifier?.registerObserver !== "function") return;
    this.notifierID = this.zotero.Notifier.registerObserver(
      {
        notify: (action: string, type: string, ids: Array<string | number>, extraData: any) => {
          // Zotero's tab notifier uses `close` in current releases; older
          // hosts used `delete`. Accept both so detached browser listeners do
          // not survive a closed split tab.
          if (type === "item") {
            this.handleRightItemNotification(action, ids, extraData);
            return;
          }
          if (type !== "tab") return;
          if (action === "load") {
            for (const id of ids) void this.restoreTab(String(id)).catch((error) => this.zotero?.debug?.(`[TeXGlot] 恢复分屏阅读失败：${String(error)}`));
            return;
          }
          if (action === "select") {
            for (const state of this.states.values()) {
              if (state.tabID !== String(ids[0]) && !state.cleaning) this.updateTabData(state);
            }
            const selected = this.states.get(String(ids[0]));
            if (selected && !selected.cleaning) {
              this.mainWindow.setTimeout(() => {
                if (!selected.cleaning) this.renameTab(selected);
              }, 0);
            }
            for (const id of ids) void this.restoreTab(String(id)).catch((error) => this.zotero?.debug?.(`[TeXGlot] 恢复分屏阅读失败：${String(error)}`));
            return;
          }
          if (action !== "delete" && action !== "close") return;
          for (const id of ids) {
            // Zotero's own tab observer must first flush and uninitialize the
            // native ReaderTab. Its callback may run after ours.
            this.mainWindow.setTimeout(() => this.cleanup(String(id)), 0);
          }
        },
      },
      ["tab", "item"],
      "texglot-native-split-reader",
      50,
    );
  }

  private handleRightItemNotification(action: string, ids: Array<string | number>, extraData: any): void {
    if (!["add", "modify", "delete", "trash"].includes(action)) return;
    const affected = new Set(ids.map((id) => Number(id)).filter(Number.isInteger));
    for (const state of this.states.values()) {
      if (state.cleaning) continue;
      if ((action === "delete" && affected.has(state.rightItem.id)) ||
          (action === "trash" && (affected.has(state.rightItem.id) || affected.has(state.rightItem.parentItemID)))) {
        this.mainWindow?.Zotero_Tabs?.close?.(state.tabID);
        continue;
      }
      if (!["add", "modify", "delete"].includes(action)) continue;
      const previous = state.rightAnnotationIds ?? new Map<number, string>();
      const current = this.annotationIdMap(state.rightItem);
      const removedKeys = [...previous]
        .filter(([id]) => affected.has(id) && (action === "delete" || !current.has(id)))
        .map(([, key]) => key);
      for (const id of affected) if (action === "delete") current.delete(id);
      const ownInstanceID = state.nativeReader?._instanceID;
      const changedKeys = new Set([...current]
        .filter(([id]) => affected.has(id) && action !== "delete" && !(ownInstanceID && extraData?.[id]?.instanceID === ownInstanceID))
        .map(([, key]) => key));
      state.rightAnnotationIds = current;
      if (!removedKeys.length && !changedKeys.size) continue;
      state.rightAnnotationRefresh = (state.rightAnnotationRefresh ?? Promise.resolve())
        .catch(() => undefined)
        .then(async () => {
          if (state.cleaning) return;
          const reader = this.internalReader(state.rightBrowser);
          if (!reader) return;
          if (removedKeys.length) reader.unsetAnnotations?.(this.cloneInto(removedKeys, state.rightBrowser.contentWindow));
          if (changedKeys.size) {
            const annotations = (await this.loadAnnotations(state.rightItem))
              .filter((annotation: any) => changedKeys.has(String(annotation.id)));
            if (annotations.length) reader.setAnnotations?.(this.cloneInto(annotations, state.rightBrowser.contentWindow));
          }
        })
        .catch((error) => this.reportActionError("刷新译文批注失败", error));
    }
  }

  private splitTitle(state: SplitState): string {
    return `${itemTitle(state.leftItem)} | ${itemTitle(state.rightItem)}`.slice(0, 100);
  }

  private ensureTitleHook(): void {
    if (this.stopped || this.restoreTitleHook) return;
    const hooks = this.mainWindow?.Zotero_Tabs?.tabHooks?.getTitle;
    const original = hooks?.reader;
    if (typeof original !== "function") return;
    const wrapped = async (tab: any) => {
      const state = this.states.get(String(tab?.id));
      return state && !state.cleaning ? this.splitTitle(state) : original(tab);
    };
    hooks.reader = wrapped;
    this.restoreTitleHook = () => {
      if (hooks.reader === wrapped) hooks.reader = original;
    };
  }


  private createBrowser(): any {
    const browser = this.mainWindow.document.createXULElement("browser");
    browser.setAttribute("type", "content");
    browser.setAttribute("transparent", "true");
    browser.setAttribute("src", "resource://zotero/reader/reader.html");
    browser.style.flex = "1 1 0";
    browser.style.minWidth = "200px";
    browser.style.minHeight = "0";
    browser.style.overflow = "hidden";
    browser.style.boxSizing = "border-box";
    return browser;
  }

  private createResizer(): any {
    const resizer = this.mainWindow.document.createXULElement("box");
    // A 2px visual rule inside a 12px hit target keeps the handle easy to
    // grab beside PDF.js's own scrollbar without making the divider heavy.
    resizer.style.width = "12px";
    resizer.style.minWidth = "12px";
    resizer.style.flex = "0 0 12px";
    resizer.style.boxSizing = "border-box";
    resizer.style.borderLeft = "5px solid transparent";
    resizer.style.borderRight = "5px solid transparent";
    resizer.style.cursor = "ew-resize";
    resizer.style.background = "var(--fill-quarternary, rgba(0,0,0,.12))";
    resizer.style.backgroundClip = "padding-box";
    resizer.style.zIndex = "2";
    resizer.setAttribute("mousethrough", "never");
    return resizer;
  }

  private installControls(state: SplitState, container: any, row: any): void {
    const doc = this.mainWindow.document;
    const bar = doc.createXULElement("hbox");
    state.controlBar = bar;
    bar.style.cssText = "display:flex;align-items:center;justify-content:flex-end;gap:6px;box-sizing:border-box;height:30px;min-height:30px;padding:2px 8px;background:var(--material-background, #f8f9fb);border-bottom:1px solid var(--fill-quarternary, #e5e7eb);";
    const label = doc.createXULElement("label");
    label.setAttribute("value", "TeXGlot · 原文 / 译文");
    label.style.cssText = "margin-right:auto;opacity:.75;font-size:11px;";
    const makeButton = (command: () => void) => {
      const button = doc.createXULElement("toolbarbutton");
      button.style.cssText = "appearance:none;border:1px solid var(--fill-quarternary, #d9dce2);border-radius:5px;padding:2px 8px;min-height:22px;background:transparent;font-size:11px;cursor:pointer;";
      button.addEventListener("command", command);
      state.listeners.push({ target: button, type: "command", listener: command });
      bar.appendChild(button);
      return button;
    };
    bar.appendChild(label);
    state.syncControl = makeButton(() => this.toggleSync(state));
    state.primaryControl = makeButton(() => this.togglePrimary(state));
    this.updateControlLabels(state);
    container.insertBefore(bar, row);
  }

  private updateControlLabels(state: SplitState): void {
    state.syncControl?.setAttribute("label", state.syncEnabled ? "同步：开" : "同步：关");
    state.syncControl?.setAttribute("tooltiptext", state.syncEnabled ? "关闭左右同步滚动" : "开启左右同步滚动");
    state.primaryControl?.setAttribute("label", `定位基准：${state.primarySide === "right" ? "译文" : "原文"}`);
    state.primaryControl?.setAttribute("tooltiptext", "开启同步或重新对齐时，以此侧的阅读位置为基准");
  }

  private toggleSync(state: SplitState): void {
    if (state.cleaning) return;
    state.syncEnabled = !state.syncEnabled;
    this.updateControlLabels(state);
    this.updateTabData(state);
    if (state.syncEnabled) void this.syncFromPrimary(state);
  }

  private togglePrimary(state: SplitState): void {
    if (state.cleaning) return;
    state.primarySide = state.primarySide === "right" ? "left" : "right";
    this.updateControlLabels(state);
    this.updateTabData(state);
    if (state.syncEnabled) void this.syncFromPrimary(state);
  }

  private installContainerMethods(container: any): void {
    container.setContextPaneOpen = (open: boolean) =>
      container.dispatchEvent(new this.mainWindow.CustomEvent("tab-context-pane-toggle", { detail: { open } }));
    container.setBottomPlaceholderHeight = (height: number) =>
      container.dispatchEvent(new this.mainWindow.CustomEvent("tab-bottom-placeholder-resize", { detail: { height } }));
    container.onTabSelectionChanged = () => undefined;
  }

  private applySplitRatio(state: SplitState): void {
    state.leftBrowser.style.flex = `${Math.round(state.splitRatio * 1000)} 1 0`;
    state.rightBrowser.style.flex = `${Math.round((1 - state.splitRatio) * 1000)} 1 0`;
  }

  private installResizer(state: SplitState, resizer: any, row: any): void {
    let dragging = false;
    let latestX = 0;
    let frame: number | null = null;
    let startRatio = state.splitRatio;
    let overlay: HTMLElement | null = null;

    const applyRatio = (clientX: number) => {
      const rect = row.getBoundingClientRect();
      if (!rect.width) return;
      const resizerWidth = Math.max(1, Number(resizer.getBoundingClientRect?.().width || 12));
      const availableWidth = Math.max(1, rect.width - resizerWidth);
      const minimumWidth = 200;
      const minRatio = Math.min(0.35, minimumWidth / availableWidth);
      const maxRatio = 1 - minRatio;
      const raw = (clientX - rect.left) / availableWidth;
      // Use one-percent increments. This is stable under PDF.js reflow and
      // prevents sub-pixel flex feedback from making the divider oscillate.
      const ratio = Math.min(maxRatio, Math.max(minRatio, Math.round(raw * 100) / 100));
      if (ratio === state.splitRatio) return;
      state.splitRatio = ratio;
      state.leftBrowser.style.flex = `${Math.round(ratio * 1000)} 1 0`;
      state.rightBrowser.style.flex = `${Math.round((1 - ratio) * 1000)} 1 0`;
    };

    const scheduleMove = (event: MouseEvent) => {
      if (!dragging) return;
      latestX = event.clientX;
      if (frame !== null) return;
      const requestFrame = this.mainWindow.requestAnimationFrame?.bind(this.mainWindow)
        || ((callback: FrameRequestCallback) => this.mainWindow.setTimeout(callback, 16));
      frame = requestFrame(() => {
        frame = null;
        if (dragging) applyRatio(latestX);
      });
    };

    const finish = (cancelled = false) => {
      if (!dragging && !overlay) return;
      if (frame !== null) {
        this.mainWindow.cancelAnimationFrame?.(frame);
        frame = null;
      }
      if (dragging && !cancelled) applyRatio(latestX);
      if (cancelled) {
        state.splitRatio = startRatio;
        this.applySplitRatio(state);
      }
      dragging = false;
      overlay?.remove();
      overlay = null;
      state.dragOverlay = null;
      this.mainWindow.removeEventListener("mousemove", scheduleMove, true);
      this.mainWindow.removeEventListener("mouseup", onMouseUp, true);
      this.mainWindow.removeEventListener("blur", onMouseUp, true);
      this.mainWindow.document.removeEventListener("mouseleave", onMouseUp, true);
      this.mainWindow.document.removeEventListener("keydown", onKeyDown, true);
      this.mainWindow.removeEventListener("keydown", onKeyDown, true);
      this.updateTabData(state);
    };

    const onMouseUp = () => finish(false);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") finish(true);
    };
    const start = (event: MouseEvent) => {
      if (dragging || event.button !== 0) return;
      dragging = true;
      latestX = event.clientX;
      startRatio = state.splitRatio;
      const dragSurface = this.mainWindow.document.createElement("div");
      overlay = dragSurface;
      dragSurface.tabIndex = -1;
      dragSurface.style.cssText = "position:fixed;inset:0;z-index:99999;cursor:ew-resize;background:transparent;";
      this.mainWindow.document.documentElement?.appendChild(dragSurface);
      dragSurface.focus?.();
      state.dragOverlay = dragSurface;
      dragSurface.addEventListener("mousemove", scheduleMove);
      dragSurface.addEventListener("mouseup", onMouseUp);
      this.mainWindow.addEventListener("mousemove", scheduleMove, true);
      this.mainWindow.addEventListener("mouseup", onMouseUp, true);
      this.mainWindow.addEventListener("blur", onMouseUp, true);
      this.mainWindow.document.addEventListener("mouseleave", onMouseUp, true);
      this.mainWindow.document.addEventListener("keydown", onKeyDown, true);
      this.mainWindow.addEventListener("keydown", onKeyDown, true);
      event.preventDefault();
      event.stopPropagation();
    };
    state.finishDrag = () => finish(true);
    resizer.addEventListener("mousedown", start);
    state.listeners.push({ target: resizer, type: "mousedown", listener: start as EventListener });
  }

  private async initializeReader(
    state: SplitState,
    side: Side,
    item: any,
    browser: any,
    popupset: any,
    viewState: any,
  ): Promise<void> {
    const path = await item.getFilePathAsync?.();
    const io = (globalThis as any).IOUtils ?? this.mainWindow?.IOUtils;
    if (typeof item.getFilePathAsync === "function" && !path) {
      throw new Error(`${side === "right" ? "译文" : "原文"} PDF 本地文件不存在；请先在 Zotero 中下载附件。`);
    }
    if (typeof path === "string" && typeof io?.exists === "function" && !await io.exists(path)) {
      throw new Error(`${side === "right" ? "译文" : "原文"} PDF 本地文件不存在；请先在 Zotero 中下载附件。`);
    }
    await this.waitForBrowserLoad(browser);
    const browserWindow = browser.contentWindow;
    if (!browserWindow) throw new Error("Zotero PDF 阅读器窗口不可用。");
    const wrappedWindow = browserWindow.wrappedJSObject || browserWindow;
    if (typeof wrappedWindow.createReader !== "function") throw new Error("Zotero PDF 阅读器初始化接口不可用。");

    const readerConfig = await this.buildReaderConfig(state, side, item, browser, popupset, viewState, wrappedWindow);
    const cloned = this.cloneInto(readerConfig, browserWindow);
    wrappedWindow.createReader(cloned);
    await this.waitForInternalReader(browser);
  }

  private async buildReaderConfig(
    state: SplitState,
    side: Side,
    item: any,
    browser: any,
    popupset: any,
    viewState: any,
    wrappedWindow: any,
  ): Promise<any> {
    const annotations = await this.loadAnnotations(item);
    const ftl: string[] = [];
    try {
      const file = this.zotero?.File;
      ftl.push(file?.getContentsFromURL?.("chrome://zotero/locale/zotero.ftl") || "");
      ftl.push(file?.getContentsFromURL?.("chrome://zotero/locale/reader.ftl") || "");
    } catch {
      // Localization is optional for the embedded reader.
    }
    let customThemes: any[] = [];
    try {
      customThemes = this.zotero?.SyncedSettings?.get?.(this.zotero?.Libraries?.userLibraryID, "readerCustomThemes") ?? [];
    } catch {
      // A reader can still open before synced settings finish loading.
    }
    const attachmentURL = this.attachmentURL(item);
    return {
      type: "pdf",
      data: { url: attachmentURL },
      annotations,
      readOnly: !item.isEditable?.() || Boolean(item.deleted || item.parentItem?.deleted),
      authorName: "",
      showContextPaneToggle: side === "right",
      contextPaneOpen: false,
      sidebarWidth: 240,
      sidebarOpen: false,
      bottomPlaceholderHeight: null,
      rtl: Boolean(this.zotero?.rtl),
      fontSize: safePref(this.zotero, "fontSize", 14),
      ftl,
      showAnnotations: true,
      textSelectionAnnotationMode: safePref(this.zotero, "reader.textSelectionAnnotationMode", "highlight"),
      customThemes,
      lightTheme: safePref(this.zotero, "reader.lightTheme", "light"),
      darkTheme: safePref(this.zotero, "reader.darkTheme", "dark"),
      fontFamily: safePref(this.zotero, "reader.ebookFontFamily", "system-ui"),
      hyphenate: safePref(this.zotero, "reader.ebookHyphenate", true),
      autoDisableNoteTool: safePref(this.zotero, "reader.autoDisableTool.note", false),
      autoDisableTextTool: safePref(this.zotero, "reader.autoDisableTool.text", false),
      autoDisableImageTool: safePref(this.zotero, "reader.autoDisableTool.image", false),
      sidebarView: safePref(this.zotero, "reader.lastSidebarTab", "thumbnails"),
      primaryViewState: viewState,
      secondaryViewState: side === "left" ? state.leftSecondaryViewState : state.rightSecondaryViewState,
      onOpenContextMenu: (params: any) => this.openContextMenu(state, browser, popupset, params),
      onToggleSidebar: (open: boolean) => state.nativeReader?._onToggleSidebarCallback?.(open),
      onChangeSidebarWidth: (width: number) => state.nativeReader?._onChangeSidebarWidthCallback?.(width),
      onFocusContextPane: () => {
        if (!this.mainWindow?.ZoteroContextPane?.focus?.()) state.nativeReader?.focusFirst?.();
      },
      onChangeSidebarView: (view: string) => {
        try { this.zotero?.Prefs?.set?.("reader.lastSidebarTab", view); } catch { /* optional */ }
      },
      onChangeViewState: (next: any, primary: boolean) => {
        const current = this.states.get(state.tabID);
        if (!current || current.cleaning) return;
        if (primary === false) {
          if (side === "left") current.leftSecondaryViewState = this.copyState(next);
          else current.rightSecondaryViewState = this.copyState(next);
          this.updateTabData(current);
        } else {
          if (side === "left") current.leftViewState = this.copyState(next);
          else current.rightViewState = this.copyState(next);
          this.scheduleTabDataSave(current);
        }
      },
      onSaveAnnotations: async (items: any[], callback: () => void) => {
        try {
          await this.saveAnnotations(item, items, state.nativeReader?._instanceID);
        } catch (error) {
          this.internalReader(browser)?.setReadOnly?.(true);
          this.zotero?.alert?.(this.mainWindow, "TeXGlot", `批注未能保存：${String(error)}`);
          throw error;
        } finally {
          callback?.();
        }
      },
      onDeleteAnnotations: (ids: string[]) => this.deleteAnnotations(item, ids),
      onAddToNote: (items: any[]) => this.addToActiveNote(item, items),
      onOpenTagsPopup: (id: string, x: number, y: number) => this.openTagsPopup(state, browser, popupset, item, id, x, y),
      onClosePopup: () => {
        for (const child of [...popupset.children]) if (child.classList?.contains("tags-popup")) child.hidePopup?.();
      },
      onOpenLink: (url: string) => this.zotero?.launchURL?.(url),
      onCopyImage: (dataURL: string) => this.copyImage(dataURL),
      onSaveImageAs: (image: string | Blob) => this.saveImageAs(image, browser),
      onSetDataTransferAnnotations: (transfer: any, values: any[], fromText = false) => {
        const copies = values.map((value) => ({ ...value, attachmentItemID: item.id }));
        transfer?.setData?.("zotero/annotation", JSON.stringify(copies));
        if (fromText) return;
        const paragraphs = copies.map((value) => [value.text, value.comment].filter(Boolean).join("\n")).filter(Boolean);
        if (!paragraphs.length) return;
        transfer?.setData?.("text/plain", paragraphs.join("\n\n"));
        transfer?.setData?.("text/html", paragraphs.map((text) => `<p>${escapeHTML(text).replace(/\n/g, "<br>")}</p>`).join(""));
      },
      onConfirm: (title: string, message: string, confirmLabel: string) => {
        const prompt = this.host.Services?.prompt ?? (globalThis as any).Services?.prompt ?? this.mainWindow?.Services?.prompt;
        if (!prompt?.confirmEx) return false;
        const flags = prompt.BUTTON_POS_0 * prompt.BUTTON_TITLE_IS_STRING + prompt.BUTTON_POS_1 * prompt.BUTTON_TITLE_CANCEL;
        return prompt.confirmEx(this.mainWindow, title, message, flags, confirmLabel, null, null, null, {}) === 0;
      },
      onRotatePages: (pageIndexes: number[], degrees: number) =>
        this.editPages(state, side, item, browser, pageIndexes, "rotate", degrees),
      onDeletePages: (pageIndexes: number[]) =>
        this.editPages(state, side, item, browser, pageIndexes, "delete"),
      onTextSelectionAnnotationModeChange: (mode: string) => this.zotero?.Prefs?.set?.("reader.textSelectionAnnotationMode", mode),
      onToolbarShiftTab: () => this.mainWindow?.Zotero_Tabs?.focusBack?.(),
      onIframeTab: () => this.mainWindow?.Zotero_Tabs?.focusForward?.(),
      onSetZoom: (iframe: any, zoom: number) => {
        if (iframe?.browsingContext) {
          iframe.browsingContext.textZoom = 1;
          iframe.browsingContext.fullZoom = zoom;
        }
      },
      onBringReaderToFront: (bring: boolean) => {
        if (browser?.parentElement?.style) browser.parentElement.style.zIndex = bring ? "1" : "";
      },
      onSaveCustomThemes: (themes: any[]) => this.saveCustomThemes(themes),
      onSetLightTheme: (name: string) => this.zotero?.Prefs?.set?.("reader.lightTheme", name || false),
      onSetDarkTheme: (name: string) => this.zotero?.Prefs?.set?.("reader.darkTheme", name || false),
      enableReadAloud: false,
      onToggleContextPane: () => this.zotero?.getMainWindow?.()?.ZoteroContextPane?.togglePane?.(),
    };
  }

  private attachmentURL(item: any): string {
    const prefix = this.zotero?.API?.getLibraryPrefix?.(item.libraryID) ?? item.libraryID;
    return `zotero://attachment/${prefix}/items/${item.key}/`;
  }

  private decodeImageDataURL(value: string): { mime: string; bytes: Uint8Array } {
    const match = /^data:([^;,]+);base64,([A-Za-z0-9+/=]+)$/.exec(value);
    if (!match) throw new Error("无法读取图片数据。");
    const decoded = atob(match[2]);
    const bytes = new Uint8Array(decoded.length);
    for (let index = 0; index < decoded.length; index++) bytes[index] = decoded.charCodeAt(index);
    return { mime: match[1], bytes };
  }

  private async copyImage(dataURL: string): Promise<void> {
    try {
      const { mime, bytes } = this.decodeImageDataURL(dataURL);
      const xpcom = (globalThis as any).Components;
      if (!xpcom) throw new Error("系统剪贴板接口不可用。");
      const imageTools = xpcom.classes["@mozilla.org/image/tools;1"].getService(xpcom.interfaces.imgITools);
      const transfer = xpcom.classes["@mozilla.org/widget/transferable;1"].createInstance(xpcom.interfaces.nsITransferable);
      const clipboard = xpcom.classes["@mozilla.org/widget/clipboard;1"].getService(xpcom.interfaces.nsIClipboard);
      transfer.init(null);
      transfer.addDataFlavor("application/x-moz-nativeimage");
      transfer.setTransferData("application/x-moz-nativeimage", imageTools.decodeImageFromArrayBuffer(bytes.buffer, mime));
      clipboard.setData(transfer, null, clipboard.kGlobalClipboard);
    } catch (error) {
      this.reportActionError("复制图片失败", error);
    }
  }

  private async saveImageAs(image: string | Blob, browser: any): Promise<void> {
    try {
      const chrome = (globalThis as any).ChromeUtils ?? this.mainWindow?.ChromeUtils;
      const Picker = chrome?.importESModule?.("chrome://zotero/content/modules/filePicker.mjs")?.FilePicker;
      const io = (globalThis as any).IOUtils ?? this.mainWindow?.IOUtils;
      if (!Picker || typeof io?.write !== "function") throw new Error("Zotero 文件保存接口不可用。");
      const picker = new Picker();
      picker.init(browser.contentWindow, "保存图片", picker.modeSave);
      picker.appendFilter("PNG", "*.png");
      picker.defaultString = "image.png";
      const result = await picker.show();
      if (result !== picker.returnOK && result !== picker.returnReplace) return;
      const bytes = typeof image === "string"
        ? this.decodeImageDataURL(image).bytes
        : new Uint8Array(await image.arrayBuffer());
      await io.write(picker.file, bytes);
    } catch (error) {
      this.reportActionError("保存图片失败", error);
    }
  }

  private reportActionError(action: string, error: unknown): void {
    if (error && typeof error === "object") {
      if (this.reportedErrors.has(error)) return;
      this.reportedErrors.add(error);
    }
    try {
      this.zotero?.alert?.(this.mainWindow, "TeXGlot", `${action}：${String(error)}`);
    } catch {
      this.zotero?.debug?.(`[TeXGlot] ${action}: ${String(error)}`);
    }
  }

  private async saveCustomThemes(themes: any[]): Promise<void> {
    const settings = this.zotero?.SyncedSettings;
    const libraryID = this.zotero?.Libraries?.userLibraryID;
    if (!settings || !libraryID) {
      this.zotero?.alert?.(this.mainWindow, "TeXGlot", "Zotero 阅读器主题设置不可用。");
      return;
    }
    const values = Array.isArray(themes) ? themes : [];
    try {
      for (const key of ["reader.lightTheme", "reader.darkTheme"]) {
        const selected = this.zotero?.Prefs?.get?.(key);
        if (typeof selected === "string" && selected.startsWith("custom") && !values.some((theme) => theme.id === selected)) {
          this.zotero?.Prefs?.clear?.(key);
        }
      }
      if (values.length) await settings.set(libraryID, "readerCustomThemes", values);
      else await settings.clear(libraryID, "readerCustomThemes");
    } catch (error) {
      this.zotero?.alert?.(this.mainWindow, "TeXGlot", `保存阅读器主题失败：${String(error)}`);
    }
  }

  private openContextMenu(state: SplitState, browser: any, popupset: any, params: any): Promise<void> {
    const doc = this.mainWindow.document;
    const popup = doc.createXULElement("menupopup");
    popupset.appendChild(popup);
    const groups = [...(params?.itemGroups || [])];
    groups.push([
      {
        label: state.syncEnabled ? "TeXGlot：关闭同步滚动" : "TeXGlot：开启同步滚动",
        icon: this.host.iconURI,
        onCommand: () => this.toggleSync(state),
      },
      {
        label: `TeXGlot：定位基准改为${state.primarySide === "right" ? "原文" : "译文"}`,
        icon: this.host.iconURI,
        onCommand: () => this.togglePrimary(state),
      },
    ]);
    const appendGroups = (parent: any, itemGroups: any[]) => {
      itemGroups.forEach((group, groupIndex) => {
        for (const item of group) {
          if (item.groups) {
            const menu = doc.createXULElement("menu");
            menu.setAttribute("label", item.label);
            const child = doc.createXULElement("menupopup");
            menu.appendChild(child);
            appendGroups(child, item.groups);
            parent.appendChild(menu);
          } else {
            const button = doc.createXULElement("menuitem");
            button.setAttribute("label", item.label);
            setMenuIcon(button, item.icon, Boolean(this.zotero?.isMac));
            button.setAttribute("disabled", Boolean(item.disabled));
            if (item.checked) {
              button.setAttribute("type", "checkbox");
              button.setAttribute("checked", "true");
            }
            button.addEventListener("command", () => {
              try {
                void Promise.resolve(item.onCommand?.()).catch((error) => this.reportActionError("阅读器操作失败", error));
              } catch (error) {
                this.reportActionError("阅读器操作失败", error);
              }
            });
            parent.appendChild(button);
          }
        }
        if (groupIndex < itemGroups.length - 1) parent.appendChild(doc.createXULElement("menuseparator"));
      });
    };
    appendGroups(popup, groups);
    const rect = browser.getBoundingClientRect();
    const screen = this.mainWindow.windowUtils?.toScreenRectInCSSUnits?.(rect.x + Number(params?.x || 0), rect.y + Number(params?.y || 0), 0, 0);
    const x = screen?.x ?? this.mainWindow.screenX + rect.x + Number(params?.x || 0);
    const y = screen?.y ?? this.mainWindow.screenY + rect.y + Number(params?.y || 0);
    return new Promise((resolve) => {
      popup.addEventListener("popuphidden", () => { popup.remove(); resolve(); }, { once: true });
      popup.openPopupAtScreen(x, y, true);
    });
  }

  private openTagsPopup(state: SplitState, browser: any, popupset: any, item: any, id: string, x: number, y: number): void {
    const annotation = this.zotero?.Items?.getByLibraryAndKey?.(item.libraryID, id);
    if (!annotation) return;
    const reader = state.nativeReader;
    if (!reader?._openTagsPopup) return;
    const oldIframe = reader._iframe;
    const oldPopupset = reader._popupset;
    try {
      reader._iframe = browser;
      reader._popupset = popupset;
      reader._openTagsPopup(annotation, x, y);
    } finally {
      reader._iframe = oldIframe;
      reader._popupset = oldPopupset;
    }
  }

  private async loadAnnotations(item: any): Promise<any[]> {
    try {
      const annotations = item.getAnnotations?.() || [];
      const values = await Promise.all(annotations.map(async (annotation: any) => {
        try {
          if (!annotation?.isAnnotation?.()) return null;
          const json = await this.zotero?.Annotations?.toJSON?.(annotation);
          if (!json) return null;
          json.id = annotation.key;
          delete json.key;
          json.tags = json.tags || [];
          return json;
        } catch {
          return null;
        }
      }));
      return values.filter(Boolean);
    } catch {
      return [];
    }
  }

  private annotationIdMap(item: any): Map<number, string> {
    try {
      return new Map((item.getAnnotations?.() || [])
        .filter((annotation: any) => Number.isInteger(annotation?.id) && annotation?.key)
        .map((annotation: any) => [annotation.id, String(annotation.key)]));
    } catch {
      return new Map();
    }
  }

  private async saveAnnotations(item: any, annotations: any[], instanceID?: string): Promise<void> {
    const queue = this.zotero?.Notifier?.Queue ? new this.zotero.Notifier.Queue() : null;
    try {
      for (const annotation of annotations) {
        annotation.key = annotation.id;
        delete annotation.authorName;
        if (typeof this.zotero?.Annotations?.saveFromJSON !== "function") throw new Error("Zotero 批注保存接口不可用。");
        const image = annotation.image;
        const existing = this.zotero?.Items?.getByLibraryAndKey?.(item.libraryID, annotation.key);
        const cacheOnly = image && existing && !existing.isEditable?.();
        const options: any = {};
        if (queue) options.notifierQueue = queue;
        if (instanceID) {
          options.notifierData = { instanceID };
          if (annotation.onlyTextOrComment && this.zotero?.Notes?.AUTO_SYNC_DELAY) {
            options.notifierData.autoSyncDelay = this.zotero.Notes.AUTO_SYNC_DELAY;
          }
        }
        const saved = cacheOnly ? existing : await this.zotero.Annotations.saveFromJSON(item, annotation, options);
        if (image) {
          if (typeof this.zotero?.Annotations?.saveCacheImage !== "function") throw new Error("Zotero 图片批注缓存接口不可用。");
          const { mime, bytes } = this.decodeImageDataURL(image);
          await this.zotero.Annotations.saveCacheImage(saved, new Blob([Uint8Array.from(bytes)], { type: mime }));
        }
      }
    } finally {
      if (queue) await this.zotero.Notifier.commit(queue);
    }
  }

  private async deleteAnnotations(item: any, ids: string[]): Promise<void> {
    const queue = this.zotero?.Notifier?.Queue ? new this.zotero.Notifier.Queue() : null;
    try {
      for (const id of ids) {
        const annotation = this.zotero?.Items?.getByLibraryAndKey?.(item.libraryID, id);
        if (!annotation?.isAnnotation?.() || annotation.parentID !== item.id) continue;
        if (typeof annotation.eraseTx !== "function") throw new Error("Zotero 批注删除接口不可用。");
        await annotation.eraseTx(queue ? { notifierQueue: queue } : undefined);
      }
    } catch (error) {
      this.reportActionError("删除批注失败", error);
      throw error;
    } finally {
      if (queue) {
        try { await this.zotero.Notifier.commit(queue); }
        catch (error) {
          this.reportActionError("提交批注删除失败", error);
          throw error;
        }
      }
    }
  }

  private async editPages(
    state: SplitState,
    side: Side,
    item: any,
    browser: any,
    requestedIndexes: number[],
    operation: "rotate" | "delete",
    degrees?: number,
  ): Promise<void> {
    if (state.cleaning) return;
    const indexes = [...new Set(requestedIndexes)].filter((value) => Number.isInteger(value) && value >= 0);
    if (!indexes.length) return;
    if (operation === "delete") {
      // Use Zotero's own confirmation wording and button semantics. If this
      // host cannot show it, do not delete any pages.
      if (typeof state.nativeReader?._promptToDeletePages !== "function") {
        this.reportActionError("PDF 页面操作失败", new Error("Zotero 删除页面确认框不可用，未修改 PDF。"));
        return;
      }
      try {
        if (!state.nativeReader._promptToDeletePages(indexes.length)) return;
      } catch (error) {
        this.reportActionError("PDF 页面操作失败", error);
        return;
      }
    }

    const worker = this.zotero?.PDFWorker;
    const internal = this.internalReader(browser);
    const method = operation === "rotate" ? worker?.rotatePages : worker?.deletePages;
    if (typeof method !== "function" || typeof internal?.reload !== "function") {
      this.reportActionError("PDF 页面操作失败", new Error("Zotero PDF 页面编辑接口不可用，未修改 PDF。"));
      return;
    }
    const wasPaused = state.syncPaused;
    state.syncPaused = true;
    const reload = async () => {
      internal.reload(this.cloneInto({ url: this.attachmentURL(item) }, browser.contentWindow));
      await this.waitForInternalReader(browser);
      if (!state.cleaning) {
        this.refreshSyncListeners(state);
        if (state.syncEnabled) this.syncFromSide(state, side);
      }
    };
    let workerStarted = false;
    try {
      internal.freeze?.();
      if (operation === "rotate") {
        if (degrees !== 90 && degrees !== 270) throw new Error("无效的页面旋转角度。");
        workerStarted = true;
        await worker.rotatePages(item.id, indexes, degrees, true);
      } else {
        workerStarted = true;
        await worker.deletePages(item.id, indexes, true);
      }
      await reload();
    } catch (error) {
      let reloadError: unknown = null;
      if (workerStarted) {
        try { await reload(); }
        catch (failure) { reloadError = failure; }
      }
      if (reloadError) {
        this.reportActionError("PDF 页面操作失败，且重新加载失败；请关闭并重新打开该 PDF 附件", new Error(`${String(error)}；${String(reloadError)}`));
      } else {
        this.reportActionError("PDF 页面操作失败", error);
      }
    } finally {
      state.syncPaused = wasPaused;
      try { internal.unfreeze?.(); } catch { /* reader may have closed during editing */ }
    }
  }

  private addToActiveNote(item: any, annotations: any[]): void {
    try {
      const editor = this.zotero?.getMainWindow?.()?.ZoteroContextPane?.activeEditor?.getCurrentInstance?.();
      if (!editor) {
        this.reportActionError("添加批注到笔记失败", new Error("请先在 Zotero 中打开或创建一篇笔记。"));
        return;
      }
      editor.focus?.();
      editor.insertAnnotations?.(annotations.map((annotation: any) => ({ ...annotation, attachmentItemID: item.id })));
    } catch (error) {
      this.reportActionError("添加批注到笔记失败", error);
    }
  }

  private cacheViewerContainers(state: SplitState): void {
    state.leftViewer = this.getViewerContainer(state.leftBrowser);
    state.rightViewer = this.getViewerContainer(state.rightBrowser);
  }

  private installSyncListeners(state: SplitState): void {
    state.syncListeners ??= [];
    this.cacheViewerContainers(state);
    const markInput = (side: Side) => () => {
      const current = this.states.get(state.tabID);
      if (!current || current.cleaning) return;
      current.inputSide = side;
      current.activeSide = side;
      current.suppressSide = null;
    };
    for (const side of ["left", "right"] as const) {
      const browser = side === "left" ? state.leftBrowser : state.rightBrowser;
      const viewer = side === "left" ? state.leftViewer : state.rightViewer;
      const document = browser?.contentWindow?.document;
      const listener = markInput(side);
      for (const target of [viewer, document]) {
        if (!target) continue;
        for (const type of ["wheel", "pointerdown", "keydown", "touchstart"]) {
          target.addEventListener(type, listener, { capture: true, passive: true });
          state.syncListeners.push({ target, type, listener, options: true });
        }
      }
    }
    const onScroll = (side: Side) => () => {
      const current = this.states.get(state.tabID);
      if (!current || current.cleaning || !current.syncEnabled || current.syncPaused) return;
      // The other pane's scroll event is normally caused by our own PDF.js
      // positioning. It must not make the two panes chase each other. A real
      // wheel, drag, click or key press changes inputSide before scrolling.
      if (current.suppressSide === side && current.inputSide !== side) return;
      current.inputSide = side;
      current.pendingSourceSide = side;
      if (current.scrollRAF !== null) return;
      const requestFrame = this.mainWindow.requestAnimationFrame?.bind(this.mainWindow) || ((callback: FrameRequestCallback) => this.mainWindow.setTimeout(callback, 16));
      current.scrollRAF = requestFrame(() => {
        current.scrollRAF = null;
        const sourceSide = current.pendingSourceSide;
        current.pendingSourceSide = null;
        if (sourceSide && !current.cleaning && current.syncEnabled) this.syncFromSide(current, sourceSide);
      });
    };
    const leftHandler = onScroll("left");
    const rightHandler = onScroll("right");
    state.leftViewer?.addEventListener("scroll", leftHandler, { passive: true });
    state.rightViewer?.addEventListener("scroll", rightHandler, { passive: true });
    if (state.leftViewer) state.syncListeners.push({ target: state.leftViewer, type: "scroll", listener: leftHandler });
    if (state.rightViewer) state.syncListeners.push({ target: state.rightViewer, type: "scroll", listener: rightHandler });
  }

  private refreshSyncListeners(state: SplitState): void {
    for (const listener of state.syncListeners) {
      try { listener.target.removeEventListener(listener.type, listener.listener, listener.options); } catch { /* replaced PDF frame */ }
    }
    state.syncListeners = [];
    this.installSyncListeners(state);
  }

  private syncFromSide(state: SplitState, side: Side): void {
    if (state.cleaning || !state.syncEnabled) return;
    const source = side === "right" ? state.rightBrowser : state.leftBrowser;
    const target = side === "right" ? state.leftBrowser : state.rightBrowser;
    state.suppressSide = side === "right" ? "left" : "right";
    // Scrolling is frequent. PDF.js already knows the viewport and page; a
    // full _setState() on every wheel tick can await the PDF pages promise and
    // discard later input while the reader catches up.
    this.syncPageLocalPosition(source, target);
  }

  private async syncFromPrimary(state: SplitState): Promise<void> {
    if (state.cleaning || !state.syncEnabled) return;
    const source = state.primarySide === "right" ? state.rightBrowser : state.leftBrowser;
    const target = state.primarySide === "right" ? state.leftBrowser : state.rightBrowser;
    const sourceReader = this.internalReader(source);
    const targetReader = this.internalReader(target);
    const sourceState = sourceReader?._state?.primaryViewState;
    const targetView = targetReader?._primaryView;
    if (!sourceState || !targetView) return;
    const next = this.copyState(sourceState);
    if (Number.isInteger(next.pageIndex)) {
      const targetFrame = targetView?._iframe?.contentWindow;
      const targetApp = (targetFrame?.wrappedJSObject || targetFrame)?.PDFViewerApplication;
      const pages = Number(targetApp?.pdfViewer?.pagesCount || 0);
      if (pages > 0) next.pageIndex = Math.min(Math.max(next.pageIndex, 0), pages - 1);
    }
    state.syncPaused = true;
    try {
      const cloned = this.cloneInto(next, target.contentWindow);
      if (typeof targetView._setState === "function") await targetView._setState(cloned);
      state.suppressSide = state.primarySide === "right" ? "left" : "right";
      this.syncPageLocalPosition(source, target);
      // PDF.js may update page containers one frame after _setState. Reapply
      // the page-local anchor once the target layout has settled.
      state.timers.push(this.mainWindow.setTimeout(() => {
        if (!state.cleaning) this.syncPageLocalPosition(source, target);
      }, 80));
    } finally {
      state.timers.push(this.mainWindow.setTimeout(() => {
        const current = this.states.get(state.tabID);
        if (current && !current.cleaning) {
          current.syncPaused = false;
          this.syncFromSide(current, current.inputSide);
        }
      }, 120));
    }
  }

  /**
   * Keep the same page-local anchor when the two PDFs have different page
   * heights. This deliberately avoids whole-document percentage mapping.
   */
  private syncPageLocalPosition(sourceBrowser: any, targetBrowser: any): void {
    try {
      const sourceReader = this.internalReader(sourceBrowser);
      const targetReader = this.internalReader(targetBrowser);
      const sourceFrame = sourceReader?._primaryView?._iframe?.contentWindow;
      const targetFrame = targetReader?._primaryView?._iframe?.contentWindow;
      const sourceApp = (sourceFrame?.wrappedJSObject || sourceFrame)?.PDFViewerApplication;
      const targetApp = (targetFrame?.wrappedJSObject || targetFrame)?.PDFViewerApplication;
      const sourceViewer = sourceApp?.pdfViewer;
      const targetViewer = targetApp?.pdfViewer;
      const sourceContainer = this.getViewerContainer(sourceBrowser) as HTMLElement | null;
      const targetContainer = this.getViewerContainer(targetBrowser) as HTMLElement | null;
      if (!sourceViewer || !targetViewer || !sourceContainer || !targetContainer) return;

      const sourcePageNumber = Number(sourceViewer.currentPageNumber || 1);
      const targetPageNumber = Math.min(
        Math.max(1, sourcePageNumber),
        Number(targetViewer.pagesCount || sourcePageNumber),
      );
      const sourcePage = sourceContainer.querySelector(`[data-page-number="${sourcePageNumber}"]`) as HTMLElement | null;
      const targetPage = targetContainer.querySelector(`[data-page-number="${targetPageNumber}"]`) as HTMLElement | null;
      if (!sourcePage || !targetPage) return;

      // Map a position within the page itself. Subtracting viewport height
      // makes the denominator zero when the page fits in the viewport and
      // incorrectly sends even a small scroll to the target page's bottom.
      const sourceRange = Math.max(1, sourcePage.offsetHeight);
      const sourceOffset = Math.max(0, sourceContainer.scrollTop - sourcePage.offsetTop);
      const fraction = Math.min(1, Math.max(0, sourceOffset / sourceRange));
      const targetRange = Math.max(0, targetPage.offsetHeight);
      targetViewer.currentPageNumber = targetPageNumber;
      targetContainer.scrollTop = Math.max(0, targetPage.offsetTop + fraction * targetRange);
    } catch {
      // PDF.js can be between page-layout updates; the next scroll retries.
    }
  }

  private installFocusListeners(state: SplitState): void {
    const install = (browser: any, side: Side) => {
      const focus = () => {
        const current = this.states.get(state.tabID);
        if (!current || current.cleaning) return;
        current.activeSide = side;
        this.updateTabData(current);
      };
      browser.addEventListener("focus", focus, true);
      browser.addEventListener("click", focus, true);
      state.listeners.push({ target: browser, type: "focus", listener: focus, options: true });
      state.listeners.push({ target: browser, type: "click", listener: focus, options: true });
    };
    install(state.leftBrowser, "left");
    install(state.rightBrowser, "right");
  }

  private getViewerContainer(browser: any): Element | null {
    try {
      const reader = this.internalReader(browser);
      const iframe = reader?._primaryView?._iframe;
      const win = iframe?.contentWindow?.wrappedJSObject || iframe?.contentWindow;
      return win?.document?.getElementById?.("viewerContainer") || null;
    } catch {
      return null;
    }
  }

  private internalReader(browser: any): any {
    try {
      const win = browser?.contentWindow?.wrappedJSObject || browser?.contentWindow;
      return win?._reader || null;
    } catch {
      return null;
    }
  }

  private async waitForBrowserLoad(browser: any): Promise<void> {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      try {
        const win = browser.contentWindow;
        const wrapped = win?.wrappedJSObject || win;
        if (win?.document?.readyState === "complete" && typeof wrapped?.createReader === "function") return;
      } catch {
        // The browser may not have created its content window yet.
      }
      await new Promise((resolve) => this.mainWindow.setTimeout(resolve, 100));
    }
    throw new Error("等待 Zotero PDF 阅读器加载超时。");
  }

  private async waitForInternalReader(browser: any): Promise<void> {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const reader = this.internalReader(browser);
      if (reader?._primaryView) {
        const remaining = Math.max(1, deadline - Date.now());
        await this.withTimeout(reader._primaryView.initializedPromise, remaining, "等待 Zotero PDF 页面加载超时。");
        const iframe = reader._primaryView._iframe?.contentWindow;
        const app = (iframe?.wrappedJSObject || iframe)?.PDFViewerApplication;
        if (Number(app?.pdfViewer?.pagesCount) > 0) return;
      }
      await new Promise((resolve) => this.mainWindow.setTimeout(resolve, 100));
    }
    throw new Error("Zotero PDF 阅读器未能加载页面；请检查附件是否已下载且文件完整。");
  }

  private async waitForReaderReady(reader: any): Promise<void> {
    if (reader?._initPromise) {
      await this.withTimeout(reader._initPromise, 15000, "等待原文阅读器初始化超时。");
    }
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline && !reader?._internalReader?._primaryView?._iframeWindow) {
      await new Promise((resolve) => this.mainWindow.setTimeout(resolve, 50));
    }
    if (!reader?._internalReader?._primaryView?._iframeWindow) throw new Error("原文 PDF 阅读器尚未完成加载。");
  }

  private async withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
    let timer: number | undefined;
    try {
      return await Promise.race([
        promise,
        new Promise<T>((_, reject) => {
          timer = this.mainWindow.setTimeout(() => reject(new Error(message)), ms);
        }),
      ]);
    } finally {
      if (timer !== undefined) this.mainWindow.clearTimeout(timer);
    }
  }

  private async getReaderViewState(reader: any): Promise<any> {
    try {
      if (typeof reader?._getState === "function") return await reader._getState();
      return this.copyState(reader?._internalReader?._state?.primaryViewState);
    } catch {
      return null;
    }
  }

  private async closeReaderWithoutClosingTab(reader: any): Promise<void> {
    try {
      // The normal reader may still have a delayed state write. Flush it
      // before our split panes begin saving their own positions.
      await reader?._flushState?.();
      if (reader?._blockingObserver && reader?._iframe) reader._blockingObserver.unregister(reader._iframe);
      // Keep the native ReaderTab registered. Zotero's tab hooks resolve
      // readers with getByTabID(), which requires a real ReaderTab instance.
      // The embedded left reader is rebound to it after both panes load.
    } catch {
      // Some Zotero builds have no blocking observer on this reader.
    }
  }

  private rebindNativeReader(state: SplitState): void {
    const reader = state.nativeReader;
    if (!reader) return;
    reader._tabContainer = state.container;
    reader._iframe = state.leftBrowser;
    reader._iframeWindow = state.leftBrowser.contentWindow;
    reader._internalReader = this.internalReader(state.leftBrowser);
    reader._popupset = state.leftPopupset;
    try { reader._blockingObserver?.register?.(state.leftBrowser); } catch { /* optional */ }
    const onSelection = (event: any) => {
      if (event?.detail?.selected) reader._updateLayout?.();
    };
    state.container.addEventListener("tab-selection-change", onSelection);
    state.listeners.push({ target: state.container, type: "tab-selection-change", listener: onSelection });
    const onContextPane = (event: any) => {
      for (const browser of [state.leftBrowser, state.rightBrowser]) {
        this.internalReader(browser)?.setContextPaneOpen?.(Boolean(event?.detail?.open));
      }
    };
    const onBottomPlaceholder = (event: any) => {
      for (const browser of [state.leftBrowser, state.rightBrowser]) {
        this.internalReader(browser)?.setBottomPlaceholderHeight?.(event?.detail?.height);
      }
    };
    state.container.addEventListener("tab-context-pane-toggle", onContextPane);
    state.container.addEventListener("tab-bottom-placeholder-resize", onBottomPlaceholder);
    state.listeners.push({ target: state.container, type: "tab-context-pane-toggle", listener: onContextPane });
    state.listeners.push({ target: state.container, type: "tab-bottom-placeholder-resize", listener: onBottomPlaceholder });
    state.container.onTabSelectionChanged = (selected: boolean) => {
      if (selected) reader._updateLayout?.();
    };
  }

  private savedViewState(tabID: string, side: Side, secondary = false): any {
    const tab = this.mainWindow?.Zotero_Tabs?._tabs?.find?.((candidate: any) => String(candidate.id) === tabID);
    const key = `${side}${secondary ? "Secondary" : ""}ViewState`;
    return this.copyState(tab?.data?.[key]);
  }

  private scheduleTabDataSave(state: SplitState): void {
    if (state.persistTimer !== null) this.mainWindow.clearTimeout(state.persistTimer);
    state.persistTimer = this.mainWindow.setTimeout(() => {
      state.persistTimer = null;
      if (state.cleaning) return;
      this.updateTabData(state);
      void this.persistSplitViewStates(state).then(() => { state.positionSaveFailed = false; })
        .catch((error) => this.reportPositionSaveError(state, error));
    }, 400);
  }

  private reportPositionSaveError(state: SplitState, error: unknown): void {
    if (state.positionSaveFailed) return;
    state.positionSaveFailed = true;
    this.reportActionError("保存 PDF 阅读位置失败", error);
  }

  private async persistSplitViewStates(state: SplitState): Promise<void> {
    await Promise.all([
      this.queueAttachmentViewState(state.leftItem, state.leftViewState),
      this.queueAttachmentViewState(state.rightItem, state.rightViewState),
    ]);
  }

  private queueAttachmentViewState(item: any, value: any): Promise<void> {
    if (!item?.id || !value) return Promise.resolve();
    const snapshot = this.copyState(value);
    const previous = this.attachmentWrites.get(item.id) ?? Promise.resolve();
    const write = previous.catch(() => undefined).then(() => this.persistAttachmentViewState(item, snapshot));
    this.attachmentWrites.set(item.id, write);
    void write.finally(() => {
      if (this.attachmentWrites.get(item.id) === write) this.attachmentWrites.delete(item.id);
    }).catch(() => undefined);
    return write;
  }

  private async persistAttachmentViewState(item: any, value: any): Promise<void> {
    const attachment = this.zotero?.Items?.get?.(item.id) ?? item;
    const storage = this.zotero?.Attachments;
    const io = (globalThis as any).IOUtils ?? this.mainWindow?.IOUtils;
    if (!storage?.getStorageDirectory || !io?.writeJSON) throw new Error("Zotero 阅读位置存储接口不可用。");
    const directory = storage.getStorageDirectory(attachment);
    if (!directory?.path || typeof directory.clone !== "function") throw new Error("找不到 Zotero 附件存储目录。");
    if (typeof io.exists === "function" && !await io.exists(directory.path)) {
      await storage.createDirectoryForItem?.(attachment);
    }
    const file = directory.clone();
    file.append(".zotero-reader-state");
    const tasks: Promise<unknown>[] = [io.writeJSON(file.path, value)];
    if (Number.isInteger(value.pageIndex) && typeof attachment.setAttachmentLastPageIndex === "function") {
      const previousPage = attachment.getAttachmentLastPageIndex?.();
      if (previousPage !== value.pageIndex) {
        tasks.push(Promise.resolve(attachment.setAttachmentLastPageIndex(value.pageIndex)).then(() =>
          this.zotero?.Notifier?.trigger?.("pageChange", "file", attachment.id)));
      }
    }
    await Promise.all(tasks);
  }

  private updateTabData(state: SplitState): void {
    try {
      this.mainWindow.Zotero_Tabs?.setTabData?.(state.tabID, {
        itemID: state.leftItem.id,
        leftItemID: state.leftItem.id,
        rightItemID: state.rightItem.id,
        isSplitView: true,
        splitRatio: state.splitRatio,
        syncEnabled: state.syncEnabled,
        primarySide: state.primarySide,
        activeSide: state.activeSide,
        leftViewState: state.leftViewState,
        rightViewState: state.rightViewState,
        leftSecondaryViewState: state.leftSecondaryViewState,
        rightSecondaryViewState: state.rightSecondaryViewState,
      });
    } catch {
      // Session metadata is an enhancement, not a reason to break reading.
    }
  }

  private renameTab(state: SplitState): void {
    try {
      this.mainWindow.Zotero_Tabs?.rename?.(state.tabID, this.splitTitle(state));
    } catch {
      // Optional.
    }
  }

  private focusSide(state: SplitState, side: Side): void {
    try {
      const browser = side === "right" ? state.rightBrowser : state.leftBrowser;
      browser.focus?.();
      browser.contentWindow?.focus?.();
    } catch {
      // Optional.
    }
  }

  private cloneInto(value: any, targetWindow: any): any {
    try {
      const components = (globalThis as any).Components;
      if (components?.utils?.cloneInto && targetWindow) {
        return components.utils.cloneInto(value, targetWindow, { wrapReflectors: true, cloneFunctions: true });
      }
    } catch {
      // Fall through to the plain object in test hosts.
    }
    return value;
  }

  private copyState(value: any): any {
    if (!value) return null;
    try { return JSON.parse(JSON.stringify(value)); } catch { return value; }
  }

  private cleanup(tabID: string, blankBrowsers = true): void {
    const state = this.states.get(tabID);
    if (!state || state.cleaning) return;
    state.cleaning = true;
    for (const listener of state.listeners) {
      try { listener.target.removeEventListener(listener.type, listener.listener, listener.options); } catch { /* dead browser */ }
    }
    for (const listener of state.syncListeners) {
      try { listener.target.removeEventListener(listener.type, listener.listener, listener.options); } catch { /* dead PDF frame */ }
    }
    for (const timer of state.timers) {
      try { this.mainWindow.clearTimeout(timer); } catch { /* optional */ }
    }
    if (state.persistTimer !== null) {
      try { this.mainWindow.clearTimeout(state.persistTimer); } catch { /* optional */ }
      this.updateTabData(state);
      void this.persistSplitViewStates(state).catch((error) => this.reportPositionSaveError(state, error));
    }
    if (state.scrollRAF !== null) {
      try { this.mainWindow.cancelAnimationFrame?.(state.scrollRAF); } catch { /* optional */ }
    }
    try { state.finishDrag?.(); } catch { /* optional */ }
    state.finishDrag = null;
    try { state.dragOverlay?.remove(); } catch { /* optional */ }
    state.dragOverlay = null;
    this.pruneOrphanedReaders(state.nativeReader);
    if (blankBrowsers) {
      try { state.leftBrowser?.setAttribute?.("src", "about:blank"); } catch { /* dead browser */ }
      try { state.rightBrowser?.setAttribute?.("src", "about:blank"); } catch { /* dead browser */ }
    }
    else try { state.controlBar?.remove?.(); } catch { /* optional */ }
    this.states.delete(tabID);
  }
}
