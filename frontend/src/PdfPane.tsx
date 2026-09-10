import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import * as pdfjs from "pdfjs-dist";
import workerURL from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { ExternalLink, LoaderCircle, MessageSquare } from "lucide-react";
import { useI18n } from "./i18n";
import { artifactURL, type Job } from "./types";
import { captureSelection, clamp } from "./readerGeometry";
import {
  colors,
  type Annotation,
  type DocumentSide,
  type DocumentInfo,
  type PagePosition,
  type ReaderTool,
  type SelectionDraft,
} from "./readerTypes";
import { captureViewport, scrollToPosition } from "./readerNavigation";
pdfjs.GlobalWorkerOptions.workerSrc = workerURL;

function PageCanvas({
  doc,
  page,
  width,
  height,
}: {
  doc: PDFDocumentProxy;
  page: number;
  width: number;
  height: number;
}) {
  const { t } = useI18n(),
    canvas = useRef<HTMLCanvasElement>(null),
    text = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(false);
  useEffect(() => {
    let alive = true,
      render: pdfjs.RenderTask | undefined,
      layer: pdfjs.TextLayer | undefined;
    const element = canvas.current!,
      textElement = text.current!;
    setLoading(true);
    setError(false);
    (async () => {
      try {
        const p = await doc.getPage(page);
        if (!alive) return;
        const scale = width / p.getViewport({ scale: 1 }).width,
          viewport = p.getViewport({ scale });
        // Limit backing-store memory on Retina displays and large zoom levels.
        const ratio = Math.min(
          devicePixelRatio || 1,
          2,
          Math.sqrt(5_000_000 / (width * height)),
        );
        element.width = Math.ceil(width * ratio);
        element.height = Math.ceil(height * ratio);
        render = p.render({
          canvas: element,
          viewport,
          transform: [ratio, 0, 0, ratio, 0, 0],
        });
        await render.promise;
        if (!alive) return;
        textElement.style.setProperty("--total-scale-factor", String(scale));
        layer = new pdfjs.TextLayer({
          textContentSource: await p.getTextContent(),
          container: textElement,
          viewport,
        });
        if (!alive) return;
        await layer.render();
        if (alive) setLoading(false);
      } catch (e) {
        if (
          alive &&
          !(e instanceof Error && e.name === "RenderingCancelledException")
        ) {
          setError(true);
          setLoading(false);
        }
      }
    })();
    return () => {
      alive = false;
      render?.cancel();
      layer?.cancel();
      textElement.replaceChildren();
      element.width = 0;
      element.height = 0;
    };
  }, [doc, page, width, height]);
  return (
    <>
      <canvas ref={canvas} style={{ width, height }} aria-hidden="true" />
      <div ref={text} className="textLayer" />
      {loading && (
        <div className="pdf-loading">
          <LoaderCircle size={17} className="spin" />
          {t("正在排版页面…")}
        </div>
      )}
      {error && (
        <p className="page-render-error">
          {t("页面渲染失败，请下载 PDF 查看")}
        </p>
      )}
    </>
  );
}

function ContinuousPage({
  doc,
  page,
  width,
  ratio,
  host,
  annotations,
  selected,
  tool,
  onPick,
  onNote,
}: {
  doc: PDFDocumentProxy;
  page: number;
  width: number;
  ratio: number;
  host: React.RefObject<HTMLDivElement | null>;
  annotations: Annotation[];
  selected: string;
  tool: ReaderTool;
  onPick: (annotation: Annotation) => void;
  onNote: (page: number, x: number, y: number) => void;
}) {
  const { t } = useI18n(),
    paper = useRef<HTMLDivElement>(null),
    [near, setNear] = useState(false);
  const height = width * ratio;
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => setNear(entry.isIntersecting),
      { root: host.current, rootMargin: "700px 0px" },
    );
    if (paper.current) observer.observe(paper.current);
    return () => observer.disconnect();
  }, [host]);
  return (
    <article className="continuous-page" style={{ width }}>
      <div
        ref={paper}
        className="continuous-paper"
        data-page={page}
        style={{ width, height }}
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("button")) return;
          const bounds = e.currentTarget.getBoundingClientRect(),
            x = clamp((e.clientX - bounds.left) / bounds.width),
            y = clamp((e.clientY - bounds.top) / bounds.height);
          if (tool === "note") {
            onNote(page, x, y);
            return;
          }
          if (!window.getSelection()?.isCollapsed) return;
          const hit = [...annotations]
            .reverse()
            .find((a) =>
              a.anchors.some(
                (anchor) =>
                  anchor.page === page &&
                  anchor.rects.some(
                    (r) =>
                      x >= r.x &&
                      x <= r.x + r.width &&
                      y >= r.y &&
                      y <= r.y + r.height,
                  ),
              ),
            );
          if (hit) onPick(hit);
        }}
      >
        {near ? (
          <PageCanvas doc={doc} page={page} width={width} height={height} />
        ) : (
          <div className="page-placeholder">{t("第 {page} 页", { page })}</div>
        )}
        <div className="annotation-layer" aria-label={t("页面批注")}>
          {annotations.flatMap((a) =>
            a.anchors
              .filter((anchor) => anchor.page === page)
              .flatMap((anchor) =>
                anchor.rects.map((r, index) =>
                  a.kind === "note" ? (
                    <button
                      key={`${a.id}-${index}`}
                      className={`note-pin ${selected === a.id ? "selected" : ""}`}
                      style={{
                        left: `${r.x * 100}%`,
                        top: `${r.y * 100}%`,
                        background: colors[a.color],
                      }}
                      title={a.comment || t("便签")}
                      onClick={() => onPick(a)}
                    >
                      <MessageSquare size={15} />
                    </button>
                  ) : (
                    <span
                      key={`${a.id}-${index}`}
                      data-annotation-id={a.id}
                      className={`annotation-mark ${a.kind} ${selected === a.id ? "selected" : ""}`}
                      style={
                        {
                          left: `${r.x * 100}%`,
                          top: `${r.y * 100}%`,
                          width: `${r.width * 100}%`,
                          height: `${r.height * 100}%`,
                          "--annotation-color": colors[a.color],
                        } as React.CSSProperties
                      }
                    />
                  ),
                ),
              ),
          )}
        </div>
      </div>
      <div className="continuous-page-number">{page}</div>
    </article>
  );
}

export type PaneHandle = {
  jump: (position: PagePosition, user?: boolean) => void;
  capture: () => PagePosition | null;
  isReady: () => boolean;
};
type Props = {
  job: Job;
  side: DocumentSide;
  info: DocumentInfo;
  zoom: number;
  tool: ReaderTool;
  annotations: Annotation[];
  selected: string;
  active: boolean;
  visible: boolean;
  initial?: PagePosition;
  onActive: (side: DocumentSide) => void;
  onPosition: (
    side: DocumentSide,
    position: PagePosition,
    user: boolean,
  ) => void;
  onSelection: (value: SelectionDraft) => void;
  onPick: (a: Annotation) => void;
  onNote: (side: DocumentSide, page: number, x: number, y: number) => void;
  onReady: () => void;
};
const PdfPane = forwardRef<PaneHandle, Props>(function PdfPane(
  {
    job,
    side,
    info,
    zoom,
    tool,
    annotations,
    selected,
    active,
    visible,
    initial,
    onActive,
    onPosition,
    onSelection,
    onPick,
    onNote,
    onReady,
  },
  ref,
) {
  const { t } = useI18n(),
    host = useRef<HTMLDivElement>(null),
    docRef = useRef<PDFDocumentProxy | null>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null),
    [ratios, setRatios] = useState<number[]>([]),
    [width, setWidth] = useState(0),
    [viewportHeight, setViewportHeight] = useState(0),
    [error, setError] = useState(false);
  const current = useRef<PagePosition>(initial || { page: 1, fraction: 0 }),
    ignoreTop = useRef<number | null>(null),
    frame = useRef(0),
    generation = useRef(0),
    callbacks = useRef({ onPosition, onReady });
  callbacks.current = { onPosition, onReady };
  const label = t(side === "original" ? "原文" : "译文");
  const url = artifactURL(job, side) + `?version=${info.version}`;
  useEffect(() => {
    let alive = true;
    const loader = pdfjs.getDocument({
      url,
      cMapUrl: "/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/pdfjs/standard_fonts/",
      wasmUrl: "/pdfjs/wasm/",
    });
    (async () => {
      try {
        const pdf = await loader.promise;
        if (!alive) return;
        docRef.current = pdf;
        const sizes: number[] = [];
        // Read page geometry once; canvases and text layers remain virtualized.
        for (let start = 1; start <= pdf.numPages; start += 8) {
          const batch = await Promise.all(
            Array.from(
              { length: Math.min(8, pdf.numPages - start + 1) },
              (_, i) =>
                pdf.getPage(start + i).then((p) => {
                  const v = p.getViewport({ scale: 1 });
                  return v.height / v.width;
                }),
            ),
          );
          if (!alive) return;
          sizes.push(...batch);
        }
        setRatios(sizes);
        setDoc(pdf);
      } catch {
        if (alive) setError(true);
      }
    })();
    return () => {
      alive = false;
      cancelAnimationFrame(frame.current);
      void loader.destroy();
      docRef.current = null;
    };
  }, [url]);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
        setWidth(entry.contentRect.width);
        setViewportHeight(entry.contentRect.height);
      }
    });
    if (host.current) observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const isReady = () => !!doc && width > 0 && visible;
  const pageBoxes = () =>
    Array.from(
      host.current?.querySelectorAll<HTMLElement>(".continuous-paper") || [],
    ).map((paper) => ({
      page: Number(paper.dataset.page),
      top: paper.offsetTop,
      height: paper.offsetHeight,
    }));
  const readPosition = (): PagePosition => {
    const element = host.current;
    if (!element || !isReady()) return current.current;
    return (
      captureViewport(pageBoxes(), element.scrollTop, element.clientHeight) ||
      current.current
    );
  };
  const capture = () => {
    cancelAnimationFrame(frame.current);
    generation.current++;
    if (!isReady()) return null;
    current.current = readPosition();
    return { ...current.current };
  };
  const notify = (position: PagePosition, user: boolean) =>
    callbacks.current.onPosition(side, position, user);
  const jump = (position: PagePosition, user = false) => {
    cancelAnimationFrame(frame.current);
    generation.current++;
    current.current = { ...position };
    const element = host.current;
    if (!element || !isReady()) return;
    const page = pageBoxes().find(
      (p) => p.page === clamp(position.page, 1, info.pages),
    );
    if (!page) return;
    element.scrollTop = scrollToPosition(page, position, element.clientHeight);
    ignoreTop.current = element.scrollTop;
    // Preserve the requested content anchor through subsequent layout changes.
    notify(readPosition(), user);
  };
  useImperativeHandle(ref, () => ({ jump, capture, isReady }));
  const pageWidth = Math.max(120, Math.min(width - 48, 1000)) * zoom;
  useLayoutEffect(() => {
    cancelAnimationFrame(frame.current);
    generation.current++;
    if (isReady()) jump(current.current);
  }, [pageWidth, viewportHeight, doc, visible]);
  useEffect(() => {
    if (isReady()) callbacks.current.onReady();
  }, [doc, pageWidth, viewportHeight, visible]);
  const pageAnnotations = annotations.filter(
    (a) =>
      !a.deleted && a.document === side && a.document_version === info.version,
  );
  return (
    <section
      className={`pdf-pane continuous-pane ${active ? "active-pane" : ""}`}
      data-document={side}
      hidden={!visible}
    >
      <div className="pane-label">
        <button
          onClick={() => {
            onActive(side);
            host.current?.focus();
          }}
        >
          {label}
          <span>{t("{count} 页", { count: info.pages })}</span>
        </button>
        <a
          href={artifactURL(job, side)}
          target="_blank"
          rel="noreferrer"
          title={t("在新标签页打开 PDF")}
        >
          <ExternalLink size={14} />
        </a>
      </div>
      <div
        ref={host}
        className="continuous-scroll"
        data-tool={tool}
        tabIndex={0}
        aria-label={t("{label}连续阅读", { label })}
        onPointerDown={() => onActive(side)}
        onPointerUp={() => {
          if (tool === "note") return;
          const selection = captureSelection(host.current!, side, info.version);
          if (selection) onSelection(selection);
        }}
        onScroll={() => {
          const element = host.current!;
          if (!isReady()) return;
          if (
            ignoreTop.current !== null &&
            Math.abs(element.scrollTop - ignoreTop.current) < 1
          )
            return;
          ignoreTop.current = null;
          // Read now, before a mode/zoom/resize can change the page geometry.
          const position = readPosition();
          current.current = position;
          cancelAnimationFrame(frame.current);
          const epoch = generation.current;
          frame.current = requestAnimationFrame(() => {
            if (epoch === generation.current) notify(position, true);
          });
        }}
      >
        {error ? (
          <div className="reader-load-error">
            <p>{t("PDF 加载失败，可下载后用系统阅读器打开")}</p>
          </div>
        ) : !doc || !width ? (
          <div className="reader-load-error">
            <LoaderCircle className="spin" />
            {t("正在打开 PDF…")}
          </div>
        ) : (
          <div className="pages-stack">
            {ratios.map((ratio, index) => (
              <ContinuousPage
                key={index + 1}
                doc={doc}
                page={index + 1}
                width={pageWidth}
                ratio={ratio}
                host={host}
                annotations={pageAnnotations.filter((a) =>
                  a.anchors.some((anchor) => anchor.page === index + 1),
                )}
                selected={selected}
                tool={tool}
                onPick={onPick}
                onNote={(page, x, y) => onNote(side, page, x, y)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
});
export default PdfPane;
