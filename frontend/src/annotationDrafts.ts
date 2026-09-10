// Keep unsent keystrokes across an immediate refresh or a local-service outage.
// Completed saves remove only their own draft, never a newer edit.
export type AnnotationDraft = {
  id: string;
  comment: string;
  revision: number;
  updated: number;
};
const prefix = (job: string) => `texglot:annotation-draft:${job}:`;
export function writeDraft(job: string, draft: AnnotationDraft) {
  try {
    localStorage.setItem(prefix(job) + draft.id, JSON.stringify(draft));
  } catch {
    /* API saving still works when browser storage is unavailable. */
  }
}
export function clearDraft(job: string, id: string, savedComment: string) {
  try {
    const key = prefix(job) + id,
      raw = localStorage.getItem(key);
    if (raw && JSON.parse(raw).comment === savedComment)
      localStorage.removeItem(key);
  } catch {}
}
export function readDrafts(job: string): AnnotationDraft[] {
  try {
    return Object.keys(localStorage)
      .filter((key) => key.startsWith(prefix(job)))
      .flatMap((key) => {
        try {
          const value = JSON.parse(localStorage.getItem(key) || "null");
          return value &&
            typeof value.id === "string" &&
            typeof value.comment === "string" &&
            Number.isInteger(value.revision)
            ? [value]
            : [];
        } catch {
          return [];
        }
      })
      .sort((a, b) => b.updated - a.updated);
  } catch {
    return [];
  }
}
