import { TeXGlotIntegrationError, errorFromPayload } from "./errors.js";
import type { BridgeFetchOptions, BridgeHealth, JobOptions, SourceSelection, TaskSnapshot } from "./types.js";

const DEFAULT_BASE = "http://127.0.0.1:8765";
const DESKTOP_FALLBACK_BASE = "http://127.0.0.1:8766";
const ACTIVE = new Set(["queued", "downloading", "preparing", "checking_layout", "translating", "compiling"]);

function normalizeBase(value: string): string {
  return value.replace(/\/+$/, "");
}

type HeaderBag = Headers | Record<string, string>;

function createHeaders(input?: HeadersInit): HeaderBag {
  const HeadersConstructor = (globalThis as unknown as { Headers?: typeof Headers }).Headers;
  if (typeof HeadersConstructor === "function") return new HeadersConstructor(input);

  const result: Record<string, string> = {};
  if (Array.isArray(input)) {
    for (const [name, value] of input) result[name] = String(value);
  } else if (input && typeof input === "object") {
    const source = input as Headers & Record<string, string>;
    if (typeof source.forEach === "function") source.forEach((value, name) => { result[name] = value; });
    else for (const [name, value] of Object.entries(source)) result[name] = String(value);
  }
  return result;
}

function setHeader(headers: HeaderBag, name: string, value: string): void {
  if ("set" in headers && typeof headers.set === "function") headers.set(name, value);
  else (headers as Record<string, string>)[name] = value;
}

function createAbortController(): AbortController | undefined {
  const AbortControllerConstructor = (globalThis as unknown as { AbortController?: typeof AbortController }).AbortController;
  return typeof AbortControllerConstructor === "function" ? new AbortControllerConstructor() : undefined;
}

export class TeXGlotBridge {
  private readonly configuredBaseUrl: string;
  private readonly explicitBaseUrl: boolean;
  private verifiedBaseUrl?: string;
  private healthProbe?: Promise<BridgeHealth>;
  readonly fetcher: typeof globalThis.fetch;
  readonly timeoutMs: number;

  constructor(options: BridgeFetchOptions = {}) {
    this.configuredBaseUrl = normalizeBase(options.baseUrl ?? DEFAULT_BASE);
    this.explicitBaseUrl = options.baseUrl !== undefined;
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 8000;
  }

  get baseUrl(): string {
    return this.verifiedBaseUrl ?? this.configuredBaseUrl;
  }

  private async request(path: string, init: RequestInit = {}, candidateBaseUrl?: string, timeoutMs = this.timeoutMs): Promise<Response> {
    const controller = createAbortController();
    let timeout: ReturnType<typeof setTimeout> | undefined;
    let timedOut = false;
    try {
      const headers = createHeaders(init.headers);
      setHeader(headers, "Accept", "application/json");
      const requestInit: RequestInit = { redirect: "error", ...init, headers };
      if (!init.signal && controller) requestInit.signal = controller.signal;
      const baseUrl = candidateBaseUrl ?? await this.resolveBaseUrl();
      const request = this.fetcher(`${baseUrl}${path}`, requestInit);
      const deadline = new Promise<never>((_, reject) => {
        timeout = setTimeout(() => {
          timedOut = true;
          controller?.abort();
          reject(new TeXGlotIntegrationError("SERVICE_TIMEOUT", "连接 TeXGlot 服务超时。"));
        }, timeoutMs);
      });
      const response = await Promise.race([request, deadline]);
      if (!response.ok) {
        let payload: unknown = null;
        try { payload = await response.clone().json(); } catch { /* text is deliberately not retained */ }
        throw errorFromPayload(response.status, payload);
      }
      return response;
    } catch (error) {
      if (error instanceof TeXGlotIntegrationError) throw error;
      if (timedOut || (error as Error)?.name === "AbortError") throw new TeXGlotIntegrationError("SERVICE_TIMEOUT", "连接 TeXGlot 服务超时。");
      throw new TeXGlotIntegrationError("SERVICE_UNAVAILABLE", "无法连接 TeXGlot 本地服务。请先启动 TeXGlot。", undefined, error);
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  }

  private async json<T>(path: string, init?: RequestInit, candidateBaseUrl?: string): Promise<T> {
    const response = await this.request(path, init, candidateBaseUrl);
    return await response.json() as T;
  }

  private async healthAt(baseUrl: string): Promise<BridgeHealth> {
    try {
      const value = await this.json<Record<string, unknown>>("/api/integrations/zotero/health", undefined, baseUrl);
      return this.normalizeHealth(value);
    } catch (error) {
      if (!(error instanceof TeXGlotIntegrationError) || ![404, 405].includes(error.status ?? 0)) throw error;
      const legacy = await this.json<Record<string, unknown>>("/api/health", undefined, baseUrl);
      return this.normalizeHealth(legacy);
    }
  }

  private async resolveBaseUrl(): Promise<string> {
    if (!this.verifiedBaseUrl) await this.health();
    return this.verifiedBaseUrl!;
  }

  private async discoverHealth(exclude?: string): Promise<BridgeHealth> {
    const candidates = this.explicitBaseUrl
      ? [this.configuredBaseUrl]
      : [DEFAULT_BASE, DESKTOP_FALLBACK_BASE].filter((base) => base !== exclude);
    let lastError: unknown;
    for (const candidate of candidates) {
      try {
        const result = await this.healthAt(candidate);
        this.verifiedBaseUrl = candidate;
        return result;
      } catch (error) {
        lastError = error;
      }
    }
    if (this.explicitBaseUrl) throw lastError;
    throw new TeXGlotIntegrationError(
      "SERVICE_UNAVAILABLE",
      "未找到 TeXGlot 本地服务。请启动 TeXGlot 后重试。",
      undefined,
      lastError,
    );
  }

  async health(): Promise<BridgeHealth> {
    if (!this.healthProbe) {
      this.healthProbe = (async () => {
        const previous = this.verifiedBaseUrl;
        if (previous) {
          try {
            return await this.healthAt(previous);
          } catch (error) {
            if (this.explicitBaseUrl) throw error;
            this.verifiedBaseUrl = undefined;
            return this.discoverHealth(previous);
          }
        }
        return this.discoverHealth();
      })();
    }
    const probe = this.healthProbe;
    try {
      return await probe;
    } finally {
      if (this.healthProbe === probe) this.healthProbe = undefined;
    }
  }

  private async readWithPortRecovery<T>(operation: () => Promise<T>): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      const failedBase = this.verifiedBaseUrl;
      if (this.explicitBaseUrl || !failedBase) throw error;
      await this.health();
      if (this.verifiedBaseUrl === failedBase) throw error;
      return operation();
    }
  }

  private normalizeHealth(value: Record<string, unknown>): BridgeHealth {
    if (value.name !== "TeXGlot" || value.ok !== true) throw new TeXGlotIntegrationError("NOT_TEXGLOT_SERVICE", "当前端口不是 TeXGlot 本地服务。");
    const raw = (value.capabilities && typeof value.capabilities === "object" ? value.capabilities : {}) as Record<string, unknown>;
    return {
      ok: true, name: "TeXGlot", version: typeof (value.version ?? value.core_version) === "string" ? String(value.version ?? value.core_version) : undefined,
      integrationApi: typeof value.integration_api === "string" ? value.integration_api : undefined,
      dataDir: typeof value.data_dir === "string" ? value.data_dir : undefined,
      capabilities: {
        arxivLatex: raw.arxiv_latex !== false, latexUpload: raw.latex_upload !== false,
        pdfReflow: raw.pdf_reflow === true, translatedSource: raw.translated_source !== false,
        readerDeepLink: raw.reader_deep_link === true,
        libraryReuse: raw.library_reuse === true,
        arxivResolution: raw.arxiv_resolution === true,
        originalPdf: raw.original_pdf === true,
      },
    };
  }

  async createJob(selection: SourceSelection, options: JobOptions = {}): Promise<TaskSnapshot> {
    if (!(await this.health()).capabilities.libraryReuse) {
      throw new TeXGlotIntegrationError("CORE_UPGRADE_REQUIRED", "当前运行的 TeXGlot 尚不支持复用文献库。请更新并重新打开 TeXGlot 后再试；本次没有创建新翻译任务。");
    }
    const language = options.language ?? "简体中文";
    const contextGuidance = options.contextGuidance ?? true;
    const source = selection.source.type === "latex"
      ? { type: "latex", filename: selection.source.filename ?? "source.zip", content_base64: selection.source.contentBase64, main: selection.source.main ?? "" }
      : selection.source;
    if (source.type === "latex" && !source.content_base64) {
      throw new TeXGlotIntegrationError("SOURCE_NOT_SUPPORTED", "LaTeX 附件读取能力尚未连接到 Zotero 运行时。请直接选择 arXiv 或重试。");
    }
    const metadata = {
      client: { name: "zotero", version: "1.0.0", item_key: options.itemKey, library_id: options.libraryId },
      idempotency_key: options.idempotencyKey,
      // The core defaults to library reuse. Only an explicit user action opts out.
      ...(options.reuseExisting === false ? { reuse_existing: false } : {}),
    };
    try {
      return await this.json<TaskSnapshot>("/api/integrations/zotero/jobs", {
        method: "POST", body: JSON.stringify({ source, target_language: language, context_guidance: contextGuidance, import: { translated_pdf: true, translated_source: options.importTranslatedSource === true, open: options.open ?? "comparison" }, ...metadata }),
        headers: { "Content-Type": "application/json" },
      });
    } catch (error) {
      if (!(error instanceof TeXGlotIntegrationError) || ![404, 405].includes(error.status ?? 0)) throw error;
      // Legacy submission always starts a new translation. Falling back would
      // silently defeat reuse and spend model tokens on an existing result.
      throw new TeXGlotIntegrationError("CORE_UPGRADE_REQUIRED", "TeXGlot 的翻译接口与插件不匹配，请更新并重新打开 TeXGlot 后再试。未改用旧接口新建翻译。");
    }
  }

  async resolveArxiv(id: string): Promise<{ id: string; title?: string }> {
    const health = await this.health();
    if (!health.capabilities.arxivResolution) {
      throw new TeXGlotIntegrationError("CORE_UPGRADE_REQUIRED", "需要更新 TeXGlot 才能自动获取这篇论文的原文版本。也可以选择已下载的 arXiv 原文 PDF。");
    }
    const response = await this.request("/api/integrations/zotero/sources/resolve", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
    }, undefined, Math.max(20000, this.timeoutMs));
    return response.json();
  }

  async getJob(id: string): Promise<TaskSnapshot> {
    return this.readWithPortRecovery(async () => {
      try { return await this.json<TaskSnapshot>(`/api/integrations/zotero/jobs/${encodeURIComponent(id)}`); }
      catch (error) {
        if (!(error instanceof TeXGlotIntegrationError) || ![404, 405].includes(error.status ?? 0)) throw error;
        return await this.json<TaskSnapshot>(`/api/jobs/${encodeURIComponent(id)}`);
      }
    });
  }

  async pollJob(id: string, options: { intervalMs?: number; maxAttempts?: number; signal?: AbortSignal; onUpdate?: (task: TaskSnapshot) => void } = {}): Promise<TaskSnapshot> {
    const intervalMs = options.intervalMs ?? 1000;
    const maxAttempts = options.maxAttempts ?? 3600;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      if (options.signal?.aborted) throw new TeXGlotIntegrationError("CANCELLED", "已取消等待 TeXGlot 任务。");
      const task = await this.getJob(id);
      options.onUpdate?.(task);
      if (!ACTIVE.has(task.status)) return task;
      await new Promise<void>((resolve, reject) => {
        let settled = false;
        const finish = (callback: () => void) => {
          if (settled) return;
          settled = true;
          options.signal?.removeEventListener("abort", onAbort);
          callback();
        };
        const onAbort = () => finish(() => reject(new TeXGlotIntegrationError("CANCELLED", "已取消等待 TeXGlot 任务。")));
        const timer = setTimeout(() => finish(resolve), intervalMs);
        options.signal?.addEventListener("abort", onAbort, { once: true });
      });
    }
    throw new TeXGlotIntegrationError("POLL_TIMEOUT", "TeXGlot 任务等待超时，可稍后在文献库中继续查询。");
  }

  async artifact(id: string, kind: "translated" | "source" | "original"): Promise<Uint8Array> {
    return this.readWithPortRecovery(async () => {
      let response: Response;
      try {
        response = await this.request(`/api/integrations/zotero/jobs/${encodeURIComponent(id)}/artifacts/${kind}?download=true`);
      } catch (error) {
        if (!(error instanceof TeXGlotIntegrationError) || ![404, 405].includes(error.status ?? 0)) throw error;
        response = await this.request(`/api/jobs/${encodeURIComponent(id)}/artifacts/${kind}?download=true`);
      }
      return new Uint8Array(await response.arrayBuffer());
    });
  }

  async cancel(id: string): Promise<TaskSnapshot> {
    try {
      return await this.json<TaskSnapshot>(`/api/integrations/zotero/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
    } catch (error) {
      if (!(error instanceof TeXGlotIntegrationError) || ![404, 405].includes(error.status ?? 0)) throw error;
      return await this.json<TaskSnapshot>(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
    }
  }

  async retry(id: string): Promise<TaskSnapshot> {
    try {
      return await this.json<TaskSnapshot>(`/api/integrations/zotero/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" });
    } catch (error) {
      if (!(error instanceof TeXGlotIntegrationError) || ![404, 405].includes(error.status ?? 0)) throw error;
      return await this.json<TaskSnapshot>(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body: JSON.stringify({}), headers: { "Content-Type": "application/json" } });
    }
  }

  readerUrl(id: string, mode: "comparison" | "translated" = "comparison"): string {
    return `${this.baseUrl}/?reader=${encodeURIComponent(id)}&mode=${encodeURIComponent(mode)}`;
  }
}
