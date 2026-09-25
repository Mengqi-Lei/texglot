import { TeXGlotIntegrationError } from "./errors.js";
import { hasAttachmentFile, isGeneratedTranslation, isPdfAttachment, parseVersionedArxiv } from "./arxiv.js";
import { completeSourceSelection, loadPaper, originalForTranslation, resolveLocalSource } from "./source-resolution.js";
import { TeXGlotBridge } from "./bridge.js";
import type { JobOptions, SourceSelection, ZoteroLikeItem, ZoteroRuntime } from "./types.js";
import { importArtifact, importComparison } from "./attachments.js";
import { readTranslationMetadata } from "./translation-metadata.js";
import { setMenuIcon } from "./menu-icon.js";

const MENU_ID = "texglot-translate-menu";
const inFlight = new Set<string>();
const resolving = new Set<string>();

function requestKey(selection: SourceSelection, language: string): string {
  const source = selection.source;
  return String(selection.parent.libraryID ?? "") + ":" + String(selection.parent.id ?? selection.parent.key ?? "") + ":" +
    (source.type === "arxiv" ? source.id : source.path) + ":" + language;
}

async function matchingTranslation(parent: ZoteroLikeItem, runtime: ZoteroRuntime, arxivId: string, language: string): Promise<ZoteroLikeItem | undefined> {
  const { children } = await loadPaper(parent, runtime);
  const candidates = children.filter((child) => {
    const marker = readTranslationMetadata(child);
    return isPdfAttachment(child) && marker?.artifact === "translated" && marker.arxiv_id === arxivId && marker.language === language;
  });
  const available = await Promise.all(candidates.map(hasAttachmentFile));
  const matches = candidates.filter((_, index) => available[index]);
  if (matches.length > 1) throw new TeXGlotIntegrationError("TRANSLATION_AMBIGUOUS", "找到多个相同版本和语言的译文，请选择具体的译文附件。");
  return matches[0];
}

/** Double-click is local and non-interactive; an uncertain pair opens normally. */
export async function defaultComparisonForParent(parent: ZoteroLikeItem, runtime: ZoteroRuntime): Promise<{ original: ZoteroLikeItem; translated: ZoteroLikeItem } | undefined> {
  if (parent.deleted || parent.isAttachment?.() || parent.isRegularItem?.() === false) return undefined;
  const { children } = await loadPaper(parent, runtime);
  let source: SourceSelection | undefined;
  try { source = await resolveLocalSource(parent, runtime, false); } catch { return undefined; }
  if (!source?.attachment || source.source.type !== "arxiv") return undefined;
  const id = source.source.id;
  const translations = children.filter((child) => isPdfAttachment(child) && readTranslationMetadata(child)?.artifact === "translated" && readTranslationMetadata(child)?.arxiv_id === id);
  const available = await Promise.all(translations.map(hasAttachmentFile));
  const candidates = translations.filter((_, index) => available[index]);
  if (candidates.length !== 1) return undefined;
  return { original: source.attachment, translated: candidates[0] };
}

async function openExisting(original: ZoteroLikeItem | undefined, translated: ZoteroLikeItem, runtime: ZoteroRuntime): Promise<void> {
  if (!original) throw new TeXGlotIntegrationError("ORIGINAL_PDF_MISSING", "已有译文，但没有找到可确认版本的原文 PDF。请重新使用 TeXGlot 获取配套原文。");
  if (!runtime.openSplitReader) throw new TeXGlotIntegrationError("SPLIT_READER_UNAVAILABLE", "当前 Zotero 不支持打开 TeXGlot 分屏阅读。");
  await runtime.openSplitReader(original, translated);
  runtime.notify?.("已打开已有的 TeXGlot 原文/译文分屏阅读。", "info");
}

export async function translateItems(items: ZoteroLikeItem[], runtime: ZoteroRuntime, bridge: TeXGlotBridge, options: JobOptions = {}): Promise<string[]> {
  if (!items.length) throw new TeXGlotIntegrationError("NO_SELECTION", "请先在 Zotero 中选择文献。");
  const pending: Array<{ item: ZoteroLikeItem; selection: SourceSelection; lockKey: string }> = [];
  const seen = new Set<string>();
  for (const item of items) {
    const lockKey = `${item.libraryID ?? ""}:${item.id ?? item.key}:${options.language ?? "简体中文"}`;
    if (resolving.has(lockKey)) { runtime.notify?.("这篇论文已有 TeXGlot 操作正在处理。", "info"); continue; }
    resolving.add(lockKey);
    let retained = false;
    let parent: ZoteroLikeItem | undefined;
    try {
      ({ parent } = await loadPaper(item, runtime));
      runtime.setTranslationActivity?.(parent, lockKey, { state: "processing", message: "正在识别论文版本" });
      let selection: SourceSelection | undefined;
      if (isGeneratedTranslation(item)) {
        const marker = readTranslationMetadata(item);
        const id = parseVersionedArxiv(marker?.arxiv_id);
        if (!id) throw new TeXGlotIntegrationError("TRANSLATION_METADATA_MISSING", "这个译文缺少来源记录，请选择文献条目重新获取译文。");
        selection = await originalForTranslation(parent, item, runtime);
        if (options.reuseExisting !== false && selection?.attachment && await hasAttachmentFile(item)) {
          await openExisting(selection.attachment, item, runtime);
          continue;
        }
        selection ??= { parent, source: { type: "arxiv", id }, useTaskOriginal: true, sourceEvidence: "saved-translation", warnings: [] };
      } else {
        selection = await resolveLocalSource(item, runtime);
        if (!selection) continue;
        selection = await completeSourceSelection(selection, runtime, (id) => bridge.resolveArxiv(id));
        if (!selection) continue;
      }
      const key = requestKey(selection, options.language ?? "简体中文");
      if (seen.has(key) || inFlight.has(key)) continue;
      seen.add(key);
      const translated = options.reuseExisting !== false && selection.source.type === "arxiv"
        ? await matchingTranslation(parent, runtime, selection.source.id, options.language ?? "简体中文") : undefined;
      if (translated && selection.attachment) {
        await openExisting(selection.attachment, translated, runtime);
        continue;
      }
      pending.push({ item, selection, lockKey });
      retained = true;
    } catch (error) {
      runtime.notify?.(error instanceof Error ? error.message : "无法确定这篇论文的翻译来源。", "error");
    } finally {
      if (parent) runtime.setTranslationActivity?.(parent, lockKey, null);
      if (!retained) resolving.delete(lockKey);
    }
  }
  if (!pending.length) return [];

  let health;
  try { health = await bridge.health(); }
  catch (error) { pending.forEach(({ lockKey }) => resolving.delete(lockKey)); throw error; }
  const jobs: string[] = [];
  for (const { item, selection, lockKey } of pending) {
    const key = requestKey(selection, options.language ?? "简体中文");
    if (inFlight.has(key)) {
      resolving.delete(lockKey);
      runtime.notify?.("这篇论文已有 TeXGlot 任务正在处理。", "info");
      continue;
    }
    if (selection.source.type === "arxiv" && !health.capabilities.arxivLatex ||
        selection.source.type === "latex" && !health.capabilities.latexUpload) {
      resolving.delete(lockKey);
      runtime.notify?.("当前 TeXGlot 服务不支持所选翻译来源。", "error");
      continue;
    }
    inFlight.add(key);
    runtime.setTranslationActivity?.(selection.parent, key, { state: "processing", message: options.reuseExisting !== false ? "正在查找已有译文" : "正在提交重新翻译任务" });
    try {
      const task = await bridge.createJob(selection, { ...options, itemKey: selection.parent.key ?? item.key, libraryId: selection.parent.libraryID ?? item.libraryID });
      jobs.push(task.id);
      const completed = task.status === "completed" || task.status === "completed_with_warnings";
      runtime.notify?.(task.reuse && completed ? "正在导入 TeXGlot 文献库中已有的译文。"
        : task.reuse === "active" ? "已关联 TeXGlot 中正在处理的任务。"
        : task.reuse ? "正在读取之前提交的 TeXGlot 任务。"
        : `TeXGlot 已提交 ${selection.source.type === "arxiv" ? selection.source.id : "源码"}。`, "info");
      const result = completed ? Promise.resolve(task) : bridge.pollJob(task.id, { onUpdate: (current) => {
        runtime.setTranslationActivity?.(selection.parent, key, { state: "processing", message: current.message });
        runtime.notify?.(`TeXGlot ${task.id}: ${current.message ?? current.status}`, "info");
      } });
      void result.then(async (final) => {
      if (final.status === "completed" || final.status === "completed_with_warnings") {
        runtime.notify?.(
          final.status === "completed_with_warnings" || final.quality === "completed_with_warnings"
            ? `TeXGlot 任务 ${task.id} 已生成 PDF，但部分内容需检查。`
            : `TeXGlot 任务 ${task.id} 已完成。`,
          "info",
        );
        let translatedArtifact: Awaited<ReturnType<typeof importArtifact>> | undefined;
        let originalPDF: ZoteroLikeItem | undefined;
        try {
          const comparison = await importComparison(bridge, final, selection, runtime, options.language);
          translatedArtifact = comparison.translated;
          originalPDF = comparison.original;
          runtime.setTranslationActivity?.(selection.parent, key, null);
          if (options.importTranslatedSource) await importArtifact(bridge, final, selection, runtime, { language: options.language, kind: "source" });
        } catch (error) {
          if (!translatedArtifact) runtime.setTranslationActivity?.(selection.parent, key, { state: "review", message: "译文已生成，但尚未导入 Zotero" });
          runtime.notify?.(error instanceof Error ? `译文已生成，但导入 Zotero 失败：${error.message}` : "译文已生成，但导入 Zotero 失败。", "error");
        }
        let openedNativeReader = false;
        if (options.open !== "none" && translatedArtifact?.attachment && runtime.openSplitReader) {
          try {
            if (originalPDF) {
              await runtime.openSplitReader(originalPDF, translatedArtifact.attachment as ZoteroLikeItem);
              openedNativeReader = true;
            }
          } catch (error) {
            runtime.notify?.(error instanceof Error ? `译文已导入，但打开 Zotero 分屏阅读失败：${error.message}` : "译文已导入，但打开 Zotero 分屏阅读失败。", "error");
          }
        }
        if (options.open !== "none" && !openedNativeReader && health.capabilities.readerDeepLink) {
          runtime.openReader?.(task.id, options.open ?? "comparison", bridge.baseUrl);
        }
      } else {
        const detail = typeof final.error === "string" ? final.error : final.error?.message ?? final.status;
        runtime.setTranslationActivity?.(selection.parent, key, { state: "review", message: `翻译未完成：${detail}` });
        runtime.notify?.(`TeXGlot 任务 ${task.id} 未完成：${detail}`, "error");
      }
      }).catch((error) => {
        runtime.setTranslationActivity?.(selection.parent, key, { state: "review", message: error instanceof Error ? error.message : "无法读取任务状态" });
        runtime.notify?.(error instanceof Error ? error.message : "TeXGlot 任务失败。", "error");
      }).finally(() => { inFlight.delete(key); resolving.delete(lockKey); });
    } catch (error) {
      inFlight.delete(key);
      resolving.delete(lockKey);
      runtime.setTranslationActivity?.(selection.parent, key, { state: "review", message: error instanceof Error ? error.message : "提交翻译失败" });
      runtime.notify?.(error instanceof Error ? error.message : "提交 TeXGlot 任务失败。", "error");
    }
  }
  return jobs;
}

export function installContextMenu(runtime: ZoteroRuntime, bridge = new TeXGlotBridge()): () => void {
  const runTranslation = (items: ZoteroLikeItem[], options?: JobOptions) => {
    void translateItems(items, runtime, bridge, options).catch((error) => runtime.notify?.(error instanceof Error ? error.message : "TeXGlot 操作失败。", "error"));
  };
  let nativeCleanup: (() => void) | undefined;
  try {
    nativeCleanup = runtime.registerContextMenu?.(runTranslation);
  } catch (error) {
    runtime.notify?.(error instanceof Error ? `TeXGlot 菜单注册稍后重试：${error.message}` : "TeXGlot 菜单注册稍后重试。", "error");
  }
  if (nativeCleanup) return nativeCleanup;

  const document = runtime.document ?? globalThis.document;
  if (!document) return () => undefined;

  // Zotero creates #zotero-itemmenu lazily. Registering only during bootstrap
  // is racy when the plugin starts before the main window has built its menu.
  let menuItems: HTMLElement[] = [];
  const ensureMenuItem = () => {
    const menu = document.querySelector("#zotero-itemmenu") as HTMLElement | null;
    if (!menu || nativeCleanup || menuItems.length && menuItems.every((item) => item.isConnected)) return;
    menuItems = [
      { id: MENU_ID, label: "使用 TeXGlot 翻译并对照阅读", options: undefined },
      { id: `${MENU_ID}-again`, label: "使用 TeXGlot 重新翻译（保留已有译文）", options: { reuseExisting: false } },
    ].map(({ id, label, options }) => {
      const existing = menu.querySelector(`#${id}`) as HTMLElement | null;
      if (existing) return existing;
      const item = (document as Document & { createXULElement?: (name: string) => HTMLElement }).createXULElement?.("menuitem") ?? document.createElement("menuitem");
      item.id = id;
      item.setAttribute("label", label);
      setMenuIcon(item, runtime.iconURI, Boolean(runtime.isMac));
      item.addEventListener("command", () => runTranslation(runtime.getSelectedItems?.() ?? [], options));
      menu.appendChild(item);
      return item;
    });
  };

  const onWindowEvent = () => ensureMenuItem();
  document.addEventListener("DOMContentLoaded", onWindowEvent, true);
  document.addEventListener("popupshowing", onWindowEvent, true);
  ensureMenuItem();
  // Cover the common startup race without keeping a permanent observer. The
  // popupshowing listener handles a later menu recreation.
  const timers = [0, 100, 500, 1500].map((delay) => setTimeout(ensureMenuItem, delay));
  let nativeRetry: ReturnType<typeof setInterval> | undefined;
  let attempts = 0;
  const retryNative = () => {
    if (nativeCleanup || attempts++ >= 100) {
      if (nativeRetry) clearInterval(nativeRetry);
      nativeRetry = undefined;
      return;
    }
    try {
      nativeCleanup = runtime.registerContextMenu?.(runTranslation);
      if (nativeCleanup) {
        if (nativeRetry) clearInterval(nativeRetry);
        nativeRetry = undefined;
        menuItems.forEach((item) => item.remove());
        menuItems = [];
      }
    } catch {
      // Zotero may expose MenuManager before its library menu target is ready.
    }
  };
  nativeRetry = setInterval(retryNative, 100);
  return () => {
    document.removeEventListener("DOMContentLoaded", onWindowEvent, true);
    document.removeEventListener("popupshowing", onWindowEvent, true);
    timers.forEach(clearTimeout);
    if (nativeRetry) clearInterval(nativeRetry);
    nativeRetry = undefined;
    nativeCleanup?.();
    menuItems.forEach((item) => item.remove());
    menuItems = [];
  };
}
