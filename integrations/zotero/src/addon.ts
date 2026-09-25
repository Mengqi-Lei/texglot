import { installContextMenu } from "./menus.js";
import { TeXGlotBridge } from "./bridge.js";
import type { ZoteroRuntime } from "./types.js";
import { createZoteroRuntime, type ZoteroHost } from "./zotero-runtime.js";

const instances = new Map<object, () => void>();
const defaultInstance = {};

function instanceKey(runtime?: ZoteroRuntime | ZoteroHost): object {
  if (runtime && "window" in runtime && runtime.window) return runtime.window;
  return runtime ?? defaultInstance;
}

export function startup(runtime?: ZoteroRuntime | ZoteroHost): void {
  const key = instanceKey(runtime);
  if (instances.has(key)) return;
  const adapter = runtime && "getSelectedItems" in runtime
    ? runtime as ZoteroRuntime
    : createZoteroRuntime(runtime as ZoteroHost | undefined);
  const menuCleanup = installContextMenu(adapter, new TeXGlotBridge());
  instances.set(key, () => {
    menuCleanup();
    adapter.dispose?.();
  });
}

export function shutdownWindow(window: object): void {
  const dispose = instances.get(window);
  if (!dispose) return;
  instances.delete(window);
  dispose();
}

export function shutdown(): void {
  for (const key of [...instances.keys()]) shutdownWindow(key);
}
