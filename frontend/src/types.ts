import { getLocale, translate } from "./i18n";
export type Settings = {
  base_url: string;
  model: string;
  api_key?: string;
  has_api_key?: boolean;
  target_language: string;
  context_guidance: boolean;
  concurrency: number;
  temperature: number;
  timeout: number;
  glossary: string;
  compiler: string;
};
export type Job = {
  id: string;
  name: string;
  kind: string;
  arxiv_id: string;
  main: string;
  candidates?: string[];
  language: string;
  context_guidance?: boolean;
  status: string;
  progress: number;
  message: string;
  created_at: number;
  updated_at: number;
  done: number;
  total: number;
  tokens: number;
  cached: number;
  pages: number;
  warnings: string[];
  logs: { time: number; message: string }[];
  artifacts: Record<string, string>;
  error?: string;
  config?: Settings;
};
export type Health = {
  ok: boolean;
  compilers: Record<string, boolean>;
  version: string;
  data_dir: string;
};
export const activeStates = [
  "queued",
  "downloading",
  "preparing",
  "translating",
  "compiling",
];
export const statusNames: Record<string, string> = {
  queued: "等待中",
  downloading: "获取源码",
  preparing: "检查排版",
  translating: "翻译中",
  compiling: "生成 PDF",
  completed: "已完成",
  partial: "需检查",
  failed: "未完成",
  cancelled: "已停止",
  interrupted: "已暂停",
};
export const defaults: Settings = {
  base_url: "https://api.deepseek.com",
  model: "deepseek-v4-flash",
  target_language: "简体中文",
  context_guidance: true,
  concurrency: 3,
  temperature: 0.2,
  timeout: 180,
  glossary: "",
  compiler: "auto",
};
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const locale = getLocale();
  const headers = new Headers(options.headers);
  headers.set("Accept-Language", headers.get("Accept-Language") ?? locale);
  if (!(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const r = await fetch("/api" + path, {
    ...options,
    headers,
  });
  if (!r.ok) {
    let text = "请求失败，请稍后重试";
    try {
      const data = await r.json();
      text =
        typeof data.detail === "string"
          ? data.detail
          : "输入格式不正确，请检查后重试";
    } catch {}
    throw new Error(translate(locale, text));
  }
  return r.json();
}
export const artifactURL = (job: Job, kind: string, download = false) =>
  `/api/jobs/${job.id}/artifacts/${kind}${download ? "?download=true" : ""}`;
