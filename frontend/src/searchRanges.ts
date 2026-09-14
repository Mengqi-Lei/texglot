export type TextSlice = { item: number; start: number; end: number };

/** Map PDF.js's original-text match offsets to immutable text-layer nodes. */
export function textSlices(
  lengths: number[],
  matches: number[],
  sizes: number[],
): TextSlice[][] {
  let item = 0,
    offset = 0;
  return matches.map((start, index) => {
    const end = start + sizes[index];
    while (item < lengths.length && offset + lengths[item] <= start)
      offset += lengths[item++];
    const slices: TextSlice[] = [];
    for (let i = item, at = offset; i < lengths.length && at < end; i++) {
      const from = Math.max(0, start - at),
        to = Math.min(lengths[i], end - at);
      if (to > from) slices.push({ item: i, start: from, end: to });
      at += lengths[i];
    }
    return slices;
  });
}
