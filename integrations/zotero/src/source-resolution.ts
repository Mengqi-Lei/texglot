import { TeXGlotIntegrationError } from "./errors.js";
import { baseArxivId, hasAttachmentFile, isGeneratedTranslation, isPdfAttachment, itemArxivReferences, parentIdOf, parseVersionedArxiv, readLatexSource } from "./arxiv.js";
import { readTranslationMetadata } from "./translation-metadata.js";
import type { SourceSelection, ZoteroLikeItem, ZoteroRuntime } from "./types.js";

type Evidence = { base?: string; id?: string };
type Candidate = Evidence & { item: ZoteroLikeItem; available: boolean; fingerprint?: string; evidence?: string };

function summarize(ids: string[], allowVersionChoice = false): Evidence {
  const bases = [...new Set(ids.map(baseArxivId))];
  const versions = [...new Set(ids.map(parseVersionedArxiv).filter((id): id is string => Boolean(id)))];
  if (bases.length > 1) throw new TeXGlotIntegrationError("ARXIV_ID_CONFLICT", "条目中出现了不同论文的 arXiv 编号，请选择正确的原文 PDF。");
  if (versions.length > 1 && !allowVersionChoice) throw new TeXGlotIntegrationError("ARXIV_VERSION_AMBIGUOUS", "这个附件中有相互冲突的版本信息，请选择其他原文 PDF。");
  return { base: bases[0], id: versions.length === 1 ? versions[0] : undefined };
}

/** Prefer a real version stamp, never the first arbitrary paper cited on page one. */
export function pdfArxivVersion(text: string, expectedBase?: string): string | undefined {
  const pattern = /arxiv\s*:\s*((?:\d{4}\s*\.\s*\d{4,5}|[a-z][a-z.\-]+\s*\/\s*\d{7})\s*v\s*[1-9]\d*)(?![\w])\s*(\[[a-z][a-z.\-]*(?:\.[a-z]+)?\])?/gi;
  const stamps = [...text.matchAll(pattern)].map((match) => ({ id: match[1].replace(/\s+/g, ""), strong: Boolean(match[2]) }));
  const strong = stamps.filter((stamp) => stamp.strong);
  const evidence = strong.length ? strong : stamps.filter((stamp) => expectedBase && baseArxivId(stamp.id) === expectedBase);
  const resolved = summarize(evidence.map((stamp) => stamp.id));
  if (resolved.base && expectedBase && resolved.base !== expectedBase) {
    throw new TeXGlotIntegrationError("ARXIV_ID_CONFLICT", "PDF 首页的论文编号与文献条目不同，请选择正确的原文附件。");
  }
  return resolved.id;
}

export async function loadPaper(item: ZoteroLikeItem, runtime: ZoteroRuntime): Promise<{ parent: ZoteroLikeItem; children: ZoteroLikeItem[] }> {
  let parent = item;
  if (item.isAttachment?.()) {
    const id = parentIdOf(item);
    if (!id) throw new TeXGlotIntegrationError("PARENT_ITEM_REQUIRED", "请先将附件加入 Zotero 文献条目，再使用 TeXGlot 翻译。");
    parent = await runtime.resolveItemAsync?.(id) ?? runtime.resolveItem?.(id)!;
    if (!parent) throw new TeXGlotIntegrationError("PARENT_ITEM_MISSING", "无法读取此附件所属的文献条目。");
  }
  await Promise.all([parent.loadDataType?.("itemData"), parent.loadDataType?.("childItems")]);
  const raw = parent.getAttachments?.() ?? [];
  const ids = [...new Set(Array.isArray(raw) ? raw : Object.values(raw))];
  const children = (await Promise.all(ids.map(async (id) => await runtime.resolveItemAsync?.(id) ?? runtime.resolveItem?.(id))))
    .filter((child): child is ZoteroLikeItem => Boolean(child && !child.deleted));
  await Promise.all(children.map(async (child) => {
    await child.loadDataType?.("itemData");
    // Notes are optional on source PDFs, but required to identify our own files.
    try { await child.loadDataType?.("note"); } catch { /* not a note-bearing attachment */ }
  }));
  return { parent, children };
}

async function inspectPdf(item: ZoteroLikeItem, expectedBase: string | undefined, runtime: ZoteroRuntime): Promise<Candidate> {
  const exists = await hasAttachmentFile(item);
  const info = exists ? await runtime.readPdfInfo?.(item) : undefined;
  const available = exists && info?.readable !== false;
  const fromPdf = pdfArxivVersion(info?.text ?? "", expectedBase);
  if (fromPdf) return { item, id: fromPdf, base: baseArxivId(fromPdf), available, fingerprint: info?.fingerprint, evidence: "pdf" };
  const marker = readTranslationMetadata(item);
  if (marker?.artifact === "original") {
    const id = parseVersionedArxiv(marker.arxiv_id);
    if (id && marker.artifact_fingerprint && marker.artifact_fingerprint === info?.fingerprint) {
      if (expectedBase && baseArxivId(id) !== expectedBase) throw new TeXGlotIntegrationError("ARXIV_ID_CONFLICT", "对照原文与当前论文编号不一致。");
      return { item, id, base: baseArxivId(id), available, fingerprint: info.fingerprint, evidence: "task-original" };
    }
    return { item, available, fingerprint: info?.fingerprint };
  }
  const metadata = summarize(itemArxivReferences(item));
  if (metadata.base && expectedBase && metadata.base !== expectedBase) {
    throw new TeXGlotIntegrationError("ARXIV_ID_CONFLICT", "原文附件与文献条目的 arXiv 编号不同，请选择正确附件。");
  }
  return { item, ...metadata, available, fingerprint: info?.fingerprint, evidence: "attachment" };
}

function supplementary(item: ZoteroLikeItem): boolean {
  let title = "";
  try { title = String(item.getField?.("title") ?? ""); } catch { /* optional */ }
  return /\b(?:supplement(?:ary)?|appendix|slides?)\b|补充材料|附录|幻灯/i.test(`${title} ${item.attachmentFilename ?? ""}`);
}

function fromCandidate(parent: ZoteroLikeItem, candidate: Candidate, fallback: Evidence): SourceSelection {
  const id = candidate.id ?? fallback.id ?? candidate.base ?? fallback.base;
  if (!id) throw new TeXGlotIntegrationError("SOURCE_NOT_SUPPORTED", "未找到这篇论文的 arXiv 编号。可以在条目网址中添加 arXiv 链接，或选择 LaTeX 源码附件。");
  // Parent-only version information does not establish the identity of an
  // unversioned local PDF. Use the task's own original in that case.
  return { source: { type: "arxiv", id }, parent, attachment: candidate.id && candidate.available ? candidate.item : undefined,
    sourceEvidence: candidate.id ? candidate.evidence : "parent", sourceFingerprint: candidate.fingerprint,
    useTaskOriginal: !candidate.id || !candidate.available, warnings: [] };
}

/** Local identity selection. It never queries arXiv or creates a translation. */
export async function resolveLocalSource(item: ZoteroLikeItem, runtime: ZoteroRuntime, interactive = true): Promise<SourceSelection | undefined> {
  const { parent, children } = await loadPaper(item, runtime);
  if (item.isAttachment?.() && !isGeneratedTranslation(item) && !isPdfAttachment(item)) {
    return readLatexSource(item, runtime.resolveItem, runtime.readFile);
  }
  const parentRefs = itemArxivReferences(parent);
  const parentInfo = summarize(parentRefs.length ? parentRefs : children.filter((child) => !isPdfAttachment(child) && !isGeneratedTranslation(child)).flatMap(itemArxivReferences), true);
  const explicit = isPdfAttachment(item) && !isGeneratedTranslation(item);
  const pdfs = explicit ? [item] : children.filter((child) => isPdfAttachment(child) && !isGeneratedTranslation(child) && !supplementary(child));
  if (!pdfs.length) {
    const id = parentInfo.id ?? parentInfo.base;
    if (!id) throw new TeXGlotIntegrationError("SOURCE_NOT_SUPPORTED", "未找到 arXiv 编号或原文 PDF，请添加 arXiv 链接或选择 LaTeX 源码附件。");
    return { source: { type: "arxiv", id }, parent, useTaskOriginal: true, sourceEvidence: "parent", warnings: [] };
  }
  const candidates: Candidate[] = [];
  const failures: Array<{ item: ZoteroLikeItem; error: unknown }> = [];
  for (const pdf of pdfs) {
    try {
      const candidate = await inspectPdf(pdf, parentInfo.base, runtime);
      if (!candidate.id && candidate.available && candidate.fingerprint && pdf.key) {
        const ids = children.map(readTranslationMetadata).filter((marker) => marker?.artifact === "translated"
          && marker.source_attachment_key === pdf.key && marker.source_fingerprint === candidate.fingerprint)
          .map((marker) => parseVersionedArxiv(marker?.arxiv_id)).filter((id): id is string => Boolean(id));
        const saved = summarize(ids);
        if (saved.id && (!parentInfo.base || saved.base === parentInfo.base)) Object.assign(candidate, saved, { evidence: "saved-binding" });
      }
      candidates.push(candidate);
    }
    catch (error) { failures.push({ item: pdf, error }); }
  }
  if (pdfs.length === 1) {
    if (failures.length) throw failures[0].error;
    return fromCandidate(parent, candidates[0], parentInfo);
  }
  const usable = candidates.some((candidate) => candidate.available) ? candidates.filter((candidate) => candidate.available) : candidates;
  const bases = new Set(usable.flatMap((candidate) => candidate.base ? [candidate.base] : []));
  const versions = usable.filter((candidate) => candidate.id).sort((a, b) => Number(b.id!.match(/v(\d+)$/i)![1]) - Number(a.id!.match(/v(\d+)$/i)![1]));
  const best = versions[0];
  const bound = versions.filter((candidate) => candidate.item.key && candidate.fingerprint && children.some((child) => {
    const marker = readTranslationMetadata(child);
    return marker?.artifact === "translated" && marker.source_attachment_key === candidate.item.key
      && marker.source_fingerprint === candidate.fingerprint && marker.arxiv_id === candidate.id;
  }));
  // An explicitly adopted task original remains the default next time, even
  // though the user's unverified older PDF was intentionally preserved.
  if (!failures.length && bound.length === 1 && bound[0].id === best?.id) return fromCandidate(parent, bound[0], parentInfo);
  if (!failures.length && versions.length === usable.length && bases.size === 1 && best && versions.filter((c) => c.id === best.id).length === 1) {
    return fromCandidate(parent, best, parentInfo);
  }
  if (!interactive) return undefined;
  if (!runtime.chooseAttachment) throw new TeXGlotIntegrationError("SOURCE_AMBIGUOUS", "有多个可能的原文 PDF，请选择要翻译的附件。");
  const selected = await runtime.chooseAttachment(pdfs.map((pdf) => ({ item: pdf, version: candidates.find((candidate) => candidate.item === pdf)?.id })));
  if (!selected) return undefined;
  const failure = failures.find((candidate) => candidate.item === selected);
  if (failure) throw failure.error;
  return fromCandidate(parent, candidates.find((candidate) => candidate.item === selected)!, parentInfo);
}

/** Pairing uses the same file evidence as translation, including a saved binding. */
export async function originalForTranslation(parent: ZoteroLikeItem, translated: ZoteroLikeItem, runtime: ZoteroRuntime): Promise<SourceSelection | undefined> {
  const marker = readTranslationMetadata(translated);
  const id = parseVersionedArxiv(marker?.arxiv_id);
  if (!id) return undefined;
  const { children } = await loadPaper(parent, runtime);
  const candidates: Candidate[] = [];
  for (const child of children.filter((child) => isPdfAttachment(child) && !isGeneratedTranslation(child))) {
    try {
      const candidate = await inspectPdf(child, baseArxivId(id), runtime);
      if (!candidate.available) continue;
      if (child.key && child.key === marker?.source_attachment_key && marker.source_fingerprint && candidate.fingerprint === marker.source_fingerprint) {
        if (candidate.id && candidate.id !== id) continue;
        return { ...fromCandidate(parent, { ...candidate, id }, {}), sourceEvidence: "saved-binding" };
      }
      if (candidate.id === id) candidates.push(candidate);
    } catch { /* an unrelated or broken sibling is not an alternative original */ }
  }
  return candidates.length === 1 ? fromCandidate(parent, candidates[0], {}) : undefined;
}

/** Official fallback is deliberate: never relabel an unknown local file. */
export async function completeSourceSelection(selection: SourceSelection, runtime: ZoteroRuntime, resolve: (id: string) => Promise<{ id: string }>): Promise<SourceSelection | undefined> {
  if (selection.source.type !== "arxiv") return selection;
  const { children } = await loadPaper(selection.parent, runtime);
  const originals = children.filter((child) => isPdfAttachment(child) && !isGeneratedTranslation(child) && !supplementary(child));
  const versioned = parseVersionedArxiv(selection.source.id);
  if (versioned && !selection.useTaskOriginal) return selection;
  const resolved = versioned ? { id: versioned } : await resolve(selection.source.id);
  if (baseArxivId(resolved.id) !== baseArxivId(selection.source.id) || !parseVersionedArxiv(resolved.id)) {
    throw new TeXGlotIntegrationError("ARXIV_ID_CONFLICT", "arXiv 返回的论文版本与当前条目不一致，请稍后重试。");
  }
  if (originals.length && selection.sourceEvidence !== "attachment") {
    const choice = await runtime.confirmOfficialSource?.(resolved.id, originals.length > 1) ?? "cancel";
    if (choice === "cancel") return undefined;
    if (choice === "choose") {
      const item = await runtime.chooseAttachment?.(originals.map((item) => ({ item })));
      if (!item) return undefined;
      const selected = await resolveLocalSource(item, runtime);
      if (!selected) return undefined;
      // An unverifiable alternative still requires acceptance of the official
      // original; selecting a file alone must not imply that acceptance.
      return completeSourceSelection(selected, runtime, resolve);
    }
  }
  return { ...selection, source: { type: "arxiv", id: resolved.id }, attachment: undefined,
    useTaskOriginal: true, sourceFingerprint: undefined, sourceEvidence: "official" };
}
