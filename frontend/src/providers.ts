export type ProviderId = "qwen" | "deepseek" | "deepl" | "custom";
export type Provider = {
  id: ProviderId;
  name: string;
  base_url: string;
  model: string;
  placeholder: string;
  docs: string;
  has_api_key: boolean;
  extra_header_names?: string[];
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
  try {
    const parsed = new URL(url.trim());
    if (
      parsed.protocol === "https:" &&
      !parsed.port &&
      !parsed.username &&
      !parsed.password &&
      !parsed.search &&
      !parsed.hash &&
      ["api.openai.com", "api.anthropic.com"].includes(parsed.hostname) &&
      ["", "/v1", "/chat/completions", "/v1/chat/completions"].includes(
        parsed.pathname.replace(/\/+$/, ""),
      )
    )
      return `${parsed.origin}/v1`;
  } catch {
    /* Preserve incomplete input. */
  }
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

export function providerErrorMessage(
  text: string,
): { key: string; values: Record<string, string> } | undefined {
  const rejected = text.match(
    /^模型拒绝请求（HTTP (\d{3})），请检查模型设置(?:：([\s\S]*))?$/,
  );
  if (rejected)
    return {
      key: "模型拒绝请求（HTTP {status}），请检查模型设置{detail}",
      values: {
        status: rejected[1],
        detail: rejected[2] ? `: ${rejected[2]}` : "",
      },
    };
  const endpoint = text.match(
    /^请使用官方 Chat Completions 兼容地址：(https:\/\/\S+)$/,
  );
  if (endpoint)
    return {
      key: "请使用官方 Chat Completions 兼容地址：{url}",
      values: { url: endpoint[1] },
    };
}
