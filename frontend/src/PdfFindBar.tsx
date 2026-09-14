import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, LoaderCircle, Search, X } from "lucide-react";
import { useI18n } from "./i18n";
import { usePresence } from "./motion";
import type { FindStatus } from "./pdfSearch";
import type { DocumentSide } from "./readerTypes";

export default function PdfFindBar({
  open,
  focus,
  query,
  side,
  sides,
  status,
  onQuery,
  onSide,
  onNext,
  onClose,
}: {
  open: boolean;
  focus: number;
  query: string;
  side: DocumentSide;
  sides: DocumentSide[];
  status: FindStatus;
  onQuery: (query: string) => void;
  onSide: (side: DocumentSide) => void;
  onNext: (previous: boolean) => void;
  onClose: () => void;
}) {
  const { t } = useI18n(),
    present = usePresence(open);
  const input = useRef<HTMLInputElement>(null),
    composing = useRef(false);
  const [composition, setComposition] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      input.current?.focus();
      input.current?.select();
    }
  }, [open, focus]);
  if (!present) return null;
  return (
    <div
      className="pdf-find-bar"
      role="search"
      aria-label={t("搜索 PDF")}
      data-closing={!open || undefined}
      inert={!open}
      aria-hidden={!open || undefined}
    >
      <div className="pdf-find-input">
        <Search size={16} aria-hidden="true" />
        <input
          ref={input}
          type="text"
          aria-label={t("搜索 PDF 内容")}
          placeholder={t("搜索 PDF 内容")}
          value={composition ?? query}
          autoComplete="off"
          spellCheck={false}
          onCompositionStart={(event) => {
            composing.current = true;
            setComposition(event.currentTarget.value);
          }}
          onCompositionEnd={(event) => {
            composing.current = false;
            setComposition(null);
            onQuery(event.currentTarget.value);
          }}
          onChange={(event) => {
            if (composing.current) setComposition(event.target.value);
            else onQuery(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || composing.current) return;
            if (event.key === "Enter") {
              event.preventDefault();
              onNext(event.shiftKey);
            }
            if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              onClose();
            }
          }}
        />
        <span
          className={`pdf-find-count ${query.trim() && !status.pending && !status.total ? "empty" : ""}`}
          role="status"
          aria-live="polite"
        >
          {status.pending ? (
            <LoaderCircle
              size={14}
              className="spin"
              aria-label={t("正在搜索…")}
            />
          ) : query.trim() ? (
            status.total ? (
              `${status.current} / ${status.total}`
            ) : (
              t("未找到")
            )
          ) : (
            ""
          )}
        </span>
        <button
          className="icon-button"
          title={t("上一处匹配（Shift+Enter）")}
          disabled={!status.total}
          onClick={() => onNext(true)}
        >
          <ArrowUp size={16} />
        </button>
        <button
          className="icon-button"
          title={t("下一处匹配（Enter）")}
          disabled={!status.total}
          onClick={() => onNext(false)}
        >
          <ArrowDown size={16} />
        </button>
        <button
          className="icon-button"
          title={t("关闭搜索（Esc）")}
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </div>
      <div className="pdf-find-options">
        <label>
          {t("搜索范围")}
          <select
            value={side}
            aria-label={t("搜索范围")}
            onChange={(event) => onSide(event.target.value as DocumentSide)}
          >
            {sides.map((value) => (
              <option key={value} value={value}>
                {t(value === "original" ? "原文" : "译文")}
              </option>
            ))}
          </select>
        </label>
        <span>{t("Enter 下一处 · Shift+Enter 上一处")}</span>
      </div>
    </div>
  );
}
