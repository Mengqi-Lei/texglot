import type {
  Alignment,
  DocumentSide,
  PagePosition,
  ReaderMode,
} from "./readerTypes";

export const otherSide = (side: DocumentSide): DocumentSide =>
  side === "original" ? "translated" : "original";
export type Positions = Partial<Record<DocumentSide, PagePosition>>;
export type PositionMapper = (
  side: DocumentSide,
  position: PagePosition,
) => PagePosition;
const clamp = (n: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, n));

export function createPositionMapper(
  alignment: Alignment | null | undefined,
  counts: Record<DocumentSide, number>,
  versions?: Partial<Record<DocumentSide, string>>,
): PositionMapper {
  if (
    versions &&
    alignment &&
    (alignment.documents.original !== versions.original ||
      alignment.documents.translated !== versions.translated)
  )
    alignment = null;
  const sides: DocumentSide[] = ["original", "translated"];
  const heights = Object.fromEntries(
    sides.map((side) => [
      side,
      Array.from(
        { length: counts[side] },
        (_, i) => alignment?.heights[side]?.[i] || 1,
      ),
    ]),
  ) as Record<DocumentSide, number[]>;
  const starts = Object.fromEntries(
    sides.map((side) => {
      const offsets = [0];
      for (const height of heights[side])
        offsets.push(offsets.at(-1)! + height);
      return [side, offsets];
    }),
  ) as Record<DocumentSide, number[]>;
  const coordinate = (side: DocumentSide, pos: PagePosition) => {
    const i = clamp(pos.page - 1, 0, counts[side] - 1);
    return starts[side][i] + clamp(pos.fraction) * heights[side][i];
  };
  const locate = (
    side: DocumentSide,
    value: number,
    source: PagePosition,
  ): PagePosition => {
    const edges = starts[side];
    let i = 0;
    while (i < counts[side] - 1 && value >= edges[i + 1]) i++;
    return {
      page: i + 1,
      fraction: clamp((value - edges[i]) / heights[side][i]),
      ...(source.viewport === undefined ? {} : { viewport: source.viewport }),
    };
  };
  const pairs = [
    { original: 0, translated: 0 },
    ...(alignment?.pairs || [])
      .map((pair) => ({
        original: coordinate("original", pair.original),
        translated: coordinate("translated", pair.translated),
      }))
      .filter(
        (pair) =>
          pair.original > 0 &&
          pair.translated > 0 &&
          pair.original < starts.original.at(-1)! &&
          pair.translated < starts.translated.at(-1)!,
      ),
    {
      original: starts.original.at(-1)!,
      translated: starts.translated.at(-1)!,
    },
  ];
  // Defensive monotonicity check: old/corrupt metadata must never scroll backwards.
  const ordered = pairs.every(
    (pair, i) =>
      !i ||
      (pair.original > pairs[i - 1].original &&
        pair.translated > pairs[i - 1].translated),
  );
  return (side, position) => {
    const target = otherSide(side);
    // Unchanged figures can float across section boundaries. Within their
    // verified artwork region, follow the figure instead of the prose order.
    const regions = (alignment?.regions || []).filter((pair) => {
      const source = pair[side];
      return (
        source.page === position.page &&
        position.fraction >= source.start &&
        position.fraction <= source.end &&
        source.end > source.start &&
        pair[target].end > pair[target].start
      );
    });
    if (regions.length === 1) {
      const source = regions[0][side],
        destination = regions[0][target];
      const ratio =
        (position.fraction - source.start) / (source.end - source.start);
      return {
        ...position,
        page: destination.page,
        fraction: clamp(
          destination.start + ratio * (destination.end - destination.start),
        ),
      };
    }
    if (!alignment?.pairs.length || !ordered)
      return {
        ...position,
        page: clamp(position.page, 1, counts[target]),
        fraction: clamp(position.fraction),
      };
    const value = coordinate(side, position);
    let low = 0,
      high = pairs.length - 1;
    while (high - low > 1) {
      const mid = (low + high) >> 1;
      if (pairs[mid][side] <= value) low = mid;
      else high = mid;
    }
    const before = pairs[low],
      after = pairs[high];
    const ratio = clamp((value - before[side]) / (after[side] - before[side]));
    return locate(
      target,
      before[target] + ratio * (after[target] - before[target]),
      position,
    );
  };
}

export function planModeChange(
  before: ReaderMode,
  after: ReaderMode,
  positions: Positions,
  map: PositionMapper,
) {
  const next = { ...positions };
  const source: DocumentSide =
    before === "split" ? (after === "split" ? "translated" : after) : before;
  const origin = positions[source] || { page: 1, fraction: 0 };
  next[source] = { ...origin };
  if (after === "split") next[otherSide(source)] = map(source, origin);
  else if (before !== "split" && after !== source)
    next[after] = map(source, origin);
  return { active: after === "split" ? source : after, positions: next };
}

export function planEnableSync(positions: Positions, map: PositionMapper) {
  const translated = positions.translated || { page: 1, fraction: 0 };
  return {
    active: "translated" as const,
    positions: {
      ...positions,
      translated: { ...translated },
      original: map("translated", translated),
    },
  };
}

export type PageBox = { page: number; top: number; height: number };
export function captureViewport(
  pages: PageBox[],
  top: number,
  viewportHeight: number,
): PagePosition | null {
  if (!pages.length || viewportHeight <= 0) return null;
  const focus = top + viewportHeight * 0.2;
  const page = [...pages].reverse().find((p) => p.top <= focus) || pages[0];
  const point = clamp(focus, page.top, page.top + page.height);
  return {
    page: page.page,
    fraction: clamp((point - page.top) / page.height),
    viewport: clamp((point - top) / viewportHeight),
  };
}
export function scrollToPosition(
  page: PageBox,
  position: PagePosition,
  viewportHeight: number,
) {
  if (position.page === 1 && position.fraction === 0 && !position.viewport)
    return 0;
  return (
    page.top +
    clamp(position.fraction) * page.height -
    (position.viewport || 0) * viewportHeight
  );
}

export function parsePageInput(value: string, current: number, total: number) {
  const number = value.trim() ? Number(value) : Number.NaN;
  return Number.isFinite(number)
    ? clamp(Math.trunc(number), 1, total)
    : current;
}
