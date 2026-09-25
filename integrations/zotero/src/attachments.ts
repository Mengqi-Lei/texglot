import { TeXGlotIntegrationError } from "./errors.js";
import type { SourceSelection, TaskSnapshot, ZoteroLikeItem, ZoteroRuntime } from "./types.js";
import { TeXGlotBridge } from "./bridge.js";
import { hasAttachmentFile, isPdfAttachment } from "./arxiv.js";
import { readTranslationMetadata } from "./translation-metadata.js";

const PDF_HEADER = "%PDF-";

function metadataNote(task: TaskSnapshot, source: SourceSelection, language: string, kind: "translated" | "source" | "original", fingerprint?: string): string {
  return JSON.stringify({ provider: "texglot", arxiv_id: source.source.type === "arxiv" ? source.source.id : undefined,
    language, task_id: task.id, artifact: kind, core_version: "unknown",
    translation_status: task.quality === "completed_with_warnings" ? task.quality : task.status,
    source_attachment_key: kind === "translated" ? source.attachment?.key : undefined,
    source_fingerprint: kind === "translated" ? source.sourceFingerprint : undefined,
    source_evidence: source.sourceEvidence, artifact_fingerprint: fingerprint });
}

function hasMarker(item: unknown, task: TaskSnapshot, source: SourceSelection, language: string): boolean {
  const note = (item as ZoteroLikeItem)?.getNote?.();
  if (!note) return false;
  try {
    const value = JSON.parse(note) as Record<string, unknown>;
    return value.provider === "texglot" && value.task_id === task.id && value.language === language && (source.source.type !== "arxiv" || value.arxiv_id === source.source.id);
  } catch { return false; }
}

/**
 * Runtime-independent attachment import. The Zotero adapter supplies importAttachment;
 * tests and future hosts can provide an equivalent implementation without touching the bridge.
 */
export async function importArtifact(
  bridge: TeXGlotBridge,
  task: TaskSnapshot,
  source: SourceSelection,
  runtime: ZoteroRuntime,
  options: { language?: string; kind?: "translated" | "source" | "original" } = {},
): Promise<{ imported: boolean; attachment?: unknown; fingerprint?: string }> {
  if (!runtime.importAttachment) throw new TeXGlotIntegrationError("ATTACHMENT_IMPORT_UNAVAILABLE", "当前 Zotero 运行时未提供附件导入能力。");
  const kind = options.kind ?? "translated";
  const language = options.language ?? "简体中文";
  const existing = await runtime.findAttachment?.(source.parent, metadataNote(task, source, language, kind));
  if (existing) return { imported: false, attachment: existing, fingerprint: readTranslationMetadata(existing as ZoteroLikeItem)?.artifact_fingerprint };
  const bytes = await bridge.artifact(task.id, kind);
  if (kind !== "source" && new TextDecoder().decode(bytes.slice(0, 5)) !== PDF_HEADER) {
    throw new TeXGlotIntegrationError("ARTIFACT_INVALID", "TeXGlot 返回的文件不是有效 PDF。");
  }
  const fingerprint = kind !== "source" ? await runtime.hashBytes?.(bytes) : undefined;
  const note = metadataNote(task, source, language, kind, fingerprint);
  const title = kind === "translated"
    ? `[TeXGlot] ${language} · ${source.source.type === "arxiv" ? `arXiv ${source.source.id}` : "译文"}.pdf`
    : kind === "original" ? `[TeXGlot] 对照原文 · ${source.source.type === "arxiv" ? `arXiv ${source.source.id}` : "LaTeX"}.pdf`
    : `[TeXGlot] translated-source · ${source.source.type === "arxiv" ? `arXiv ${source.source.id}` : "source"}.zip`;
  const attachment = await runtime.importAttachment(bytes, { parent: source.parent, title, note, extension: kind === "source" ? "zip" : "pdf" });
  return { imported: true, attachment, fingerprint };
}

export async function importComparison(bridge: TeXGlotBridge, task: TaskSnapshot, source: SourceSelection, runtime: ZoteroRuntime, language?: string) {
  let original = source.attachment;
  let fingerprint = source.sourceFingerprint;
  if (source.useTaskOriginal || !isPdfAttachment(original) || !original || !await hasAttachmentFile(original)) {
    const result = await importArtifact(bridge, task, source, runtime, { language, kind: "original" });
    original = result.attachment as ZoteroLikeItem | undefined;
    fingerprint = result.fingerprint;
  }
  const translated = await importArtifact(bridge, task, { ...source, attachment: original, sourceFingerprint: fingerprint }, runtime, { language });
  return { original, translated };
}

export { hasMarker };
