export type JobDeepLink = { id: string; view: "details" | "reader" };

/** Resolve links opened by integrations without depending on the current UI state. */
export function parseJobDeepLink(search: string): JobDeepLink | null {
  const params = new URLSearchParams(search);
  const id = params.get("job") ?? params.get("reader");
  if (!id || !/^[a-zA-Z0-9_-]{1,128}$/.test(id)) return null;
  return {
    id,
    view: params.has("reader") && !params.has("job") || params.get("view") === "reader"
      ? "reader"
      : "details",
  };
}

export function resolveJobDeepLink<T extends { id: string; artifacts: Record<string, unknown> }>(
  jobs: T[],
  link: JobDeepLink,
): { kind: "missing" } | { kind: "details" | "reader"; job: T } {
  const job = jobs.find((candidate) => candidate.id === link.id);
  if (!job) return { kind: "missing" };
  return { kind: link.view === "reader" && Boolean(job.artifacts.translated) ? "reader" : "details", job };
}
