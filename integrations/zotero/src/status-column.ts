import { isGeneratedTranslation, isPdfAttachment, itemArxivVersions, parentIdOf } from "./arxiv.js";
import { readTranslationMetadata } from "./translation-metadata.js";
import type { TranslationActivity, ZoteroLikeItem } from "./types.js";

type StatusKind = "untranslated" | "translated" | "processing" | "review" | "checking";
export interface TranslationStatus { kind: StatusKind; details: string[] }
const symbols: Record<StatusKind, string> = { untranslated: "○", translated: "✓", processing: "◷", review: "!", checking: "…" };
const labels = {
  zh: { untranslated: "未翻译", translated: "已有译文", processing: "处理中", review: "需检查", checking: "正在读取翻译状态" },
  en: { untranslated: "Not translated", translated: "Translation available", processing: "Processing", review: "Needs review", checking: "Reading translation status" },
};

/** The PDF's metadata, not its filename or the availability of the service, is authoritative. */
export function translationStatus(parent: ZoteroLikeItem, children: ZoteroLikeItem[], chinese = true): TranslationStatus {
  const pdfs = children.filter((item) => !item.deleted && isPdfAttachment(item));
  const translations = pdfs.map(readTranslationMetadata).filter((marker) => marker?.artifact === "translated");
  if (!translations.length) {
    return pdfs.some(isGeneratedTranslation)
      ? { kind: "review", details: [chinese ? "TeXGlot 附件缺少有效的翻译标记" : "A TeXGlot attachment has no valid translation metadata"] }
      : { kind: "untranslated", details: [] };
  }
  const details = [...new Set(translations.map((marker) =>
    [marker!.language || (chinese ? "语言未记录" : "Language not recorded"), marker!.arxiv_id && `arXiv ${marker!.arxiv_id}`].filter(Boolean).join(" · ")))];
  const originals = pdfs.filter((item) => !isGeneratedTranslation(item));
  // The parent URL may describe an older revision than the PDF that was
  // actually translated. Prefer the stored file binding, then attachment
  // metadata; use parent metadata only when no attachment establishes a version.
  const attachmentVersions = originals.flatMap((item) => {
    const bound = translations.filter((marker) => item.key && marker!.source_attachment_key === item.key && marker!.source_fingerprint)
      .flatMap((marker) => marker!.arxiv_id ? [marker!.arxiv_id] : []);
    return bound.length ? bound : itemArxivVersions(item);
  });
  const versions = new Set(attachmentVersions.length ? attachmentVersions : itemArxivVersions(parent));
  const uncovered = [...versions].filter((version) => !translations.some((marker) => marker!.arxiv_id === version));
  const warnings = translations.some((marker) => marker!.translation_status && marker!.translation_status !== "completed");
  if (uncovered.length) details.push(chinese ? `以下原文版本尚无对应译文：${uncovered.join("、")}` : `No matching translation for: ${uncovered.join(", ")}`);
  if (warnings) details.push(chinese ? "译文已生成，部分内容需要检查" : "The PDF was generated with content requiring review");
  return { kind: warnings || uncovered.length ? "review" : "translated", details };
}

function statusData(status: TranslationStatus, chinese: boolean): string {
  return `${symbols[status.kind]} TeXGlot · ${labels[chinese ? "zh" : "en"][status.kind]}${status.details.length ? "\n" + status.details.join("\n") : ""}`;
}

const iconPaths: Record<string, string> = {
  "○": "M5 8h6",
  "✓": "M3 8l3 3 7-7",
  "◷": "M8 1.5a6.5 6.5 0 1 0 6.5 6.5A6.5 6.5 0 0 0 8 1.5ZM8 4v4l2.5 1.5",
  "!": "M8 1.5 15 14H1L8 1.5ZM8 6v3.5M8 12h.01",
  "…": "M3 8h.01M8 8h.01M13 8h.01",
};

/** Create native-sized SVG icons; the complete status remains available to assistive technology. */
export function renderStatusCell(data: string, column: { className?: string }, doc: Document): HTMLElement {
  const cell = doc.createElement("span");
  cell.className = `cell ${column.className ?? ""} texglot-status-cell`;
  cell.style.cssText = "display:flex;align-items:center;justify-content:center;min-width:0;";
  if (!data) return cell;
  const symbol = data[0];
  cell.dataset.status = symbol;
  cell.title = data.slice(2);
  cell.setAttribute("role", "img");
  cell.setAttribute("aria-label", cell.title);
  const svg = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({ viewBox: "0 0 16 16", width: "16", height: "16", fill: "none", stroke: "currentColor", "stroke-width": "1.6", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(key, value);
  const path = doc.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", iconPaths[symbol] ?? iconPaths["…"]);
  svg.appendChild(path);
  cell.appendChild(svg);
  return cell;
}

/** Default position only: Zotero's saved column preferences take precedence on subsequent starts. */
export function statusColumnOrdinal(columns: Array<{ dataKey: string; ordinal?: number }>): number {
  const title = columns.find((column) => column.dataKey === "title")?.ordinal ?? 0;
  const next = columns.map((column) => column.ordinal).filter((value): value is number => typeof value === "number" && value > title).sort((a, b) => a - b)[0];
  return (title + (next ?? title + 1)) / 2;
}

type CacheEntry = { item: any; status: TranslationStatus; children: Set<number> };
const PLACEMENT_PREF = "extensions.texglot.statusColumnPlacement";

class StatusColumn {
  references = 0;
  private key: string | false = false;
  private observer: any;
  private closed = false;
  private cache = new Map<number, CacheEntry>();
  private activities = new Map<number, Map<string, TranslationActivity>>();
  private refreshIDs = new Set<number>();
  private refreshTimer: ReturnType<typeof setTimeout> | undefined;
  private styles = new Set<HTMLStyleElement>();

  constructor(private zotero: any, private window: any, rootURI?: string) {
    const manager = zotero.ItemTreeManager;
    let columns = [];
    try { columns = window?.ZoteroPane?.itemsView?._getColumns?.() ?? []; } catch { /* library is not ready yet */ }
    this.key = manager.registerColumn({
      dataKey: "translationStatus", label: "TeXGlot", pluginID: "zotero@texglot.org",
      enabledTreeIDs: ["main"], showInColumnPicker: true,
      width: "40", minWidth: 32, flex: 0, staticWidth: true, noPadding: true,
      hidden: false, ordinal: statusColumnOrdinal(columns), dependsOnChildren: true,
      ...(rootURI ? { iconPath: `${rootURI}icons/texglot.png` } : {}),
      zoteroPersist: ["width", "hidden", "sortDirection"],
      dataProvider: (item: ZoteroLikeItem) => this.data(item),
      renderCell: (_index: number, data: string, column: { className?: string }, _first: boolean, doc: Document) => {
        this.ensureStyle(doc);
        return renderStatusCell(data, column, doc);
      },
    });
    if (!this.key) throw new Error("Zotero could not register the TeXGlot status column");
    this.restorePlacement();
    this.observer = zotero.Notifier?.registerObserver?.({
      notify: (action: string, type: string, ids: number[]) => {
        if (type !== "item" || !["add", "modify", "delete", "trash"].includes(action)) return;
        const affected = new Set(ids.map(Number));
        const parents = new Set<number>();
        for (const [parentID, entry] of this.cache) {
          if (affected.has(parentID) || [...entry.children].some((id) => affected.has(id))) parents.add(parentID);
        }
        for (const id of affected) {
          let item;
          try { item = zotero.Items?.get?.(id); } catch { continue; /* item may already have been erased */ }
          const parentID = item && parentIdOf(item);
          if (parentID) parents.add(parentID);
        }
        for (const id of parents) { this.cache.delete(id); this.queueRefresh(id); }
      },
    }, ["item"], "texglot-translation-status", 60);
  }

  private get chinese(): boolean { return !this.zotero.locale || String(this.zotero.locale).toLowerCase().startsWith("zh"); }

  private preservePlacement(): void {
    try {
      const view = this.window?.ZoteroPane?.itemsView;
      const columns = [...(view?._getColumns?.() ?? [])].sort((a, b) => a.ordinal - b.ordinal);
      const index = columns.findIndex((column) => column.dataKey === this.key);
      if (index < 0) return;
      const { hidden, width, sortDirection } = columns[index];
      this.zotero.Prefs?.set?.(PLACEMENT_PREF, JSON.stringify({
        before: columns[index - 1]?.dataKey, after: columns[index + 1]?.dataKey,
        hidden, width, sortDirection,
      }), true);
    } catch { /* a closing window may no longer expose its item tree */ }
  }

  private restorePlacement(): void {
    // Zotero renumbers the remaining columns when an add-on is unloaded.
    // Preserve relative neighbours through hot updates, rather than reusing a
    // stale integer ordinal that can put the column after a different field.
    try {
      const raw = this.zotero.Prefs?.get?.(PLACEMENT_PREF, true);
      const view = this.window?.ZoteroPane?.itemsView;
      if (!raw || !view?._storeColumnPrefs || !this.key) return;
      const { before, after, ...settings } = JSON.parse(raw);
      const columns = view._getColumns().filter((column: any) => column.dataKey !== this.key);
      const left = columns.find((column: any) => column.dataKey === before)?.ordinal;
      const right = columns.find((column: any) => column.dataKey === after)?.ordinal;
      const ordinal = left != null && right != null ? (left + right) / 2 : left != null ? left + 0.5 : right != null ? right - 0.5 : statusColumnOrdinal(columns);
      const prefs = view._getColumnPrefs();
      view._storeColumnPrefs({ ...prefs, [this.key]: { ...prefs[this.key], ...settings, ordinal } });
      this.zotero.Prefs.set(PLACEMENT_PREF, "", true);
    } catch (error) { this.zotero.debug?.(`[TeXGlot] column placement restore failed: ${String(error)}`); }
  }

  refreshWindow(window: any): void {
    // Registering a column does not evict Zotero's existing per-row data cache.
    // Refresh the current view once; subsequent views load lazily as usual.
    for (const id of window?.ZoteroPane?.itemsView?.getSortedItems?.(true) ?? []) {
      if (Number.isInteger(id)) this.queueRefresh(id);
    }
  }

  private data(item: ZoteroLikeItem): string {
    if (!item.id || item.deleted || item.isAttachment?.() || item.isNote?.() || item.isRegularItem?.() === false) return "";
    let entry = this.cache.get(item.id);
    if (!entry) {
      entry = { item, status: { kind: "checking", details: [] }, children: new Set() };
      this.cache.set(item.id, entry);
      void this.load(item.id, entry);
    }
    const activities = [...(this.activities.get(item.id)?.values() ?? [])];
    const activity = activities.find((value) => value.state === "processing") ?? activities[0];
    return statusData(activity ? { kind: activity.state, details: activity.message ? [activity.message] : [] } : entry.status, this.chinese);
  }

  private async load(id: number, entry: CacheEntry): Promise<void> {
    try {
      await Promise.all([entry.item.loadDataType?.("childItems"), entry.item.loadDataType?.("itemData")]);
      const ids = Object.values(entry.item.getAttachments?.() ?? {}).map(Number);
      entry.children = new Set(ids);
      const children: any[] = this.zotero.Items?.getAsync
        ? await this.zotero.Items.getAsync(ids)
        : ids.map((childID) => this.zotero.Items?.get?.(childID)).filter(Boolean);
      await Promise.all(children.filter(isPdfAttachment).map(async (child) => {
        await Promise.all([child.loadDataType?.("note"), child.loadDataType?.("itemData")]);
      }));
      entry.status = translationStatus(entry.item, children, this.chinese);
    } catch (error) {
      entry.status = { kind: "review", details: [this.chinese ? "无法读取翻译状态" : "Unable to read translation status"] };
      this.zotero.debug?.(`[TeXGlot] status lookup failed: ${String(error)}`);
    }
    if (!this.closed && this.cache.get(id) === entry) this.queueRefresh(id);
  }

  setActivity(parent: ZoteroLikeItem, requestKey: string, activity: TranslationActivity | null): void {
    if (!parent.id || this.closed) return;
    let activities = this.activities.get(parent.id);
    if (!activities) { activities = new Map(); this.activities.set(parent.id, activities); }
    if (activity) activities.set(requestKey, activity);
    else activities.delete(requestKey);
    if (!activities.size) this.activities.delete(parent.id);
    this.queueRefresh(parent.id);
  }

  private queueRefresh(id: number): void {
    if (this.closed) return;
    this.refreshIDs.add(id);
    if (this.refreshTimer) return;
    this.refreshTimer = setTimeout(() => {
      this.refreshTimer = undefined;
      const ids = [...this.refreshIDs];
      this.refreshIDs.clear();
      // Refresh only the affected rows, without re-registering columns or scanning the library.
      Promise.resolve(this.zotero.Notifier?.trigger?.("refresh", "item", ids, {}))
        .catch((error) => this.zotero.debug?.(`[TeXGlot] status redraw failed: ${String(error)}`));
    }, 100);
  }

  private ensureStyle(doc: Document): void {
    if (doc.getElementById("texglot-status-style")) return;
    const style = doc.createElement("style");
    style.id = "texglot-status-style";
    style.textContent = `.texglot-status-cell{color:#8b9099}.texglot-status-cell[data-status="○"]{opacity:.45}
      .texglot-status-cell[data-status="✓"]{color:#23865b}.texglot-status-cell[data-status="◷"]{color:#3178d3}
      .texglot-status-cell[data-status="!"]{color:#b77916}.row.selected .texglot-status-cell{color:inherit;opacity:1}
      @media(prefers-color-scheme:dark){.texglot-status-cell[data-status="✓"]{color:#6acc9b}.texglot-status-cell[data-status="◷"]{color:#7fb3ff}.texglot-status-cell[data-status="!"]{color:#e0b159}.row.selected .texglot-status-cell{color:inherit}}`;
    (doc.head ?? doc.documentElement).appendChild(style);
    this.styles.add(style);
  }

  dispose(): void {
    this.closed = true;
    this.preservePlacement();
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    if (this.observer != null) this.zotero.Notifier?.unregisterObserver?.(this.observer);
    if (this.key) this.zotero.ItemTreeManager.unregisterColumn(this.key);
    for (const style of this.styles) style.remove();
    this.cache.clear(); this.activities.clear();
  }
}

const columns = new WeakMap<object, StatusColumn>();

/** Zotero registers columns globally, while the add-on starts once per main window. */
export function installStatusColumn(zotero: any, window?: any, rootURI?: string): { setActivity: StatusColumn["setActivity"]; dispose: () => void } | undefined {
  if (!zotero?.ItemTreeManager?.registerColumn) return undefined;
  let column = columns.get(zotero);
  if (!column) { column = new StatusColumn(zotero, window, rootURI); columns.set(zotero, column); }
  column.references++;
  column.refreshWindow(window);
  let disposed = false;
  return {
    setActivity: column.setActivity.bind(column),
    dispose: () => {
      if (disposed) return;
      disposed = true;
      if (--column!.references === 0) { column!.dispose(); columns.delete(zotero); }
    },
  };
}
