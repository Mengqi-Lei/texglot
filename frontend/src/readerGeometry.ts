import type { Anchor, Rect, DocumentSide, SelectionDraft } from "./readerTypes";
export const clamp = (value: number, min = 0, max = 1) =>
  Math.min(max, Math.max(min, value));
export function normalizedRect(
  rect: Pick<DOMRect, "left" | "top" | "right" | "bottom">,
  page: Pick<DOMRect, "left" | "top" | "width" | "height">,
): Rect | null {
  const x = clamp((rect.left - page.left) / page.width),
    y = clamp((rect.top - page.top) / page.height);
  const right = clamp((rect.right - page.left) / page.width),
    bottom = clamp((rect.bottom - page.top) / page.height);
  return right > x && bottom > y
    ? { x, y, width: right - x, height: bottom - y }
    : null;
}
export function mergeRects(rects: Rect[]): Rect[] {
  // Browser ranges can contain overlapping glyph/ligature rectangles.
  const result: Rect[] = [];
  for (const r of [...rects].sort((a, b) => a.y - b.y || a.x - b.x)) {
    const previous = result.find(
      (p) =>
        Math.abs(p.y - r.y) < 0.002 &&
        Math.abs(p.height - r.height) < 0.004 &&
        r.x <= p.x + p.width + 0.002 &&
        r.x + r.width >= p.x,
    );
    if (previous) {
      const right = Math.max(previous.x + previous.width, r.x + r.width);
      previous.x = Math.min(previous.x, r.x);
      previous.width = right - previous.x;
    } else result.push({ ...r });
  }
  return result;
}
export function captureSelection(
  host: HTMLElement,
  side: DocumentSide,
  version: string,
): SelectionDraft | null {
  const selection = window.getSelection();
  if (
    !selection ||
    selection.isCollapsed ||
    !selection.rangeCount ||
    !selection.anchorNode ||
    !selection.focusNode ||
    !host.contains(selection.anchorNode) ||
    !host.contains(selection.focusNode)
  )
    return null;
  const range = selection.getRangeAt(0),
    anchors: Anchor[] = [];
  const text: string[] = [];
  for (const paper of host.querySelectorAll<HTMLElement>(".continuous-paper")) {
    const layer = paper.querySelector(".textLayer");
    if (!layer || !range.intersectsNode(layer)) continue;
    const bounds = paper.getBoundingClientRect(),
      rects: Rect[] = [];
    const walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!range.intersectsNode(node)) continue;
      const part = document.createRange();
      part.selectNodeContents(node);
      if (node === range.startContainer) part.setStart(node, range.startOffset);
      if (node === range.endContainer) part.setEnd(node, range.endOffset);
      if (part.collapsed) continue;
      text.push(part.toString());
      for (const rect of part.getClientRects()) {
        if (rect.width < 0.5 || rect.height < 0.5) continue;
        const normalized = normalizedRect(rect, bounds);
        if (normalized) rects.push(normalized);
      }
    }
    if (rects.length)
      anchors.push({
        page: Number(paper.dataset.page),
        rects: mergeRects(rects),
      });
  }
  if (!anchors.length || !text.join("").trim()) return null;
  const bounds = range.getBoundingClientRect();
  return {
    document: side,
    document_version: version,
    anchors,
    quote: text.join(" ").trim().slice(0, 12000),
    x: clamp(bounds.left + bounds.width / 2, 130, innerWidth - 130),
    y: clamp(bounds.top - 46, 10, innerHeight - 60),
  };
}
