import { useI18n } from "./i18n";
import { useEffect, useRef, useState } from "react";
import {
  X,
  Check,
  LoaderCircle,
  PlugZap,
  ShieldCheck,
  ChevronDown,
  ArrowUpRight,
} from "lucide-react";
import { api, type Settings as Config, type Health } from "./types";
import ContextGuidance from "./ContextGuidance";
import {
  normalizedEndpoint,
  providerId,
  type Provider,
  type ProviderId,
} from "./providers";

export default function Settings({
  value,
  health,
  onClose,
  onSave,
}: {
  value: Config;
  health: Health | null;
  onClose: () => void;
  onSave: (s: Config) => void;
}) {
  const { t, locale } = useI18n();
  const dialog = useRef<HTMLElement>(null);
  const previousFocus = useRef(document.activeElement as HTMLElement | null);
  const [form, setForm] = useState<Config>({ ...value, api_key: "" }),
    [busy, setBusy] = useState(""),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<ProviderId>(
    providerId(value.base_url),
  );
  const drafts = useRef<Partial<Record<ProviderId, Config>>>({});
  const provider = providers.find((p) => p.id === selectedProvider);
  const savedKey =
    (value.has_api_key &&
      normalizedEndpoint(form.base_url) ===
        normalizedEndpoint(value.base_url)) ||
    providers.some(
      (p) =>
        p.has_api_key &&
        normalizedEndpoint(p.base_url) === normalizedEndpoint(form.base_url),
    );
  const ready = !!form.base_url.trim() && !!form.model.trim();
  const chooseProvider = (next: Provider) => {
    if (next.id === selectedProvider) return;
    drafts.current[selectedProvider] = form;
    setForm(
      drafts.current[next.id] ?? {
        ...form,
        base_url: next.base_url,
        model: next.model,
        api_key: "",
      },
    );
    setSelectedProvider(next.id);
    setMessage("");
    setError("");
  };
  useEffect(() => {
    let mounted = true;
    api<Provider[]>("/providers")
      .then((items) => {
        if (mounted) setProviders(items);
      })
      .catch((e) => {
        if (mounted) setError(e.message);
      });
    return () => {
      mounted = false;
    };
  }, []);
  const set = (key: keyof Config, v: string | number | boolean) => {
    setForm((f) => ({
      ...f,
      [key]: v,
      ...(key === "base_url" ? { api_key: "" } : {}),
    }));
    setMessage("");
    setError("");
  };
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && dialog.current) {
        const controls = Array.from(
          dialog.current.querySelectorAll<HTMLElement>(
            "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, a[href]",
          ),
        ).filter((element) => element.getClientRects().length > 0);
        const first = controls[0],
          last = controls[controls.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", fn);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", fn);
      document.body.style.overflow = "";
      previousFocus.current?.focus({ preventScroll: true });
    };
  }, []);
  const test = async () => {
    setBusy("test");
    setError("");
    setMessage("");
    try {
      const r = await api<{ message: string }>("/settings/test", {
        method: "POST",
        body: JSON.stringify(form),
      });
      setMessage(t("连接成功 · ") + r.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const save = async () => {
    setBusy("save");
    setError("");
    setMessage("");
    try {
      const s = await api<Config>("/settings", {
        method: "PUT",
        body: JSON.stringify(form),
      });
      onSave(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        ref={dialog}
        className="settings-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
      >
        <header>
          <div>
            <h2 id="settings-title">{t("模型与翻译设置")}</h2>
            <p>{t("配置模型服务、API 密钥和翻译偏好。")}</p>
          </div>
          <button
            autoFocus
            className="icon-button"
            title={t("关闭设置")}
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        <div className="settings-scroll">
          <fieldset className="connection-settings" disabled={!!busy}>
            <legend className="settings-label">{t("模型服务")}</legend>
            <div
              className="provider-options"
              role="group"
              aria-label={t("模型服务")}
            >
              {providers.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  aria-pressed={selectedProvider === p.id}
                  className={selectedProvider === p.id ? "selected" : ""}
                  onClick={() => chooseProvider(p)}
                >
                  <span className={`provider-icon ${p.id}`}>
                    {p.id === "qwen" ? "Q" : p.id === "deepseek" ? "D" : "↔"}
                  </span>
                  <span className="provider-name">
                    <strong>{p.id === "qwen" ? "Qwen" : t(p.name)}</strong>
                    <small>
                      {t(
                        p.id === "qwen"
                          ? "阿里云百炼"
                          : p.id === "deepseek"
                            ? "深度求索"
                            : "兼容接口 / 本地",
                      )}
                    </small>
                  </span>
                  <Check
                    size={14}
                    className="provider-check"
                    aria-hidden="true"
                  />
                </button>
              ))}
            </div>
            {!providers.length && !error && (
              <p className="settings-loading" role="status">
                {t("正在读取服务配置…")}
              </p>
            )}
            <div className="field-row model-fields">
              <label className="field">
                {t("模型名称")}
                <input
                  value={form.model}
                  onChange={(e) => set("model", e.target.value)}
                  list="provider-models"
                  placeholder={
                    selectedProvider === "qwen"
                      ? "qwen3.7-plus"
                      : selectedProvider === "deepseek"
                        ? "deepseek-v4-flash"
                        : t("输入模型名称")
                  }
                  spellCheck={false}
                />
                <datalist id="provider-models">
                  {selectedProvider === "qwen" && (
                    <option value="qwen3.7-plus">Qwen3.7 Plus</option>
                  )}
                  {selectedProvider === "deepseek" && (
                    <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
                  )}
                </datalist>
              </label>
              <label className="field narrow">
                {t("并发段落")}
                <select
                  value={form.concurrency}
                  onChange={(e) => set("concurrency", +e.target.value)}
                >
                  {[1, 2, 3, 4, 6, 8].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {selectedProvider === "qwen" && (
              <p className="provider-guidance">
                {t("默认关闭深度思考，减少翻译等待与额外输出。")}
              </p>
            )}
            <label className="field">
              {t("服务地址")}
              <input
                type="url"
                value={form.base_url}
                onChange={(e) => set("base_url", e.target.value)}
                placeholder={
                  provider?.placeholder ?? "https://your-api.example/v1"
                }
                autoComplete="off"
                spellCheck={false}
              />
              <small>
                {t(
                  selectedProvider === "qwen"
                    ? "从百炼 API Key 页面复制 OpenAI 兼容地址，须与密钥的业务空间和地域一致。"
                    : "填写接口根地址，可包含 /v1，不需要 /chat/completions。",
                )}
              </small>
            </label>
            <label className="field">
              <span className="key-label">
                <span>API Key</span>
                <span className={`key-status ${savedKey ? "configured" : ""}`}>
                  {savedKey ? (
                    <>
                      <Check size={12} />
                      {t("已保存在本机")}
                    </>
                  ) : (
                    t(
                      selectedProvider === "custom"
                        ? "本地模型可留空"
                        : "仅保存到本机",
                    )
                  )}
                </span>
              </span>
              <input
                type="password"
                autoComplete="off"
                value={form.api_key}
                onChange={(e) => set("api_key", e.target.value)}
                placeholder={
                  savedKey ? t("留空保留，填写可替换") : t("输入你的 API key")
                }
              />
            </label>
          </fieldset>
          <ContextGuidance
            checked={form.context_guidance ?? true}
            onChange={(enabled) => set("context_guidance", enabled)}
            disabled={!!busy}
            label={t("默认上下文引导")}
            note={t("作为新任务的默认设置，不会更改已有任务。")}
          />
          <label className="field">
            {t("术语表")}
            <span className="inline-note">{t("可选")}</span>
            <textarea
              rows={4}
              value={form.glossary}
              onChange={(e) => set("glossary", e.target.value)}
              placeholder={t(
                "attention = 注意力\nembedding = 嵌入\n保留 Transformer 原文",
              )}
            />
            <small>{t("每行一条术语偏好，用于保持整篇论文的译法一致。")}</small>
          </label>
          <details className="advanced">
            <summary>
              {t("高级设置")}
              <ChevronDown size={15} />
            </summary>
            <div className="field-row">
              <label className="field">
                {t("编译器")}
                <select
                  value={form.compiler}
                  onChange={(e) => set("compiler", e.target.value)}
                >
                  <option value="auto">{t("自动选择")}</option>
                  {["tectonic", "xelatex", "lualatex"].map((x) => (
                    <option key={x} value={x}>
                      {x}
                      {health?.compilers[x] ? t(" · 已安装") : t(" · 未安装")}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                {t("API 超时（秒）")}
                <input
                  type="number"
                  min={15}
                  max={600}
                  value={form.timeout}
                  onChange={(e) => set("timeout", +e.target.value)}
                />
              </label>
              <label className="field">
                {t("温度")}
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.1}
                  value={form.temperature}
                  onChange={(e) => set("temperature", +e.target.value)}
                />
              </label>
            </div>
          </details>
          <div className="privacy-note">
            <ShieldCheck size={18} />
            <p>
              {t(
                "密钥只保存至本机服务，不会写入前端或导出文件。翻译段落会发送至你配置的模型服务。",
              )}
            </p>
          </div>
          {error && (
            <p role="alert" className="error-box">
              {t(error)}
            </p>
          )}
          {message && (
            <p role="status" className="success-box">
              <Check size={16} />
              {message}
            </p>
          )}
        </div>
        <footer>
          <button
            className="secondary"
            disabled={!!busy || !ready}
            onClick={test}
          >
            {busy === "test" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <PlugZap size={16} />
            )}
            {t("测试连接")}
          </button>
          {provider?.docs && (
            <a
              href={
                selectedProvider === "deepseek" && locale === "zh"
                  ? "https://api-docs.deepseek.com/zh-cn/"
                  : provider.docs
              }
              target="_blank"
              rel="noreferrer"
            >
              {t("API 文档")}
              <ArrowUpRight size={12} />
            </a>
          )}
          <button
            className="primary"
            disabled={!!busy || !ready}
            onClick={save}
          >
            {busy === "save" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Check size={16} />
            )}
            {t("保存设置")}
          </button>
        </footer>
      </section>
    </div>
  );
}
