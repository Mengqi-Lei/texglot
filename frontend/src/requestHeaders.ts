import { normalizedEndpoint, providerId } from "./providers";

export type HeaderDraft = string | null; // null keeps stored values, never echoed.
export type HeaderValidation = {
  headers?: Record<string, string>;
  error?: string;
};
const reserved = new Set([
  "authorization",
  "host",
  "content-length",
  "content-type",
  "content-encoding",
  "accept-encoding",
  "connection",
  "keep-alive",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "expect",
]);

export function parseHeaderDraft(text: HeaderDraft): HeaderValidation {
  if (text === null) return {};
  if (text.length > 65536) return { error: "请求头 JSON 文本不能超过 64 KiB" };
  let input: unknown;
  try {
    input = text.trim() ? JSON.parse(text) : {};
  } catch {
    return { error: "请输入有效的请求头 JSON 对象" };
  }
  if (!input || typeof input !== "object" || Array.isArray(input))
    return { error: "额外请求头必须是名称和值均为字符串的 JSON 对象" };
  const entries = Object.entries(input);
  if (entries.length > 16) return { error: "额外请求头最多 16 项" };
  const headers: Record<string, string> = Object.create(null);
  let size = 0;
  for (const [name, value] of entries) {
    if (typeof value !== "string")
      return { error: "额外请求头必须是名称和值均为字符串的 JSON 对象" };
    if (
      !name.length ||
      name.length > 128 ||
      /[^!#$%&'*+.^_`|~0-9A-Za-z-]/.test(name)
    )
      return { error: "请求头名称无效，须为 HTTP token 且不超过 128 个字符" };
    const key = name.toLowerCase();
    if (reserved.has(key))
      return {
        error: "不能覆盖 Authorization、Host、Content-Type 或传输控制请求头",
      };
    if (Object.hasOwn(headers, key))
      return { error: "请求头名称不能重复（不区分大小写）" };
    if (value.length > 4096)
      return { error: "单个请求头的值不能超过 4096 个字符" };
    if (/[^\x20-\x7e]/.test(value))
      return { error: "请求头值不能包含换行、控制字符或非 ASCII 字符" };
    size += name.length + value.length + 4;
    if (size > 16384) return { error: "额外请求头总大小不能超过 16 KiB" };
    headers[key] = value.trim();
  }
  return { headers };
}

export function headerDraftForAddress(
  previous: string,
  next: string,
  draft: HeaderDraft,
): HeaderDraft {
  return normalizedEndpoint(previous) === normalizedEndpoint(next) ? draft : "";
}

export function settingsPayload<
  T extends { base_url: string; extra_header_names?: string[] },
>(form: T, draft: HeaderDraft): T & { extra_headers?: Record<string, string> } {
  const result: T & { extra_headers?: Record<string, string> } = { ...form };
  delete result.extra_header_names;
  const parsed = parseHeaderDraft(
    providerId(form.base_url) === "deepl" ? "" : draft,
  );
  if (parsed.error) throw new Error(parsed.error);
  if (parsed.headers !== undefined) result.extra_headers = parsed.headers;
  return result;
}
