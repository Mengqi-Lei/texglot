import { useEffect, useRef } from "react";
import { MessageSquare, Underline, X } from "lucide-react";
import { useI18n } from "./i18n";
import { usePresence } from "./motion";
import {
  colors,
  colorNames,
  type AnnotationColor,
  type AnnotationKind,
  type SelectionDraft,
} from "./readerTypes";

type Draft = SelectionDraft & { id: string };
export default function SelectionToolbar({
  selection,
  saving,
  color,
  onDismiss,
  onMark,
}: {
  selection: Draft | null;
  saving: boolean;
  color: AnnotationColor;
  onDismiss: () => void;
  onMark: (
    draft: Draft,
    kind: AnnotationKind,
    color: AnnotationColor,
    open?: boolean,
  ) => void;
}) {
  const { t } = useI18n();
  const host = useRef<HTMLDivElement>(null),
    last = useRef(selection),
    dismiss = useRef(onDismiss);
  dismiss.current = onDismiss;
  if (selection) last.current = selection;
  const present = usePresence(!!selection);
  useEffect(() => {
    if (!selection) return;
    const outside = (event: Event) => {
      if (event.target instanceof Node && !host.current?.contains(event.target))
        dismiss.current();
    };
    const lost = () => dismiss.current();
    const range = window.getSelection()?.rangeCount
      ? window.getSelection()!.getRangeAt(0).cloneRange()
      : null;
    const changed = () => {
      // Keyboard focus on a toolbar button must not invalidate its action.
      if (host.current?.contains(document.activeElement)) return;
      const current = window.getSelection();
      if (!current?.rangeCount || current.isCollapsed || !range) return lost();
      const next = current.getRangeAt(0);
      if (
        next.startContainer !== range.startContainer ||
        next.startOffset !== range.startOffset ||
        next.endContainer !== range.endContainer ||
        next.endOffset !== range.endOffset
      )
        lost();
    };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", outside);
    document.addEventListener("selectionchange", changed);
    window.addEventListener("blur", lost);
    window.addEventListener("resize", lost);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("selectionchange", changed);
      window.removeEventListener("blur", lost);
      window.removeEventListener("resize", lost);
    };
  }, [selection?.id]);
  const value = selection || last.current;
  if (!present || !value) return null;
  return (
    <div
      ref={host}
      className="selection-toolbar"
      role="dialog"
      aria-label={t("添加标记")}
      aria-hidden={!selection || undefined}
      inert={!selection}
      data-closing={!selection || undefined}
      style={{ left: value.x, top: value.y }}
      onPointerDown={(event) => event.preventDefault()}
    >
      <div className="selection-colors">
        {(Object.keys(colors) as AnnotationColor[]).map((shade) => (
          <button
            key={shade}
            className="color-dot"
            title={t("{color}高亮", { color: t(colorNames[shade]) })}
            style={{ background: colors[shade] }}
            disabled={saving}
            onClick={() => onMark(value, "highlight", shade)}
          />
        ))}
      </div>
      <button
        title={t("添加下划线")}
        disabled={saving}
        onClick={() => onMark(value, "underline", color)}
      >
        <Underline size={17} />
      </button>
      <button
        title={t("高亮并添加批注")}
        disabled={saving}
        onClick={() => onMark(value, "highlight", color, true)}
      >
        <MessageSquare size={17} />
      </button>
      <button title={t("关闭标记工具")} onClick={onDismiss}>
        <X size={14} />
      </button>
    </div>
  );
}
