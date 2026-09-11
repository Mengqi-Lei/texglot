import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";
import { useI18n } from "./i18n";
import { prepareUpdate, type UpdateState } from "./updates";
import { keepDialogFocus } from "./dialogFocus";
import "./updates.css";

const errors: Record<string, string> = {
  "rate-limit": "更新服务暂时限流，请稍后再试。",
  "check-failed": "暂时无法检查更新，请检查网络后重试。",
  "download-failed": "更新下载中断，请检查网络后重新下载。",
  checksum: "安装包校验未通过，请重新下载。",
  "install-failed": "未能打开安装包，请稍后重试。",
  "jobs-active": "仍有论文正在处理。请等待完成或停止任务后再安装。",
  "service-unavailable": "暂时无法确认任务状态，请恢复本地连接后再安装。",
};
export default function UpdateCenter() {
  const { t } = useI18n();
  const [state, setState] = useState<UpdateState | null>(null);
  const [open, setOpen] = useState(false),
    [dismissed, setDismissed] = useState("");
  const [error, setError] = useState(""),
    [preparing, setPreparing] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const dismissRef = useRef(() => {});
  const bridge = window.texglotDesktop?.updates;
  const accept = (next: UpdateState) =>
    setState((previous) =>
      previous && previous.revision > next.revision ? previous : next,
    );
  const invoke = async (action: () => Promise<UpdateState>) => {
    setError("");
    try {
      accept(await action());
    } catch {
      setError("暂时无法连接桌面更新服务，请重新打开应用。");
    }
  };
  useEffect(() => {
    if (!bridge) return;
    const offState = bridge.onChange(accept);
    const show = () => {
      setOpen(true);
      void invoke(() => bridge.check());
    };
    const offOpen = bridge.onOpen(show);
    window.addEventListener("texglot:open-updates", show);
    void invoke(() => bridge.status());
    return () => {
      offState();
      offOpen();
      window.removeEventListener("texglot:open-updates", show);
    };
  }, [bridge]);
  useEffect(() => {
    if (!open || !state) return;
    dialog.current?.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const keydown = (event: KeyboardEvent) => {
      // A busy button can temporarily lose focus. Escape must still close only
      // this top-level dialog, never the reader or settings behind it.
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        dismissRef.current();
      } else if (event.key === "Tab") {
        keepDialogFocus(event, dialog.current);
        event.stopImmediatePropagation();
      }
    };
    document.addEventListener("keydown", keydown, true);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      document.body.style.overflow = previousOverflow;
      dialog.current?.close();
    };
  }, [open, !!state]);
  if (!bridge || !state) return null;
  const noticeKey = `${state.version}:${state.status === "ready" ? "ready" : "available"}`;
  const dismissDialog = () => {
    setOpen(false);
    setDismissed(noticeKey);
  };
  dismissRef.current = dismissDialog;
  const busy =
    ["checking", "downloading", "opening"].includes(state.status) || preparing;
  const available = ["available", "downloading", "ready"].includes(
    state.status,
  );
  const message =
    (error ? t(error) : "") ||
    (state.error ? t(errors[state.error] ?? errors["check-failed"]) : "");
  const install = async () => {
    setPreparing(true);
    setError("");
    try {
      await prepareUpdate();
      await invoke(() => bridge.install());
    } catch {
      setError("请先保存或处理尚未保存的批注，再安装更新。");
    } finally {
      setPreparing(false);
    }
  };
  return (
    <>
      {!open && available && noticeKey !== dismissed && (
        <div className="update-notice" role="status">
          <ArrowDownToLine size={19} />
          <div>
            <strong>
              {state.status === "ready"
                ? t("更新已准备好")
                : t("TeXGlot {version} 可用", { version: state.version! })}
            </strong>
            <button onClick={() => setOpen(true)}>
              {t("查看更新")}
              <ArrowUpRight size={12} />
            </button>
          </div>
          <button
            className="icon-button"
            title={t("稍后提醒")}
            onClick={() => setDismissed(noticeKey)}
          >
            <X size={15} />
          </button>
        </div>
      )}
      <dialog
        ref={dialog}
        className="update-dialog"
        aria-labelledby="update-title"
        onCancel={(event) => {
          event.preventDefault();
          dismissDialog();
        }}
        onClick={(event) => {
          if (event.target === event.currentTarget) dismissDialog();
        }}
        onKeyDown={(event) => {
          event.stopPropagation();
          keepDialogFocus(event, dialog.current);
        }}
      >
        <div className="update-dialog-content">
          <button
            className="icon-button update-close"
            title={t("关闭")}
            onClick={dismissDialog}
          >
            <X size={18} />
          </button>
          <div className="update-symbol">
            {state.status === "current" ? (
              <Check size={26} />
            ) : state.status === "checking" ? (
              <LoaderCircle className="spin" size={26} />
            ) : (
              <ArrowDownToLine size={26} />
            )}
          </div>
          <h2 id="update-title">{t("软件更新")}</h2>
          <p className="update-version">
            {t("当前版本")} {state.currentVersion}
          </p>
          <div className="update-summary" aria-live="polite">
            {state.status === "checking" ? (
              <p>{t("正在检查新版本…")}</p>
            ) : state.status === "current" ? (
              <p>{t("你正在使用最新版本。")}</p>
            ) : available || state.status === "opening" ? (
              <>
                <strong>TeXGlot {state.version}</strong>
                <p>
                  {t(
                    state.platform === "darwin"
                      ? "下载后打开安装包，将 TeXGlot 拖入 Applications 并确认替换。论文、设置和批注会保留。"
                      : "下载后打开安装程序完成更新。论文、设置和批注会保留。",
                  )}
                </p>
                {state.url && (
                  <a href={state.url} target="_blank" rel="noreferrer">
                    {t("版本说明")}
                    <ArrowUpRight size={13} />
                  </a>
                )}
                {state.status === "available" && !state.canDownload && (
                  <p>
                    {t(
                      "此版本暂未提供适合本机的可验证安装包，请查看版本说明。",
                    )}
                  </p>
                )}
              </>
            ) : (
              <p>{t("检查 TeXGlot 的最新正式版本。")}</p>
            )}
          </div>
          {state.status === "downloading" && (
            <div className="update-progress">
              <div>
                <span>
                  {state.progress! >= 99
                    ? t("正在校验安装包…")
                    : t("正在下载更新…")}
                </span>
                <span>{state.progress ?? 0}%</span>
              </div>
              <progress
                max={100}
                value={state.progress ?? 0}
                aria-label={t("下载进度")}
              />
              <small>{t("下载期间可以继续使用 TeXGlot。")}</small>
            </div>
          )}
          {message && (
            <p className="update-error" role="alert">
              {message}
            </p>
          )}
          <label className="update-preference">
            <input
              type="checkbox"
              checked={state.autoCheck}
              onChange={(event) =>
                void invoke(() => bridge.setAutoCheck(event.target.checked))
              }
            />
            {t("自动检查更新")}
          </label>
          <footer>
            <button className="secondary" onClick={dismissDialog}>
              {t("稍后")}
            </button>
            {state.status === "downloading" ? (
              <button
                className="secondary"
                onClick={() => void invoke(() => bridge.cancel())}
              >
                {t("取消下载")}
              </button>
            ) : state.status === "ready" && state.error !== "checksum" ? (
              <button
                className="primary"
                disabled={preparing}
                onClick={() => void install()}
              >
                {preparing && <LoaderCircle className="spin" size={15} />}
                {t("退出并打开安装包")}
              </button>
            ) : state.status === "available" ||
              (state.status === "ready" && state.error === "checksum") ? (
              <button
                className="primary"
                disabled={!state.canDownload}
                onClick={() => void invoke(() => bridge.download())}
              >
                <ArrowDownToLine size={15} />
                {t("下载更新")}
              </button>
            ) : (
              <button
                className="primary"
                disabled={busy}
                onClick={() => void invoke(() => bridge.check())}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <RefreshCw size={15} />
                )}
                {t(state.status === "opening" ? "正在打开安装包…" : "检查更新")}
              </button>
            )}
          </footer>
        </div>
      </dialog>
    </>
  );
}
