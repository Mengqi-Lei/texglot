import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  ArrowLeftRight,
  ChevronLeft,
  ChevronRight,
  Columns2,
  Download,
  FileText,
  Highlighter,
  Link2,
  LoaderCircle,
  MessageSquare,
  Minus,
  MousePointer2,
  PanelRight,
  Plus,
  RotateCcw,
  Save,
  Search,
  Trash2,
  Underline,
  Unlink,
  X,
  Check,
} from "lucide-react";
import { useI18n } from "./i18n";
import { api, artifactURL, type Job } from "./types";
import PdfPane, { type PaneHandle } from "./PdfPane";
import { clamp } from "./readerGeometry";
import {
  createPositionMapper,
  otherSide,
  planModeChange,
  planEnableSync,
  parsePageInput,
  type Positions,
} from "./readerNavigation";
import {
  colors,
  colorNames,
  type Annotation,
  type AnnotationColor,
  type AnnotationInput,
  type AnnotationKind,
  type DocumentSide,
  type PagePosition,
  type ReaderData,
  type ReaderMode,
  type ReaderTool,
  type ReadingState,
  type SelectionDraft,
} from "./readerTypes";
import "./reader.css";
import { readDrafts, writeDraft, clearDraft } from "./annotationDrafts";
import { beforeUpdate } from "./updates";
import {
  attachWheelZoom,
  clampZoom,
  MAX_ZOOM,
  MIN_ZOOM,
  zoomFromWheel,
} from "./readerZoom";

export default function PdfReader({
  job,
  onClose,
}: {
  job: Job;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [data, setData] = useState<ReaderData | null>(null),
    [loadError, setLoadError] = useState(""),
    [mode, setMode] = useState<ReaderMode>("split"),
    [zoom, setZoom] = useState(1),
    [sync, setSync] = useState(true),
    [left, setLeft] = useState<DocumentSide>("original"),
    [active, setActive] = useState<DocumentSide>("translated"),
    [page, setPage] = useState(1),
    [pageInput, setPageInput] = useState("1"),
    [tool, setTool] = useState<ReaderTool>("select"),
    [color, setColor] = useState<AnnotationColor>("yellow"),
    [sidebar, setSidebar] = useState(false),
    [selected, setSelected] = useState(""),
    [draft, setDraft] = useState(""),
    [search, setSearch] = useState(""),
    [scope, setScope] = useState("all"),
    [popup, setPopup] = useState<(SelectionDraft & { id: string }) | null>(
      null,
    ),
    [saving, setSaving] = useState(0),
    [error, setError] = useState(""),
    [conflict, setConflict] = useState(false),
    [deleted, setDeleted] = useState<Annotation | null>(null),
    [failedCreate, setFailedCreate] = useState<AnnotationInput | null>(null),
    [positionError, setPositionError] = useState(false);
  const original = useRef<PaneHandle>(null),
    translated = useRef<PaneHandle>(null),
    pdfContent = useRef<HTMLDivElement>(null),
    positions = useRef<ReadingState["positions"]>({}),
    requested = useRef<Positions>({}),
    dataRef = useRef(data),
    saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null),
    queue = useRef<Promise<unknown>>(Promise.resolve()),
    preferences = useRef({ mode, zoom, sync, active, left }),
    ready = useRef(false),
    pageInputDirty = useRef(false),
    popupRef = useRef(popup);
  dataRef.current = data;
  preferences.current = { mode, zoom, sync, active, left };
  popupRef.current = popup;
  const pane = (side: DocumentSide) =>
    side === "original" ? original.current : translated.current;
  const mapper = useMemo(
    () =>
      createPositionMapper(
        data?.alignment,
        {
          original: data?.documents.original?.pages || 1,
          translated: data?.documents.translated?.pages || 1,
        },
        {
          original: data?.documents.original?.version,
          translated: data?.documents.translated?.version,
        },
      ),
    [
      data?.alignment,
      data?.documents.original?.version,
      data?.documents.translated?.version,
    ],
  );
  const remember = (side: DocumentSide, position: PagePosition) => {
    const info = dataRef.current?.documents[side];
    if (info)
      positions.current[side] = { ...position, document_version: info.version };
  };
  const capturePositions = (): Positions => {
    for (const side of ["original", "translated"] as const) {
      const position = pane(side)?.capture();
      if (position) {
        remember(side, position);
        requested.current[side] = { ...position };
      }
    }
    return { ...positions.current };
  };
  const applyPositions = (values: Positions) => {
    for (const side of ["original", "translated"] as const) {
      const position = values[side];
      if (!position) continue;
      remember(side, position);
      requested.current[side] = { ...position };
      pane(side)?.jump(position);
    }
  };
  const changeZoom = (value: number) => {
    const next = clampZoom(value);
    if (next === preferences.current.zoom) return;
    capturePositions();
    preferences.current.zoom = next;
    setZoom(next);
    setPopup(null);
  };
  const wheelZoom = useRef<(delta: number) => void>(() => {});
  wheelZoom.current = (delta) =>
    changeZoom(zoomFromWheel(preferences.current.zoom, delta));
  const loaded = !!data;
  useEffect(() => {
    if (loaded && pdfContent.current)
      return attachWheelZoom(pdfContent.current, (delta) =>
        wheelZoom.current(delta),
      );
  }, [loaded]);
  const changeMode = (next: ReaderMode) => {
    const previous = preferences.current.mode;
    if (previous === next) return;
    const plan = planModeChange(previous, next, capturePositions(), mapper);
    preferences.current = {
      ...preferences.current,
      mode: next,
      active: plan.active,
    };
    setMode(next);
    setActive(plan.active);
    setPopup(null);
    setPage(plan.positions[plan.active]?.page || 1);
    applyPositions(plan.positions);
  };
  const changeSync = () => {
    const enabled = !preferences.current.sync;
    const current = capturePositions();
    preferences.current.sync = enabled;
    setSync(enabled);
    setPopup(null);
    if (enabled) {
      const plan = planEnableSync(current, mapper);
      preferences.current.active = plan.active;
      setActive(plan.active);
      setPage(plan.positions.translated.page);
      applyPositions(plan.positions);
    }
  };
  const swapPanes = () => {
    capturePositions();
    setPopup(null);
    window.getSelection()?.removeAllRanges();
    const next = otherSide(preferences.current.left);
    preferences.current.left = next;
    setLeft(next);
  };
  useLayoutEffect(() => {
    // Reorder the existing document-keyed panes, retaining both reading anchors.
    applyPositions(requested.current);
  }, [left]);
  const focusPosition = (side: DocumentSide, position: PagePosition) => {
    if (
      preferences.current.mode !== "split" &&
      preferences.current.mode !== side
    ) {
      preferences.current.mode = side;
      setMode(side);
    }
    preferences.current.active = side;
    setActive(side);
    setPage(position.page);
    applyPositions({ [side]: position });
    if (preferences.current.sync && preferences.current.mode === "split") {
      // Page jumps land at the page edge, but synchronization follows the
      // content actually visible at the reading line (including moved figures).
      const visiblePosition = pane(side)?.capture() || position;
      remember(side, visiblePosition);
      requested.current[side] = { ...visiblePosition };
      applyPositions({ [otherSide(side)]: mapper(side, visiblePosition) });
    }
  };
  const selectedAnnotation = data?.annotations.find(
    (a) => a.id === selected && !a.deleted,
  );
  const currentDraft = useRef({ selected, draft });
  currentDraft.current = { selected, draft };
  const fetchReader = useCallback(async () => {
    try {
      const state = await api<ReaderData>(`/jobs/${job.id}/reader`);
      setData(state);
      dataRef.current = state;
      setLoadError("");
      for (const cached of readDrafts(job.id)) {
        const annotation = state.annotations.find(
          (a) => a.id === cached.id && !a.deleted,
        );
        if (!annotation) continue;
        if (annotation.comment === cached.comment) {
          clearDraft(job.id, cached.id, cached.comment);
          continue;
        }
        setSelected(cached.id);
        setDraft(cached.comment);
        setSidebar(true);
        if (annotation.revision !== cached.revision) {
          setConflict(true);
          setError(t("草稿已恢复，请检查批注的最新版本后保存。"));
        }
        break;
      }
      const saved = state.reading;
      if (saved) {
        const valid = Object.fromEntries(
          Object.entries(saved.positions).filter(
            ([side, pos]) =>
              pos.document_version ===
              state.documents[side as DocumentSide]?.version,
          ),
        );
        positions.current = valid;
        requested.current = { ...valid };
        if (saved.mode === "split" && saved.sync) {
          const map = createPositionMapper(
            state.alignment,
            {
              original: state.documents.original?.pages || 1,
              translated: state.documents.translated?.pages || 1,
            },
            {
              original: state.documents.original?.version,
              translated: state.documents.translated?.version,
            },
          );
          const source = saved.active;
          const location = valid[source] || { page: 1, fraction: 0 };
          const paired = map(source, location),
            target = otherSide(source);
          requested.current[target] = paired;
          if (state.documents[target])
            positions.current[target] = {
              ...paired,
              document_version: state.documents[target]!.version,
            };
        }
        setZoom(saved.zoom);
        setSync(saved.sync);
        setLeft(saved.left ?? "original");
        setMode(saved.mode);
        setActive(saved.active);
        setPage(valid[saved.active]?.page || 1);
      }
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, [job.id]);
  useEffect(() => {
    void fetchReader();
  }, [fetchReader]);
  useEffect(() => {
    if (!pageInputDirty.current) setPageInput(String(page));
  }, [page]);
  const savePosition = useCallback(
    async (keepalive = false) => {
      if (!ready.current || !Object.keys(positions.current).length) return;
      capturePositions();
      try {
        await api(`/jobs/${job.id}/reader/position`, {
          method: "PUT",
          body: JSON.stringify({
            ...preferences.current,
            positions: positions.current,
          }),
          keepalive,
        });
        setPositionError(false);
        return true;
      } catch {
        setPositionError(true);
        return false;
      }
    },
    [job.id],
  );
  const schedulePosition = () => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void savePosition(), 700);
  };
  useEffect(() => {
    if (data) schedulePosition();
  }, [mode, zoom, sync, active, left]);
  useEffect(() => {
    const flush = () => void savePosition(true);
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      if (saveTimer.current) clearTimeout(saveTimer.current);
      flush();
    };
  }, [savePosition]);
  const replace = (annotation: Annotation) => {
    if (!dataRef.current) return;
    const next = {
      ...dataRef.current,
      annotations: [
        ...dataRef.current.annotations.filter((a) => a.id !== annotation.id),
        annotation,
      ],
    };
    dataRef.current = next;
    setData(next);
  };
  const enqueue = <T,>(operation: () => Promise<T>): Promise<T> => {
    setSaving((n) => n + 1);
    const promise = queue.current.then(operation);
    queue.current = promise.catch(() => {});
    return promise.finally(() => setSaving((n) => n - 1));
  };
  const patch = async (
    id: string,
    changes: Partial<Pick<Annotation, "comment" | "color" | "deleted">>,
  ) =>
    enqueue(async () => {
      const latest = dataRef.current?.annotations.find((a) => a.id === id);
      if (!latest) throw new Error(t("批注不存在"));
      if (
        Object.entries(changes).every(
          ([key, value]) => latest[key as keyof Annotation] === value,
        )
      )
        return latest;
      try {
        const saved = await api<Annotation>(
          `/jobs/${job.id}/annotations/${id}`,
          {
            method: "PATCH",
            body: JSON.stringify({ revision: latest.revision, ...changes }),
          },
        );
        replace(saved);
        clearDraft(job.id, saved.id, saved.comment);
        setError("");
        return saved;
      } catch (e) {
        setError((e as Error).message);
        setConflict(true);
        throw e;
      }
    });
  const saveComment = async () => {
    const { selected: id, draft: comment } = currentDraft.current;
    const annotation = dataRef.current?.annotations.find(
      (a) => a.id === id && !a.deleted,
    );
    if (annotation && comment !== annotation.comment)
      await patch(id, { comment });
  };
  useEffect(() => {
    if (!selectedAnnotation || draft === selectedAnnotation.comment || conflict)
      return;
    const timer = setTimeout(() => {
      void saveComment().catch(() => {});
    }, 850);
    return () => clearTimeout(timer);
  }, [selected, draft, selectedAnnotation?.comment, conflict]);
  const choose = async (annotation: Annotation, jump = false) => {
    try {
      await saveComment();
    } catch {
      return;
    }
    setSelected(annotation.id);
    setDraft(annotation.comment);
    capturePositions();
    setSidebar(true);
    setConflict(false);
    setPopup(null);
    if (
      jump &&
      annotation.document_version ===
        dataRef.current?.documents[annotation.document]?.version
    ) {
      focusPosition(annotation.document, {
        page: annotation.anchors[0].page,
        fraction: annotation.anchors[0].rects[0].y,
        viewport: 0.2,
      });
    }
  };
  const create = async (input: AnnotationInput, open = false) => {
    try {
      const saved = await enqueue(() =>
        api<Annotation>(`/jobs/${job.id}/annotations`, {
          method: "POST",
          body: JSON.stringify(input),
        }),
      );
      replace(saved);
      setPopup(null);
      setFailedCreate(null);
      setError("");
      window.getSelection()?.removeAllRanges();
      if (open || sidebar) await choose(saved);
    } catch (e) {
      setFailedCreate(input);
      setError((e as Error).message);
    }
  };
  const mark = (
    selection: SelectionDraft & { id?: string },
    kind: AnnotationKind,
    shade: AnnotationColor,
    open = false,
  ) => {
    void create(
      {
        id: selection.id || crypto.randomUUID(),
        document: selection.document,
        document_version: selection.document_version,
        anchors: selection.anchors,
        quote: selection.quote,
        comment: "",
        kind,
        color: shade,
      },
      open,
    );
  };
  const onSelection = (selection: SelectionDraft) => {
    const value = { ...selection, id: crypto.randomUUID() };
    if (tool === "highlight" || tool === "underline") mark(value, tool, color);
    else setPopup(value);
  };
  const onNote = (side: DocumentSide, number: number, x: number, y: number) => {
    const version = dataRef.current?.documents[side]?.version;
    if (!version) return;
    mark(
      {
        document: side,
        document_version: version,
        quote: "",
        anchors: [
          {
            page: number,
            rects: [
              {
                x: clamp(x, 0, 0.97),
                y: clamp(y, 0, 0.97),
                width: 0.025,
                height: 0.025,
              },
            ],
          },
        ],
        x: 0,
        y: 0,
      },
      "note",
      color,
      true,
    );
  };
  const onPosition = (
    side: DocumentSide,
    position: PagePosition,
    user: boolean,
  ) => {
    remember(side, position);
    if (user) {
      delete requested.current[side];
      preferences.current.active = side;
      setActive(side);
      setPage(position.page);
      setPopup(null);
      if (preferences.current.sync && preferences.current.mode === "split") {
        const target = otherSide(side),
          paired = mapper(side, position);
        requested.current[target] = paired;
        remember(target, paired);
        pane(target)?.jump(paired);
      }
    } else if (side === preferences.current.active) setPage(position.page);
    schedulePosition();
  };
  const navigate = (number: number) => {
    const side = preferences.current.active,
      total = dataRef.current?.documents[side]?.pages || 1;
    focusPosition(side, {
      page: parsePageInput(String(number), page, total),
      fraction: 0,
    });
  };
  const close = async () => {
    try {
      await saveComment();
      capturePositions();
      await queue.current;
      await savePosition();
      onClose();
    } catch {
      setSidebar(true);
    }
  };
  const prepareUpdateRef = useRef(async () => {});
  prepareUpdateRef.current = async () => {
    await saveComment();
    await queue.current;
    if (conflict || failedCreate || (await savePosition()) === false)
      throw new Error("Unsaved reader changes");
  };
  useEffect(() => beforeUpdate(() => prepareUpdateRef.current()), []);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        (e.target as HTMLElement).closest(
          "input,textarea,[contenteditable=true]",
        )
      )
        return;
      if (e.key === "Escape") {
        if (popupRef.current) {
          setPopup(null);
          window.getSelection()?.removeAllRanges();
        } else void closeRef.current();
      }
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const current =
          positions.current[preferences.current.active]?.page || 1;
        navigate(current + (e.key === "ArrowRight" ? 1 : -1));
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);
  const remove = async () => {
    if (!selectedAnnotation) return;
    try {
      await saveComment();
      const item = await patch(selected, { deleted: true });
      setDeleted(item);
      setSelected("");
      setDraft("");
    } catch {}
  };
  const undo = async () => {
    if (!deleted) return;
    try {
      const item = await patch(deleted.id, { deleted: false });
      setDeleted(null);
      await choose(item, true);
    } catch {}
  };
  const reloadNotes = async () => {
    try {
      const next = await api<ReaderData>(`/jobs/${job.id}/reader`);
      dataRef.current = next;
      setData(next);
      setConflict(false);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const total = data?.documents[active]?.pages || 1;
  const notes = (data?.annotations || [])
    .filter((a) => !a.deleted)
    .sort(
      (a, b) =>
        a.document.localeCompare(b.document) ||
        a.anchors[0].page - b.anchors[0].page ||
        a.anchors[0].rects[0].y - b.anchors[0].rects[0].y ||
        a.created_at - b.created_at,
    );
  const shown = notes.filter(
    (a) =>
      (scope === "all" || a.document === scope) &&
      `${a.quote} ${a.comment}`.toLowerCase().includes(search.toLowerCase()),
  );
  const dirty = !!selectedAnnotation && draft !== selectedAnnotation.comment;
  if (!data)
    return (
      <div className="reader-initial">
        <button className="text-button" onClick={onClose}>
          <ArrowLeft size={16} />
          {t("返回工作台")}
        </button>
        {loadError ? (
          <>
            <p className="error-box">{loadError}</p>
            <button className="secondary" onClick={() => void fetchReader()}>
              {t("重试")}
            </button>
          </>
        ) : (
          <>
            <LoaderCircle className="spin" />
            {t("正在打开 PDF…")}
          </>
        )}
      </div>
    );
  return (
    <div className="reader continuous-reader">
      <header className="reader-header">
        <button
          className="icon-button"
          onClick={() => void close()}
          title={t("返回工作台")}
        >
          <ArrowLeft size={19} />
        </button>
        <div className="reader-title">
          <strong>{job.name}</strong>
          <span>TeXGlot · {t("连续阅读")}</span>
        </div>
        <div className="segmented reader-modes">
          {(["translated", "original", "split"] as const).map((m) => (
            <button
              key={m}
              aria-pressed={mode === m}
              className={mode === m ? "selected" : ""}
              onClick={() => changeMode(m)}
            >
              {m === "split" ? <Columns2 size={15} /> : <FileText size={15} />}
              {
                {
                  translated: t("译文"),
                  original: t("原文"),
                  split: t("对照"),
                }[m]
              }
            </button>
          ))}
        </div>
        <a
          className="primary small reader-download"
          aria-label={t("下载译文")}
          href={artifactURL(job, "translated", true)}
        >
          <Download size={15} />
          <span>{t("下载译文")}</span>
        </a>
      </header>
      <div className="reader-toolbar">
        <div className="reader-tools">
          {mode === "split" && (
            <div
              className="comparison-tools"
              role="group"
              aria-label={t("对照阅读")}
            >
              <button
                className={`reader-tool sync-tool ${sync ? "selected" : ""}`}
                aria-pressed={sync}
                title={t(sync ? "关闭同步滚动" : "开启同步滚动")}
                onClick={changeSync}
              >
                {sync ? <Link2 size={17} /> : <Unlink size={17} />}
                <span>{t("同步滚动")}</span>
              </button>
              <button
                className="reader-tool"
                title={t("左右互换")}
                aria-label={t("左右互换")}
                onClick={swapPanes}
              >
                <ArrowLeftRight size={17} />
              </button>
            </div>
          )}
          <div
            className="annotation-tools"
            role="group"
            aria-label={t("批注工具")}
          >
            {(
              [
                ["select", MousePointer2, "选择文字"],
                ["highlight", Highlighter, "高亮"],
                ["underline", Underline, "下划线"],
                ["note", MessageSquare, "便签"],
              ] as const
            ).map(([value, Icon, label]) => (
              <button
                key={value}
                className={`reader-tool ${tool === value ? "selected" : ""}`}
                aria-pressed={tool === value}
                title={t(label)}
                onClick={() => {
                  setTool(value);
                  setPopup(null);
                  window.getSelection()?.removeAllRanges();
                }}
              >
                <Icon size={17} />
              </button>
            ))}
          </div>
          <div
            className="annotation-colors"
            role="group"
            aria-label={t("标记颜色")}
          >
            {(Object.keys(colors) as AnnotationColor[]).map((c) => (
              <button
                key={c}
                className={`color-dot ${color === c ? "selected" : ""}`}
                style={{ background: colors[c] }}
                title={t(colorNames[c])}
                aria-pressed={color === c}
                onClick={() => setColor(c)}
              />
            ))}
          </div>
        </div>
        <div className="page-control">
          <span className="current-document">
            {t(active === "original" ? "原文" : "译文")}
          </span>
          <button
            className="icon-button"
            title={t("上一页")}
            disabled={page <= 1}
            onClick={() => navigate(page - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <input
            aria-label={t("页码")}
            inputMode="numeric"
            value={pageInput}
            onChange={(e) => {
              pageInputDirty.current = true;
              setPageInput(e.target.value);
            }}
            onFocus={(e) => e.currentTarget.select()}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                e.currentTarget.blur();
              }
              if (e.key === "Escape") {
                pageInputDirty.current = false;
                setPageInput(String(page));
                e.currentTarget.blur();
              }
            }}
            onBlur={() => {
              if (!pageInputDirty.current) return;
              pageInputDirty.current = false;
              const next = parsePageInput(pageInput, page, total);
              navigate(next);
              setPageInput(String(next));
            }}
          />
          <span>/ {total}</span>
          <button
            className="icon-button"
            title={t("下一页")}
            disabled={page >= total}
            onClick={() => navigate(page + 1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
        <div className="reader-view-tools">
          <div className="zoom-control" title={t("Ctrl + 滚轮缩放")}>
            <button
              className="icon-button"
              title={t("缩小")}
              disabled={zoom <= MIN_ZOOM}
              onClick={() => changeZoom(Math.round((zoom - 0.1) * 10) / 10)}
            >
              <Minus size={15} />
            </button>
            <button
              className="text-button zoom-reset"
              title={t("适合宽度")}
              onClick={() => changeZoom(1)}
            >
              {Math.round(zoom * 100)}%
            </button>
            <button
              className="icon-button"
              title={t("放大")}
              disabled={zoom >= MAX_ZOOM}
              onClick={() => changeZoom(Math.round((zoom + 0.1) * 10) / 10)}
            >
              <Plus size={15} />
            </button>
          </div>
          <button
            className={`reader-tool notes-toggle ${sidebar ? "selected" : ""}`}
            aria-pressed={sidebar}
            title={t("批注侧栏")}
            aria-label={`${t("批注")} ${notes.length}`}
            onClick={async () => {
              if (sidebar) {
                try {
                  await saveComment();
                } catch {
                  return;
                }
              }
              capturePositions();
              setSidebar(!sidebar);
            }}
          >
            <PanelRight size={17} />
            <span>{t("批注")}</span>
            <small>{notes.length}</small>
          </button>
        </div>
      </div>
      {(error || positionError) && (
        <div className="reader-error" role="alert">
          <span>{error || t("阅读位置尚未保存，请检查本地连接")}</span>
          {failedCreate && (
            <button
              onClick={() =>
                void create(failedCreate, failedCreate.kind === "note")
              }
            >
              {t("重试保存")}
            </button>
          )}
          {conflict && (
            <button onClick={() => void reloadNotes()}>
              {t("重新加载批注")}
            </button>
          )}
          {positionError && (
            <button onClick={() => void savePosition()}>{t("重试")}</button>
          )}
          <button title={t("关闭提示")} onClick={() => setError("")}>
            <X size={14} />
          </button>
        </div>
      )}
      <div className="reader-body">
        <div
          ref={pdfContent}
          className={`pdf-content ${mode === "split" ? "split" : ""}`}
        >
          {[left, otherSide(left)].map((side) =>
            data.documents[side] ? (
              <PdfPane
                key={side + data.documents[side]!.version}
                ref={side === "original" ? original : translated}
                job={job}
                side={side}
                info={data.documents[side]!}
                zoom={zoom}
                tool={tool}
                annotations={data.annotations}
                selected={selected}
                active={active === side}
                visible={mode === "split" || mode === side}
                initial={requested.current[side] || positions.current[side]}
                onActive={(s) => {
                  preferences.current.active = s;
                  setActive(s);
                  setPage(
                    pane(s)?.capture()?.page || positions.current[s]?.page || 1,
                  );
                }}
                onPosition={onPosition}
                onSelection={onSelection}
                onPick={(a) => void choose(a)}
                onNote={onNote}
                onReady={() => {
                  ready.current = true;
                  const position =
                    requested.current[side] || positions.current[side];
                  if (position) pane(side)?.jump(position);
                }}
              />
            ) : null,
          )}
        </div>
        {sidebar && (
          <aside className="annotations-sidebar" aria-label={t("批注列表")}>
            <header>
              <div>
                <h2>
                  {t("批注")}
                  <span>{notes.length}</span>
                </h2>
                <p>{t("仅保存在 TeXGlot，不写入 PDF")}</p>
              </div>
              <button
                className="icon-button"
                title={t("关闭批注侧栏")}
                onClick={async () => {
                  try {
                    await saveComment();
                    capturePositions();
                    setSidebar(false);
                  } catch {}
                }}
              >
                <X size={17} />
              </button>
            </header>
            <div className="notes-filters">
              <div className="notes-search">
                <Search size={14} />
                <input
                  aria-label={t("搜索批注")}
                  placeholder={t("搜索批注…")}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <div className="note-scope">
                {[
                  ["all", "全部"],
                  ["original", "原文"],
                  ["translated", "译文"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    className={scope === value ? "selected" : ""}
                    onClick={() => setScope(value)}
                  >
                    {t(label)}
                  </button>
                ))}
              </div>
            </div>
            <div className="annotations-list">
              {!shown.length && (
                <div className="annotations-empty">
                  <Highlighter size={25} />
                  <strong>
                    {t(notes.length ? "没有匹配的批注" : "开始记录你的想法")}
                  </strong>
                  <p>
                    {t(
                      "选中文字添加高亮或下划线，也可以使用便签工具点击页面。",
                    )}
                  </p>
                </div>
              )}
              {shown.map((a) => (
                <button
                  key={a.id}
                  className={`annotation-card ${selected === a.id ? "selected" : ""}`}
                  style={
                    {
                      "--annotation-color": colors[a.color],
                    } as React.CSSProperties
                  }
                  onClick={() => void choose(a, true)}
                >
                  <div className="annotation-card-meta">
                    <span style={{ background: colors[a.color] }} />
                    {t(a.document === "original" ? "原文" : "译文")} ·{" "}
                    {t("第 {page} 页", { page: a.anchors[0].page })}
                    {a.document_version !==
                      data.documents[a.document]?.version && (
                      <em>{t("旧版本")}</em>
                    )}
                  </div>
                  {a.quote ? (
                    <blockquote>{a.quote}</blockquote>
                  ) : (
                    <div className="note-card-kind">
                      <MessageSquare size={13} />
                      {t("便签")}
                    </div>
                  )}
                  {a.comment && <p>{a.comment}</p>}
                </button>
              ))}
            </div>
            {selectedAnnotation && (
              <section className="annotation-editor" aria-label={t("编辑批注")}>
                <div className="editor-heading">
                  <span>{t("批注内容")}</span>
                  <div className="editor-colors">
                    {(Object.keys(colors) as AnnotationColor[]).map((c) => (
                      <button
                        key={c}
                        className={`color-dot ${selectedAnnotation.color === c ? "selected" : ""}`}
                        title={t("改为{color}", { color: t(colorNames[c]) })}
                        style={{ background: colors[c] }}
                        onClick={() =>
                          void patch(selected, { color: c }).catch(() => {})
                        }
                      />
                    ))}
                  </div>
                </div>
                {selectedAnnotation.document_version !==
                  data.documents[selectedAnnotation.document]?.version && (
                  <p className="archived-note">
                    {t("此批注属于较早的 PDF 版本，内容已保留。")}
                  </p>
                )}
                <textarea
                  key={selected}
                  autoFocus
                  rows={4}
                  maxLength={8000}
                  aria-label={t("批注内容")}
                  placeholder={t("写下你的想法…")}
                  value={draft}
                  onChange={(e) => {
                    setDraft(e.target.value);
                    writeDraft(job.id, {
                      id: selected,
                      comment: e.target.value,
                      revision: selectedAnnotation.revision,
                      updated: Date.now(),
                    });
                  }}
                />
                <footer>
                  <span role="status">
                    {saving ? (
                      <>
                        <LoaderCircle size={12} className="spin" />
                        {t("保存中…")}
                      </>
                    ) : dirty ? (
                      t("尚未保存")
                    ) : (
                      <>
                        <Check size={12} />
                        {t("已保存")}
                      </>
                    )}
                  </span>
                  <button
                    className="icon-button"
                    title={t("删除批注")}
                    onClick={() => void remove()}
                  >
                    <Trash2 size={15} />
                  </button>
                  <button
                    className="secondary small"
                    disabled={!dirty || !!saving}
                    onClick={() => void saveComment().catch(() => {})}
                  >
                    <Save size={13} />
                    {t("保存")}
                  </button>
                </footer>
              </section>
            )}
            {deleted && (
              <div className="annotation-undo">
                <span>{t("批注已删除")}</span>
                <button onClick={() => void undo()}>
                  <RotateCcw size={13} />
                  {t("撤销")}
                </button>
              </div>
            )}
          </aside>
        )}
      </div>
      {popup && (
        <div
          className="selection-toolbar"
          role="dialog"
          aria-label={t("添加标记")}
          style={{ left: popup.x, top: popup.y }}
          onPointerDown={(e) => e.preventDefault()}
        >
          <div className="selection-colors">
            {(Object.keys(colors) as AnnotationColor[]).map((c) => (
              <button
                key={c}
                className="color-dot"
                title={t("{color}高亮", { color: t(colorNames[c]) })}
                style={{ background: colors[c] }}
                disabled={!!saving}
                onClick={() => mark(popup, "highlight", c)}
              />
            ))}
          </div>
          <button
            title={t("添加下划线")}
            disabled={!!saving}
            onClick={() => mark(popup, "underline", color)}
          >
            <Underline size={17} />
          </button>
          <button
            title={t("高亮并添加批注")}
            disabled={!!saving}
            onClick={() => mark(popup, "highlight", color, true)}
          >
            <MessageSquare size={17} />
          </button>
          <button title={t("关闭标记工具")} onClick={() => setPopup(null)}>
            <X size={14} />
          </button>
        </div>
      )}
      <footer className="reader-footer">
        <span>
          {t(
            tool === "select"
              ? "选择文字即可标记 · ← → 跳页"
              : tool === "note"
                ? "点击页面添加便签"
                : "选中文字后自动添加标记",
          )}
        </span>
        <span>
          {t(
            sync && mode === "split"
              ? data.alignment?.kind === "landmarks"
                ? "按内容定位点同步"
                : "按页码与页内位置同步"
              : "连续滚动阅读 · 阅读位置自动保存",
          )}
        </span>
        <a href={artifactURL(job, "source", true)}>{t("下载 LaTeX 源码")}</a>
      </footer>
    </div>
  );
}
