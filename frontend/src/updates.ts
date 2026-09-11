export type UpdateState = {
  revision: number;
  status:
    | "idle"
    | "checking"
    | "current"
    | "available"
    | "downloading"
    | "ready"
    | "opening"
    | "error";
  currentVersion: string;
  platform: string;
  arch: string;
  autoCheck: boolean;
  version?: string;
  url?: string;
  canDownload?: boolean;
  progress?: number;
  error?: string;
};
type UpdateBridge = {
  status(): Promise<UpdateState>;
  check(): Promise<UpdateState>;
  download(): Promise<UpdateState>;
  cancel(): Promise<UpdateState>;
  install(): Promise<UpdateState>;
  setAutoCheck(value: boolean): Promise<UpdateState>;
  onChange(callback: (state: UpdateState) => void): () => void;
  onOpen(callback: () => void): () => void;
};
declare global {
  interface Window {
    texglotDesktop?: { updates: UpdateBridge };
  }
}
export const openUpdates = () =>
  window.dispatchEvent(new Event("texglot:open-updates"));

// Readers flush their own pending writes before the desktop service is stopped.
export function beforeUpdate(callback: () => Promise<unknown>) {
  const listener = (event: Event) =>
    (event as CustomEvent<Promise<unknown>[]>).detail.push(
      Promise.resolve().then(callback),
    );
  window.addEventListener("texglot:prepare-update", listener);
  return () => window.removeEventListener("texglot:prepare-update", listener);
}
export async function prepareUpdate() {
  const pending: Promise<unknown>[] = [];
  window.dispatchEvent(
    new CustomEvent("texglot:prepare-update", { detail: pending }),
  );
  await Promise.all(pending);
}
