import type { PdfSourceInfo, ZoteroLikeItem } from "./types.js";

interface PdfHost {
  stat: (path: string) => Promise<{ size: number; lastModified: number }>;
  read: (path: string) => Promise<Uint8Array>;
  hash: (bytes: Uint8Array) => Promise<string>;
  extract: (id: number) => Promise<{ text?: string }>;
  timeoutMs?: number;
}

/** Each unchanged file is read once, including concurrent clicks/windows. */
export function createPdfSourceReader(host: PdfHost) {
  const cache = new Map<string, { stamp: string; result: Promise<PdfSourceInfo> }>();
  const read = async (item: ZoteroLikeItem): Promise<PdfSourceInfo> => {
    try {
      const path = await (item.getFilePathAsync?.() ?? item.getFilePath?.());
      if (!path || item.id === undefined) return { text: "", readable: false };
      const stat = await host.stat(path);
      const stamp = `${stat.size}:${stat.lastModified}`;
      const key = `${item.libraryID}:${item.key ?? item.id}:${path}`;
      const cached = cache.get(key);
      if (cached?.stamp === stamp) return await cached.result;
      const result = (async (): Promise<PdfSourceInfo> => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        try {
          const work = async (): Promise<PdfSourceInfo> => {
            const bytes = await host.read(path);
            if (new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-") return { text: "", readable: false };
            const fingerprint = await host.hash(bytes);
            const { text } = await host.extract(item.id!);
            const after = await host.stat(path);
            if (`${after.size}:${after.lastModified}` !== stamp) throw new Error("PDF changed during inspection");
            return { text: (text ?? "").slice(0, 65536), fingerprint, readable: true };
          };
          return await Promise.race([work(), new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error("PDF inspection timed out")), host.timeoutMs ?? 12000);
          })]);
        } finally {
          if (timer) clearTimeout(timer);
        }
      })();
      cache.set(key, { stamp, result });
      if (cache.size > 64) cache.delete(cache.keys().next().value!);
      try { return await result; }
      catch { if (cache.get(key)?.result === result) cache.delete(key); return { text: "", readable: false }; }
    } catch { return { text: "", readable: false }; }
  };
  return { read, clear: () => cache.clear() };
}
