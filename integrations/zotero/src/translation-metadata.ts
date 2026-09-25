import type { ZoteroLikeItem } from "./types.js";

export interface TranslationMetadata {
  provider: "texglot";
  artifact: "translated" | "source" | "original";
  task_id?: string;
  language?: string;
  arxiv_id?: string;
  translation_status?: string;
  source_attachment_key?: string;
  source_fingerprint?: string;
  artifact_fingerprint?: string;
  source_evidence?: string;
}

/** Read the attachment marker independently of its user-editable title. */
export function readTranslationMetadata(item: ZoteroLikeItem): TranslationMetadata | undefined {
  try {
    const value = JSON.parse(item.getNote?.() || "");
    if (value?.provider !== "texglot" || !["translated", "source", "original"].includes(value.artifact)) return undefined;
    return {
      provider: "texglot", artifact: value.artifact,
      task_id: typeof value.task_id === "string" ? value.task_id : undefined,
      language: typeof value.language === "string" ? value.language : undefined,
      arxiv_id: typeof value.arxiv_id === "string" ? value.arxiv_id : undefined,
      translation_status: typeof value.translation_status === "string" ? value.translation_status : undefined,
      source_attachment_key: typeof value.source_attachment_key === "string" ? value.source_attachment_key : undefined,
      source_fingerprint: typeof value.source_fingerprint === "string" ? value.source_fingerprint : undefined,
      artifact_fingerprint: typeof value.artifact_fingerprint === "string" ? value.artifact_fingerprint : undefined,
      source_evidence: typeof value.source_evidence === "string" ? value.source_evidence : undefined,
    };
  } catch {
    return undefined;
  }
}

export function sameTranslationArtifact(left: TranslationMetadata, right: TranslationMetadata): boolean {
  return Boolean(left.task_id && left.task_id === right.task_id && left.artifact === right.artifact &&
    left.language === right.language && left.arxiv_id === right.arxiv_id);
}
