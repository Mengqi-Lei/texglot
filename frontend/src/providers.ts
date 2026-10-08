export type ProviderId = "qwen" | "deepseek" | "deepl" | "custom";
export type Provider = {
  id: ProviderId;
  name: string;
  base_url: string;
  model: string;
  placeholder: string;
  docs: string;
  has_api_key: boolean;
  saved: boolean;
};

export function providerId(url: string): ProviderId {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (["api.deepl.com", "api-free.deepl.com"].includes(host)) return "deepl";
    if (host === "api.deepseek.com") return "deepseek";
    if (
      [
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
      ].includes(host) ||
      /^[a-z0-9-]+\.(cn-beijing|ap-southeast-1|ap-northeast-1|eu-central-1|cn-hongkong)\.maas\.aliyuncs\.com$/.test(
        host,
      )
    )
      return "qwen";
  } catch {
    /* An unfinished address stays editable. */
  }
  return "custom";
}

export function normalizedEndpoint(url: string) {
  if (providerId(url.trim()) === "deepl") {
    try {
      const parsed = new URL(url.trim());
      if (
        ["", "/", "/v2", "/v2/", "/v2/translate", "/v2/translate/"].includes(
          parsed.pathname,
        )
      )
        return parsed.origin;
    } catch {
      /* Preserve incomplete input. */
    }
  }
  return url
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/chat\/completions$/, "");
}
