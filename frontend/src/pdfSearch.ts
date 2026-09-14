// Initialize PDF.js before its viewer module reads the shared display API.
import "pdfjs-dist";
import type { PDFDocumentProxy, TextLayer } from "pdfjs-dist";
import {
  EventBus,
  FindState,
  PDFFindController,
  PDFLinkService,
} from "pdfjs-dist/web/pdf_viewer.mjs";
import { mergeRects, normalizedRect } from "./readerGeometry";
import { textSlices } from "./searchRanges";

export type FindRequest = {
  query: string;
  sequence: number;
  previous: boolean;
};
export type FindStatus = { current: number; total: number; pending: boolean };
export const emptyFindStatus: FindStatus = {
  current: 0,
  total: 0,
  pending: false,
};

/** Keep PDF.js's Unicode/line-break search; adapt only our virtual page layout. */
export class PdfSearch {
  private bus = new EventBus();
  private controller: PDFFindController;
  private active = false;
  private query = "";
  private status = emptyFindStatus;
  private pages = new Map<number, () => void>();

  constructor(
    doc: PDFDocumentProxy,
    callbacks: {
      page: () => number;
      jump: (page: number) => void;
      status: (status: FindStatus) => void;
    },
  ) {
    const linkService = new PDFLinkService({ eventBus: this.bus });
    linkService.setDocument(doc);
    linkService.setViewer({
      get currentPageNumber() {
        return callbacks.page();
      },
      set currentPageNumber(value: number) {
        callbacks.jump(value);
      },
    });
    this.controller = new PDFFindController({
      linkService,
      eventBus: this.bus,
      delay: 150,
    });
    this.controller.setDocument(doc);
    const update = (event: {
      state?: number;
      matchesCount: { current: number; total: number };
    }) => {
      if (!this.active) return;
      this.status = this.query.trim()
        ? {
            ...event.matchesCount,
            pending:
              event.state === undefined
                ? this.status.pending
                : event.state === FindState.PENDING,
          }
        : emptyFindStatus;
      callbacks.status(this.status);
    };
    this.bus.on("updatefindcontrolstate", update);
    this.bus.on("updatefindmatchescount", update);
    this.bus.on(
      "updatetextlayermatches",
      ({ pageIndex }: { pageIndex: number }) => {
        if (pageIndex === -1) this.pages.forEach((paint) => paint());
        else this.pages.get(pageIndex)?.();
      },
    );
  }

  find(request: FindRequest) {
    const again = this.active && this.query === request.query;
    this.active = true;
    this.query = request.query;
    this.bus.dispatch("find", {
      source: this,
      type: again ? "again" : "",
      query: request.query,
      caseSensitive: false,
      entireWord: false,
      highlightAll: true,
      findPrevious: again && request.previous,
      matchDiacritics: false,
    });
  }

  close() {
    this.active = false;
    this.bus.dispatch("findbarclose", { source: this });
    this.pages.forEach((paint) => paint());
  }

  destroy() {
    this.close();
    // PDF.js supports null to cancel extraction/reset; its .d.ts omits null.
    // @ts-expect-error Upstream setDocument's reset parameter is nullable.
    this.controller.setDocument(null);
    this.pages.clear();
  }

  /** Separate paint layer: searching never rewrites selectable PDF text. */
  bindPage(page: number, surface: HTMLDivElement, layer: TextLayer) {
    const overlay = document.createElement("div");
    overlay.className = "pdf-search-highlights";
    overlay.setAttribute("aria-hidden", "true");
    surface.append(overlay);
    const paint = () => {
      overlay.replaceChildren();
      if (
        !this.active ||
        !this.controller.highlightMatches ||
        !this.query.trim()
      )
        return;
      const bounds = surface.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      const groups = textSlices(
        layer.textContentItemsStr.map((text) => text.length),
        this.controller.pageMatches?.[page - 1] || [],
        this.controller.pageMatchesLength?.[page - 1] || [],
      );
      groups.forEach((slices, matchIndex) => {
        const current =
          this.controller.selected?.pageIdx === page - 1 &&
          this.controller.selected.matchIdx === matchIndex;
        const rects = slices.flatMap((slice) => {
          const node = layer.textDivs[slice.item]?.firstChild;
          if (!node || node.nodeType !== Node.TEXT_NODE) return [];
          const range = document.createRange();
          range.setStart(node, slice.start);
          range.setEnd(node, slice.end);
          return Array.from(range.getClientRects()).flatMap((rect) => {
            const value = normalizedRect(rect, bounds);
            return value ? [value] : [];
          });
        });
        let first: HTMLSpanElement | null = null;
        for (const rect of mergeRects(rects)) {
          const mark = document.createElement("span");
          mark.className = `pdf-search-hit${current ? " current" : ""}`;
          Object.assign(mark.style, {
            left: `${rect.x * 100}%`,
            top: `${rect.y * 100}%`,
            width: `${rect.width * 100}%`,
            height: `${rect.height * 100}%`,
          });
          overlay.append(mark);
          first ||= mark;
        }
        if (current && first)
          this.controller.scrollMatchIntoView({
            element: first,
            pageIndex: page - 1,
            matchIndex,
          });
      });
    };
    this.pages.set(page - 1, paint);
    paint();
    return () => {
      if (this.pages.get(page - 1) === paint) this.pages.delete(page - 1);
      overlay.remove();
    };
  }
}
