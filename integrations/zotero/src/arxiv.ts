import { TeXGlotIntegrationError } from "./errors.js";
import type { SourceSelection, ZoteroLikeItem } from "./types.js";
import { readTranslationMetadata } from "./translation-metadata.js";

const VERSIONED = /(?:^|[^\w])((?:\d{4}\.\d{4,5}|[a-z][a-z.\-]+\/\d{7})v[1-9]\d*)(?!\w)/i;
const UNVERSIONED = /(?:^|[^\w])((?:\d{4}\.\d{4,5}|[a-z][a-z.\-]+\/\d{7}))(?![\w])/i;

function normalizeText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * TeXGlot stores translated PDFs as child attachments.  They often inherit
 * the parent arXiv metadata, so treating every child as a possible source can
 * accidentally select the translated PDF as the "original" pane.  Keep this
 * predicate deliberately metadata-based instead of relying on one paper title.
 */
export function isGeneratedTranslation(item: ZoteroLikeItem | undefined): boolean {
  if (!item?.isAttachment?.()) return false;
  if (readTranslationMetadata(item)?.artifact === "original") return false;
  let title = "";
  try { title = normalizeText(item.getField?.("title")).toLowerCase(); } catch { /* optional field not loaded */ }
  if (title.startsWith("[texglot]")) return true;
  try {
    const note = JSON.parse(normalizeText(item.getNote?.())) as Record<string, unknown>;
    return note.provider === "texglot";
  } catch {
    return false;
  }
}

export function isPdfAttachment(item: ZoteroLikeItem | undefined): boolean {
  return Boolean(item?.isFileAttachment?.() && item.attachmentContentType?.toLowerCase() === "application/pdf");
}

export async function hasAttachmentFile(item: ZoteroLikeItem): Promise<boolean> {
  if (item.deleted) return false;
  try { return await item.fileExists?.() !== false; }
  catch { return false; }
}

function encodeBase64(bytes: Uint8Array): string {
  let output = "";
  // Every non-final base64 chunk must contain a multiple of three bytes.
  // Otherwise btoa inserts padding in the middle of the combined string.
  const chunkSize = 0x8000 - (0x8000 % 3);
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    output += btoa(String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length))));
  }
  return output;
}

/** Return only a fully versioned arXiv identifier. A bare ID is intentionally rejected. */
export function parseVersionedArxiv(value: unknown): string | null {
  const text = normalizeText(value).replace(/^arxiv:/i, "").trim();
  const match = text.match(VERSIONED);
  return match?.[1] ?? null;
}

export function hasUnversionedArxiv(value: unknown): boolean {
  const text = normalizeText(value);
  return UNVERSIONED.test(text) && !VERSIONED.test(text);
}

export function itemArxivVersions(item: ZoteroLikeItem): string[] {
  return itemArxivReferences(item).filter((id) => /v[1-9]\d*$/i.test(id));
}

export function baseArxivId(id: string): string { return id.replace(/v\d+$/i, "").toLowerCase(); }

export function arxivReferences(value: string): string[] {
  const pattern = /(?:^|[^A-Za-z0-9_])((?:\d{4}\.\d{4,5}|[a-z][a-z.\-]+\/\d{7})(?:v[1-9]\d*)?)(?![A-Za-z0-9_])/gi;
  return [...new Set([...value.matchAll(pattern)].map((match) => match[1]))];
}

export function itemArxivReferences(item: ZoteroLikeItem): string[] {
  const values = valuesFromItem(item);
  const refs = [...new Set(values.flatMap(arxivReferences))];
  const bases = [...new Set(refs.map(baseArxivId))];
  // Zotero's translator can store the version separately from the base ID.
  if (bases.length === 1) {
    let extra = "";
    try { extra = String(item.getField?.("extra") ?? ""); } catch { /* optional */ }
    for (const match of extra.matchAll(/^\s*version\s*:\s*v?([1-9]\d*)\s*$/gim)) refs.push(`${bases[0]}v${match[1]}`);
  }
  return [...new Set(refs)];
}

function valuesFromItem(item: ZoteroLikeItem): string[] {
  const values: string[] = [];
  for (const field of ["url", "DOI", "archiveID", "extra", "title", "citationKey"]) {
    try {
      const value = item.getField?.(field);
      if (typeof value === "string") values.push(value);
    } catch {
      // Zotero may lazily load an optional field on a child attachment.
    }
  }
  // Zotero.Item.getNote() throws on ordinary bibliographic parent items.
  // Only attachment notes can carry source hints used by this selector.
  if (item.isAttachment?.()) {
    values.push(item.attachmentFilename ?? "", item.attachmentPath ?? "");
    try {
      const note = item.getNote?.();
      if (typeof note === "string") values.push(note);
    } catch {
      // Optional attachment notes may not be loaded yet. URL and item fields
      // remain sufficient for a versioned arXiv source.
    }
  }
  return values;
}

/** Zotero 9 exposes a parentItemID property; retain the method for older adapters. */
export function parentIdOf(item: ZoteroLikeItem): number | false {
  const value = item.parentItemID ?? item.parentID ?? item.getParentID?.();
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : false;
}

function parentOf(item: ZoteroLikeItem, getItem?: (id: number) => ZoteroLikeItem | undefined): ZoteroLikeItem {
  if (!item.isAttachment?.()) return item;
  const parentId = parentIdOf(item);
  if (!parentId || !getItem) return item;
  return getItem(parentId) ?? item;
}

/** Read an explicitly selected LaTeX source; PDF identity is resolved separately. */
export async function readLatexSource(
  item: ZoteroLikeItem,
  getItem?: (id: number) => ZoteroLikeItem | undefined,
  readFile?: (path: string) => Promise<Uint8Array>,
): Promise<SourceSelection> {
  // Explicitly selecting a LaTeX attachment should use that file even when
  // its parent also has arXiv metadata.
  if (item.isAttachment?.() && !isGeneratedTranslation(item)) {
    const path = await item.getFilePath?.();
    if (typeof path === "string" && /\.(?:tex|zip|tar|tgz|tar\.gz|gz)$/i.test(path)) {
      const filename = path.split(/[\\/]/).pop() || "source.zip";
      const contentBase64 = readFile ? encodeBase64(await readFile(path)) : undefined;
      return { source: { type: "latex", path, filename, contentBase64 }, parent: parentOf(item, getItem), attachment: item, warnings: [] };
    }
  }
  throw new TeXGlotIntegrationError(
    "SOURCE_NOT_SUPPORTED",
    "请选择 LaTeX 源码附件（.tex 或源码压缩包），或选择论文原文 PDF。",
  );
}
