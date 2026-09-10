import logoURL from "./assets/texglot-logo.png";
import { useI18n } from "./i18n";
import {
  lazy,
  Suspense,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  Download,
  FileArchive,
  FileText,
  Globe2,
  Languages,
  Link2,
  LoaderCircle,
  Plus,
  Search,
  Settings2,
  Square,
  UploadCloud,
  X,
  TriangleAlert,
  RotateCcw,
  Terminal,
} from "lucide-react";
import Settings from "./Settings";
import ContextGuidance from "./ContextGuidance";
import {
  api,
  artifactURL,
  defaults,
  activeStates,
  statusNames,
  type Settings as Config,
  type Job,
  type Health,
} from "./types";
const PdfReader = lazy(() => import("./PdfReader"));
const date = (n: number, locale: string) =>
  new Date(n * 1000).toLocaleDateString(locale === "en" ? "en-US" : "zh-CN", {
    month: "short",
    day: "numeric",
  });
const count = (n: number) =>
  n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);

function JobDetail({
  job,
  onClose,
  onRead,
  onRefresh,
  onError,
}: {
  job: Job;
  onClose: () => void;
  onRead: () => void;
  onRefresh: () => void;
  onError: (e: string) => void;
}) {
  const { t, locale } = useI18n();
  const [busy, setBusy] = useState(false),
    [main, setMain] = useState(job.main),
    [logs, setLogs] = useState(false);
  const savedGuidance =
    job.context_guidance ?? job.config?.context_guidance ?? true;
  const [guidance, setGuidance] = useState(savedGuidance);
  useEffect(() => setGuidance(savedGuidance), [job.id, savedGuidance]);
  const active = activeStates.includes(job.status);
  const action = async (name: string) => {
    setBusy(true);
    try {
      await api(`/jobs/${job.id}/${name}`, {
        method: "POST",
        body: JSON.stringify(
          name === "retry" ? { main, context_guidance: guidance } : {},
        ),
      });
      onRefresh();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      className="job-detail"
      id={`job-details-${job.id}`}
      aria-labelledby={`job-title-${job.id}`}
    >
      <header>
        <div>
          <p>
            {job.main || t("正在识别主文件")} · {t(job.language)}
          </p>
        </div>
        <button className="icon-button" onClick={onClose} title={t("收起详情")}>
          <X size={17} />
        </button>
      </header>
      <div className="pipeline">
        {[t("获取源码"), t("检查排版"), t("段落翻译"), t("生成 PDF")].map(
          (s, i) => {
            const n = job.progress;
            const done = n >= [10, 25, 88, 100][i];
            const current = n >= [0, 10, 25, 88][i] && !done;
            return (
              <div className={done ? "done" : current ? "current" : ""} key={s}>
                <span>{done ? <Check size={12} /> : i + 1}</span>
                {s}
              </div>
            );
          },
        )}
      </div>
      <div className="detail-status">
        <span className={"badge " + job.status}>
          {active && <LoaderCircle size={12} className="spin" />}
          {t(statusNames[job.status])}
        </span>
        <span>{job.message}</span>
        {active && <b>{job.progress}%</b>}
      </div>
      {active && (
        <div className="progress-track">
          <i style={{ width: `${job.progress}%` }} />
        </div>
      )}
      <div className="detail-metrics">
        <span>
          <b>
            {job.done} <small>/ {job.total || "—"}</small>
          </b>
          {t("段落已处理")}
        </span>
        <span>
          <b>{count(job.tokens)}</b>
          {t("已使用 tokens")}
        </span>
        <span>
          <b>{job.cached}</b>
          {t("缓存复用")}
        </span>
        <span>
          <b>{job.pages || "—"}</b>
          {t("译文页数")}
        </span>
      </div>
      <ContextGuidance
        checked={guidance}
        onChange={setGuidance}
        disabled={active || busy}
        note={t(
          active
            ? "此任务正在使用的翻译方式。"
            : "下次重新处理或继续任务时生效。",
        )}
      />
      {job.error && <p className="error-box">{job.error}</p>}
      {job.warnings.map((w, i) => (
        <p key={i} className="warning-box">
          <TriangleAlert size={15} />
          {w}
        </p>
      ))}
      {(job.candidates?.length || 0) > 1 && (
        <label className="main-choice">
          {t("主文件")}{" "}
          <select
            value={main}
            onChange={(e) => setMain(e.target.value)}
            disabled={active}
          >
            {job.candidates!.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
          <small>{t("切换后点击重新处理")}</small>
        </label>
      )}
      <div className="detail-actions">
        {job.artifacts.translated && (
          <button className="primary small" onClick={onRead}>
            <BookOpen size={15} />
            {t("对照阅读")}
          </button>
        )}
        {job.artifacts.translated && (
          <a
            className="secondary small"
            href={artifactURL(job, "translated", true)}
          >
            <Download size={15} />
            {t("译文 PDF")}
          </a>
        )}
        {job.artifacts.source && (
          <a
            className="secondary small"
            href={artifactURL(job, "source", true)}
          >
            <Code2 size={15} />
            {t("LaTeX 源码")}
          </a>
        )}
        {active ? (
          <button
            className="text-button danger"
            disabled={busy}
            onClick={() => action("cancel")}
          >
            <Square size={13} />
            {t("停止任务")}
          </button>
        ) : (
          <button
            className="text-button"
            disabled={busy}
            onClick={() => action("retry")}
          >
            <RotateCcw size={14} />
            {job.status === "completed" ? t("重新处理") : t("继续 / 重试")}
          </button>
        )}
        <button
          className="text-button log-toggle"
          onClick={() => setLogs(!logs)}
        >
          <Terminal size={14} />
          {t("处理记录")}
          <ChevronDown size={12} />
        </button>
      </div>
      {logs && (
        <div className="job-logs">
          {job.logs.map((l, i) => (
            <p key={i}>
              <time>
                {new Date(l.time * 1000).toLocaleTimeString(
                  locale === "en" ? "en-US" : "zh-CN",
                  {
                    hour12: false,
                  },
                )}
              </time>
              {l.message}
            </p>
          ))}
          <a href={artifactURL(job, "log", true)}>{t("下载编译日志")}</a>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const { t, locale, setLocale } = useI18n();
  const [settings, setSettings] = useState<Config>(defaults),
    [health, setHealth] = useState<Health | null>(null),
    [jobs, setJobs] = useState<Job[]>([]),
    [showSettings, setShowSettings] = useState(false),
    [tab, setTab] = useState("arxiv"),
    [section, setSection] = useState("workspace"),
    [url, setUrl] = useState(""),
    [file, setFile] = useState<File | null>(null),
    [language, setLanguage] = useState("简体中文"),
    [contextGuidance, setContextGuidance] = useState(true),
    [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all"),
    [busy, setBusy] = useState(false),
    [dragging, setDragging] = useState(false),
    [selected, setSelected] = useState(""),
    [reader, setReader] = useState<Job | null>(null),
    [notice, setNotice] = useState(""),
    [error, setError] = useState(""),
    [connected, setConnected] = useState(true);
  const input = useRef<HTMLInputElement>(null),
    arxivInput = useRef<HTMLInputElement>(null),
    noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null),
    detailAnchor = useRef<{
      row: HTMLElement;
      top: number;
      restoreFocus: boolean;
    } | null>(null);
  const toggleDetail = (id: string, restoreFocus = false) => {
    const row = document.getElementById(`job-row-${id}`);
    if (row) {
      const headerBottom =
        document.querySelector(".app-header")?.getBoundingClientRect().bottom ||
        0;
      detailAnchor.current = {
        row,
        top: restoreFocus
          ? Math.max(row.getBoundingClientRect().top, headerBottom + 12)
          : row.getBoundingClientRect().top,
        restoreFocus,
      };
    }
    setSelected((current) => (current === id ? "" : id));
  };
  useLayoutEffect(() => {
    const anchor = detailAnchor.current;
    detailAnchor.current = null;
    if (!anchor?.row.isConnected) return;
    // Collapsing another detail above the clicked row must not move that row
    // out from under the user. Compensate only this deliberate view change.
    window.scrollBy({
      top: anchor.row.getBoundingClientRect().top - anchor.top,
      behavior: "instant",
    });
    if (anchor.restoreFocus)
      anchor.row
        .querySelector<HTMLButtonElement>(".job-summary")
        ?.focus({ preventScroll: true });
  }, [selected]);
  const toast = (message: string) => {
    setNotice(message);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(""), 4500);
  };
  const currentLocale = useRef(locale);
  currentLocale.current = locale;
  const refresh = async () => {
    const requestLocale = currentLocale.current;
    try {
      const next = await api<Job[]>("/jobs", {
        headers: { "Accept-Language": requestLocale },
      });
      if (requestLocale === currentLocale.current) setJobs(next);
      setConnected(true);
    } catch {
      setConnected(false);
    }
  };
  useEffect(() => {
    void Promise.all([
      api<Config>("/settings").then((s) => {
        setSettings(s);
        setLanguage(s.target_language);
        setContextGuidance(s.context_guidance ?? true);
      }),
      api<Health>("/health").then(setHealth),
      refresh(),
    ]).catch(() => setConnected(false));
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    void refresh();
  }, [locale]);
  const submit = async (example = false) => {
    setError("");
    if (!example && tab === "arxiv" && !url.trim()) {
      setError("先输入一个 arXiv 链接或 ID");
      arxivInput.current?.focus();
      return;
    }
    if (!example && tab === "file" && !file) {
      setError("请先选择 LaTeX 源码文件");
      return;
    }
    setBusy(true);
    try {
      let job: Job;
      if (example)
        job = await api("/jobs/example", {
          method: "POST",
          body: JSON.stringify({ language, context_guidance: contextGuidance }),
        });
      else if (tab === "arxiv")
        job = await api("/jobs/arxiv", {
          method: "POST",
          body: JSON.stringify({
            url,
            language,
            context_guidance: contextGuidance,
          }),
        });
      else {
        const body = new FormData();
        body.append("file", file!);
        body.append("language", language);
        body.append("context_guidance", String(contextGuidance));
        job = await api("/jobs/file", { method: "POST", body });
      }
      setSelected(job.id);
      setSection("workspace");
      setFilter("all");
      setSearch("");
      await refresh();
      toast("任务已开始，可在下方查看进度");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const chooseFile = (f: File | undefined) => {
    if (!f) return;
    if (f.size > 80 * 1024 * 1024) {
      setError("文件超过 80 MB，请精简源码包后重试");
      return;
    }
    if (!/\.(tex|zip|tar|tar\.gz|tgz|gz)$/i.test(f.name)) {
      setError("请选择 .tex 或 LaTeX 源码压缩包");
      return;
    }
    setFile(f);
    setError("");
  };
  const completed = jobs.filter(
      (j) => j.status === "completed" || j.status === "partial",
    ).length,
    running = jobs.filter((j) => activeStates.includes(j.status)).length;
  const shown = jobs.filter(
    (j) =>
      (filter === "all" ||
        (filter === "done"
          ? ["completed", "partial"].includes(j.status)
          : activeStates.includes(j.status))) &&
      j.name.toLowerCase().includes(search.toLowerCase()),
  );
  const compilerReady = health && Object.values(health.compilers).some(Boolean);
  if (reader)
    return (
      <Suspense
        fallback={
          <div className="full-loading">
            <LoaderCircle className="spin" />
            {t("正在打开 PDF…")}
          </div>
        }
      >
        <PdfReader job={reader} onClose={() => setReader(null)} />
      </Suspense>
    );
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-inner">
          <a
            className="brand"
            href="#"
            aria-label={t("TeXGlot首页")}
            onClick={(e) => {
              e.preventDefault();
              setSection("workspace");
            }}
          >
            <img className="brand-mark" src={logoURL} alt="" />
            <strong>TeXGlot</strong>
          </a>
          <nav className="app-nav" aria-label={t("主要导航")}>
            <button
              className={section === "workspace" ? "selected" : ""}
              aria-current={section === "workspace" ? "page" : undefined}
              onClick={() => setSection("workspace")}
            >
              {t("新建翻译")}
            </button>
            <button
              className={section === "library" ? "selected" : ""}
              aria-current={section === "library" ? "page" : undefined}
              onClick={() => setSection("library")}
            >
              {t("文献库")}
            </button>
          </nav>
          <div className="header-actions">
            <div
              className="locale-switch"
              role="group"
              aria-label="界面语言 / Interface language"
            >
              <button
                lang="zh-CN"
                aria-pressed={locale === "zh"}
                onClick={() => setLocale("zh")}
              >
                中
              </button>
              <button
                lang="en"
                aria-pressed={locale === "en"}
                onClick={() => setLocale("en")}
              >
                EN
              </button>
            </div>
            <span className="connection-status">
              <i className={connected ? "" : "offline"} />
              {connected ? t("本地运行") : t("连接中断")}
            </span>
            <button
              className="settings-button"
              aria-label={t("模型设置")}
              onClick={() => setShowSettings(true)}
            >
              <Settings2 size={17} />
              <span>{t("模型设置")}</span>
            </button>
          </div>
        </div>
      </header>
      <main>
        <div className="main-content">
          {!connected && (
            <div className="error-box">
              {t(
                "无法连接本地服务。请运行 texglot --serve，页面会自动重连。",
              )}
            </div>
          )}
          {section === "workspace" ? (
            <>
              <section className="page-intro">
                <h1>{t("翻译论文")}</h1>
                <p>{t("导入 arXiv 链接或 LaTeX 源码，生成翻译后的 PDF。")}</p>
              </section>
              <section className="input-card">
                <div
                  className="input-tabs"
                  role="tablist"
                  aria-label={t("论文来源")}
                >
                  <button
                    role="tab"
                    aria-selected={tab === "arxiv"}
                    className={tab === "arxiv" ? "selected" : ""}
                    onClick={() => {
                      setTab("arxiv");
                      setError("");
                    }}
                  >
                    <Link2 size={17} />
                    {t("arXiv 链接")}
                  </button>
                  <button
                    role="tab"
                    aria-selected={tab === "file"}
                    className={tab === "file" ? "selected" : ""}
                    onClick={() => {
                      setTab("file");
                      setError("");
                    }}
                  >
                    <FileArchive size={17} />
                    {t("LaTeX 源码")}
                  </button>
                </div>
                <div className="input-body">
                  {tab === "arxiv" ? (
                    <>
                      <label className="input-label" htmlFor="arxiv">
                        {t("arXiv 链接或 ID")}
                      </label>
                      <div className="url-field">
                        <Globe2 size={20} />
                        <input
                          id="arxiv"
                          ref={arxivInput}
                          value={url}
                          onChange={(e) => setUrl(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void submit();
                          }}
                          placeholder="https://arxiv.org/abs/1706.03762"
                        />
                      </div>
                      <p className="input-hint">
                        {t("支持论文链接、PDF 链接和 arXiv ID。")}
                      </p>
                    </>
                  ) : (
                    <>
                      <input
                        className="hidden-input"
                        ref={input}
                        type="file"
                        accept=".tex,.zip,.tar,.tar.gz,.tgz,.gz"
                        onChange={(e) => chooseFile(e.target.files?.[0])}
                      />
                      <div
                        role="button"
                        tabIndex={0}
                        aria-label={t("选择或拖放 LaTeX 源码")}
                        className={
                          "upload-zone " +
                          (dragging ? "dragging" : "") +
                          (file ? " has-file" : "")
                        }
                        onClick={() => input.current?.click()}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ")
                            input.current?.click();
                        }}
                        onDragOver={(e) => {
                          e.preventDefault();
                          setDragging(true);
                        }}
                        onDragLeave={() => setDragging(false)}
                        onDrop={(e) => {
                          e.preventDefault();
                          setDragging(false);
                          chooseFile(e.dataTransfer.files[0]);
                        }}
                      >
                        {file ? (
                          <>
                            <FileArchive size={30} />
                            <strong>{file.name}</strong>
                            <span>
                              {(file.size / 1024 / 1024).toFixed(2)}
                              {t("MB · 点击更换文件")}
                            </span>
                          </>
                        ) : (
                          <>
                            <UploadCloud size={30} />
                            <strong>
                              {t("拖放源码到这里，或")}
                              <span>{t("选择文件")}</span>
                            </strong>
                            <span>{t(".tex、.zip、.tar.gz · 最大 80 MB")}</span>
                          </>
                        )}
                      </div>
                      <p className="upload-tip">
                        {t("多文件工程请连同图片、参考文献和模板一起打包。")}
                      </p>
                    </>
                  )}
                  {error && (
                    <p role="alert" className="error-box">
                      {t(error)}
                    </p>
                  )}
                </div>
                <footer className="input-footer">
                  <div className="translation-options">
                    <div className="language-pair">
                      <span>{t("翻译为")}</span>
                      <select
                        aria-label={t("翻译目标语言")}
                        value={language}
                        onChange={(e) => setLanguage(e.target.value)}
                      >
                        {["简体中文", "繁體中文", "English"].map((l) => (
                          <option key={l} value={l}>
                            {t(l)}
                          </option>
                        ))}
                      </select>
                    </div>
                    <ContextGuidance
                      compact
                      checked={contextGuidance}
                      onChange={setContextGuidance}
                      disabled={busy}
                    />
                  </div>
                  <button
                    className="primary translate-button"
                    disabled={busy}
                    onClick={() => void submit()}
                  >
                    {busy ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <Languages size={17} />
                    )}
                    {t("开始翻译")}
                    <ArrowRight size={16} />
                  </button>
                </footer>
              </section>
              <div className="input-meta">
                <button onClick={() => setShowSettings(true)}>
                  <span>{t("模型")}</span>
                  {settings.model}
                  <ChevronDown size={12} />
                </button>
                <span>{t("文件与任务保存在本机")}</span>
              </div>
              {(!compilerReady || !settings.has_api_key) && health && (
                <div className="setup-hint">
                  <Settings2 size={16} />
                  <span>
                    {!compilerReady
                      ? t("还需要安装编译器。macOS：brew install tectonic")
                      : !settings.has_api_key
                        ? t("连接你的模型 API 后，即可开始翻译。")
                        : ""}
                  </span>
                  <button onClick={() => setShowSettings(true)}>
                    {t("检查设置")}
                    <ArrowRight size={13} />
                  </button>
                </div>
              )}
            </>
          ) : (
            <section className="library-hero">
              <h1>{t("文献库")}</h1>
              <p>{t("查看翻译记录，阅读和下载论文。")}</p>
            </section>
          )}
          <section className="library">
            <header className="section-header">
              <div>
                <h2>
                  {section === "workspace" ? t("最近翻译") : t("全部文献")}
                </h2>
                <span>
                  {completed}
                  {t("篇已完成")}
                  {running > 0
                    ? ` · ${t("{count} 个任务处理中", { count: running })}`
                    : ""}
                </span>
              </div>
              {section === "workspace" ? (
                <button
                  className="text-button"
                  onClick={() => setSection("library")}
                >
                  {t("全部文献")}
                  <ArrowRight size={14} />
                </button>
              ) : (
                <button
                  className="secondary small"
                  onClick={() => {
                    setSection("workspace");
                    setTimeout(() => arxivInput.current?.focus(), 50);
                  }}
                >
                  <Plus size={15} />
                  {t("新建翻译")}
                </button>
              )}
            </header>
            {jobs.length > 0 && (
              <div className="library-tools">
                <div className="filter-tabs">
                  {[
                    ["all", t("全部")],
                    ["done", t("已完成")],
                    ["active", t("处理中")],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      className={filter === value ? "selected" : ""}
                      onClick={() => setFilter(value)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="search-box">
                  <Search size={14} />
                  <input
                    aria-label={t("搜索文献")}
                    placeholder={t("搜索文献…")}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
              </div>
            )}
            <div className="jobs-list">
              {(section === "workspace" ? shown.slice(0, 5) : shown).map(
                (job) => (
                  <article
                    className={
                      "job-row " + (selected === job.id ? "selected" : "")
                    }
                    key={job.id}
                    id={`job-row-${job.id}`}
                  >
                    <div className="job-row-heading">
                      <button
                        className="job-summary"
                        aria-expanded={selected === job.id}
                        aria-controls={`job-details-${job.id}`}
                        onClick={() => toggleDetail(job.id)}
                      >
                        <div
                          className={
                            "file-icon " +
                            (job.status === "completed" ? "green" : "")
                          }
                        >
                          <FileText size={21} />
                        </div>
                        <div className="job-name">
                          <h3 id={`job-title-${job.id}`}>{job.name}</h3>
                          <p>
                            {job.kind === "arxiv"
                              ? `arXiv · ${job.arxiv_id}`
                              : t("LaTeX 源码")}
                            <span>·</span>
                            {t(job.language)}
                            <span>·</span>
                            {date(job.created_at, locale)}
                            {job.config?.model && (
                              <small
                                className="job-model"
                                title={t("翻译模型") + ": " + job.config.model}
                              >
                                {job.config.model}
                              </small>
                            )}
                          </p>
                        </div>
                        <ChevronRight
                          className="job-disclosure"
                          size={15}
                          aria-hidden="true"
                        />
                      </button>
                      <div className="job-state">
                        <span className={"badge " + job.status}>
                          {activeStates.includes(job.status) ? (
                            <LoaderCircle className="spin" size={12} />
                          ) : job.status === "completed" ? (
                            <Check size={12} />
                          ) : null}
                          {t(statusNames[job.status])}
                        </span>
                        {activeStates.includes(job.status) ? (
                          <small>{job.progress}%</small>
                        ) : job.pages > 0 ? (
                          <small>{t("{count} 页", { count: job.pages })}</small>
                        ) : null}
                      </div>
                      <div className="job-row-actions">
                        {job.artifacts.translated ? (
                          <>
                            <button
                              title={t("对照阅读")}
                              className="icon-button"
                              onClick={() => setReader(job)}
                            >
                              <BookOpen size={17} />
                            </button>
                            <a
                              title={t("下载译文 PDF")}
                              className="icon-button"
                              href={artifactURL(job, "translated", true)}
                            >
                              <Download size={17} />
                            </a>
                          </>
                        ) : (
                          <button
                            title={t(
                              selected === job.id ? "收起详情" : "查看任务详情",
                            )}
                            className="icon-button"
                            aria-expanded={selected === job.id}
                            aria-controls={`job-details-${job.id}`}
                            onClick={() => toggleDetail(job.id)}
                          >
                            <ChevronRight size={18} />
                          </button>
                        )}
                      </div>
                    </div>
                    {selected === job.id && (
                      <JobDetail
                        job={job}
                        onClose={() => toggleDetail(job.id, true)}
                        onRead={() => setReader(job)}
                        onRefresh={refresh}
                        onError={toast}
                      />
                    )}
                  </article>
                ),
              )}
            </div>
            {shown.length === 0 && (
              <div className="empty-library">
                <div className="empty-icon">
                  <BookOpen size={25} />
                </div>
                <h3>{jobs.length ? t("没有匹配的文献") : t("暂无翻译记录")}</h3>
                <p>
                  {jobs.length
                    ? t("换一个关键词或筛选条件试试。")
                    : t("完成的论文会显示在这里。")}
                </p>
                {!jobs.length && (
                  <button
                    className="text-button"
                    onClick={() => void submit(true)}
                  >
                    {t("翻译 Attention Is All You Need")}
                    <ArrowRight size={14} />
                  </button>
                )}
              </div>
            )}
          </section>
        </div>
      </main>
      {showSettings && (
        <Settings
          value={settings}
          health={health}
          onClose={() => setShowSettings(false)}
          onSave={(s) => {
            setSettings(s);
            setContextGuidance(s.context_guidance ?? true);
            setShowSettings(false);
            toast("模型设置已保存");
          }}
        />
      )}
      {notice && (
        <div className="toast" role="status">
          <Check size={16} />
          {t(notice)}
          <button onClick={() => setNotice("")} aria-label={t("关闭提示")}>
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
