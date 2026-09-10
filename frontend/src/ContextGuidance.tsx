import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CircleHelp } from "lucide-react";
import { useI18n } from "./i18n";

function GuidanceHelp({ description }: { description: string }) {
  const { t } = useI18n();
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const pinned = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{
    left: number;
    top: number;
    width: number;
  } | null>(null);
  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current);
  };
  const close = () => {
    clearTimer();
    pinned.current = false;
    setOpen(false);
  };
  const show = () => {
    clearTimer();
    setOpen(true);
  };
  const leave = () => {
    clearTimer();
    timer.current = setTimeout(() => {
      if (!pinned.current && !button.current?.matches(":focus-visible"))
        setOpen(false);
    }, 100);
  };
  useEffect(() => () => clearTimer(), []);
  useLayoutEffect(() => {
    if (!open || !button.current || !bubble.current) return;
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight;
    const width = Math.min(280, viewportWidth - 24);
    bubble.current.style.width = `${width}px`;
    const anchor = button.current.getBoundingClientRect();
    const height = bubble.current.getBoundingClientRect().height;
    const above = anchor.top - height - 10;
    setPosition({
      width,
      left: Math.max(
        12,
        Math.min(
          anchor.left + anchor.width / 2 - width / 2,
          viewportWidth - width - 12,
        ),
      ),
      top: Math.max(
        12,
        Math.min(
          above >= 12 ? above : anchor.bottom + 10,
          viewportHeight - height - 12,
        ),
      ),
    });
  }, [open, description]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (
        !button.current?.contains(event.target as Node) &&
        !bubble.current?.contains(event.target as Node)
      )
        close();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);
  return (
    <>
      <button
        ref={button}
        type="button"
        className="guidance-help"
        aria-label={t("上下文引导说明")}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onPointerEnter={(event) => {
          if (event.pointerType !== "touch") show();
        }}
        onPointerLeave={leave}
        onFocus={(event) => {
          if (event.currentTarget.matches(":focus-visible")) show();
        }}
        onBlur={close}
        onClick={() => {
          clearTimer();
          pinned.current = !pinned.current;
          setOpen(pinned.current);
        }}
      >
        <CircleHelp size={15} />
      </button>
      {open &&
        createPortal(
          <div
            ref={bubble}
            id={id}
            role="tooltip"
            className="guidance-tooltip"
            style={{ ...position, visibility: position ? "visible" : "hidden" }}
            onPointerEnter={clearTimer}
            onPointerLeave={leave}
          >
            {description}
          </div>,
          document.body,
        )}
    </>
  );
}

export default function ContextGuidance({
  checked,
  onChange,
  disabled = false,
  label,
  note,
  compact = false,
}: {
  checked: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
  label?: string;
  note?: string;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const id = useId();
  const description = compact
    ? t(
        "开启后，使用论文原文摘要作为背景，帮助理解研究主题与术语。关闭后，只翻译当前段落，不附加摘要。",
      )
    : note ||
      t(
        checked
          ? "本次翻译结合论文摘要理解主题与术语。"
          : "本次翻译仅处理当前段落，不附加论文摘要。",
      );
  return (
    <div className={`context-guidance${compact ? " compact" : ""}`}>
      <div className={compact ? "guidance-label" : undefined}>
        <strong id={`${id}-label`}>{label || t("上下文引导")}</strong>
        {compact && <GuidanceHelp description={description} />}
        <p
          id={`${id}-note`}
          className={compact ? "visually-hidden" : undefined}
        >
          {description}
        </p>
      </div>
      <button
        type="button"
        className="guidance-switch"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-note`}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <span />
      </button>
    </div>
  );
}
