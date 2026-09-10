const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  createPositionMapper,
  planModeChange,
  planEnableSync,
  captureViewport,
  scrollToPosition,
} = require("../../tmp/reader-tests/readerNavigation.js");
const same = (a, b) => {
  assert.equal(a.page, b.page);
  assert.ok(Math.abs(a.fraction - b.fraction) < 1e-9);
  assert.equal(a.viewport, b.viewport);
};
const alignment = {
  kind: "landmarks",
  heights: { original: Array(15).fill(1.3), translated: Array(14).fill(1.3) },
  pairs: [
    {
      id: "section.1",
      original: { page: 2, fraction: 0.1 },
      translated: { page: 2, fraction: 0.2 },
    },
    {
      id: "subsection.6.3",
      original: { page: 9, fraction: 0.69678 },
      translated: { page: 8, fraction: 0.66789 },
    },
    {
      id: "table.4",
      original: { page: 10, fraction: 0.08567 },
      translated: { page: 9, fraction: 0.0872 },
    },
    {
      id: "section.7",
      original: { page: 10, fraction: 0.4567 },
      translated: { page: 9, fraction: 0.39563 },
    },
    {
      id: "figure.10",
      original: { page: 15, fraction: 0.8 },
      translated: { page: 14, fraction: 0.7 },
    },
  ],
};
const map = createPositionMapper(alignment, { original: 15, translated: 14 });

test("Table 4 maps translated page 9 to original page 10, independent of total scroll percentages", () => {
  same(map("translated", { page: 9, fraction: 0.0872, viewport: 0.2 }), {
    page: 10,
    fraction: 0.08567,
    viewport: 0.2,
  });
  for (const pair of alignment.pairs) {
    same(map("original", pair.original), pair.translated);
    same(map("translated", pair.translated), pair.original);
  }
});
test("interpolation uses actual page aspect ratios between content landmarks", () => {
  const mapper = createPositionMapper(
    {
      heights: { original: [1, 2, 1], translated: [2, 1, 3] },
      pairs: [
        {
          original: { page: 1, fraction: 0.5 },
          translated: { page: 1, fraction: 0.25 },
        },
        {
          original: { page: 3, fraction: 0.5 },
          translated: { page: 3, fraction: 0.5 },
        },
      ],
    },
    { original: 3, translated: 3 },
  );
  // Source coordinate 2 is halfway from .5 to 3.5. Target coordinate is 2.5.
  same(mapper("original", { page: 2, fraction: 0.5, viewport: 0.3 }), {
    page: 2,
    fraction: 0.5,
    viewport: 0.3,
  });
});
test("enabling sync always preserves the translation and realigns the original", () => {
  const translation = { page: 9, fraction: 0.0872, viewport: 0.2 };
  const previous = {
    original: { page: 3, fraction: 0.9 },
    translated: translation,
  };
  const result = planEnableSync(previous, map);
  assert.equal(result.active, "translated");
  same(result.positions.translated, translation);
  same(result.positions.original, {
    page: 10,
    fraction: 0.08567,
    viewport: 0.2,
  });
  assert.equal(previous.original.page, 3);
});
test("entering comparison uses whichever single document was being read", () => {
  const positions = {
    original: { page: 10, fraction: 0.08567, viewport: 0.2 },
    translated: { page: 4, fraction: 0.5, viewport: 0.1 },
  };
  const fromOriginal = planModeChange("original", "split", positions, map);
  same(fromOriginal.positions.original, positions.original);
  same(fromOriginal.positions.translated, {
    page: 9,
    fraction: 0.0872,
    viewport: 0.2,
  });
  assert.equal(fromOriginal.active, "original");
  const fromTranslation = planModeChange("translated", "split", positions, map);
  same(fromTranslation.positions.translated, positions.translated);
  same(
    fromTranslation.positions.original,
    map("translated", positions.translated),
  );
  assert.equal(fromTranslation.active, "translated");
});
test("leaving comparison keeps the selected pane even if the two panes were independently positioned", () => {
  const positions = {
    original: { page: 13, fraction: 0.2, viewport: 0.25 },
    translated: { page: 4, fraction: 0.8, viewport: 0.4 },
  };
  for (const side of ["original", "translated"]) {
    const result = planModeChange("split", side, positions, map);
    same(result.positions[side], positions[side]);
    assert.equal(result.active, side);
  }
});
test("single-document swaps and repeated view changes do not accumulate location error", () => {
  const start = { page: 9, fraction: 0.21, viewport: 0.2 };
  let positions = { translated: start };
  for (let i = 0; i < 50; i++) {
    positions = planModeChange(
      "translated",
      "original",
      positions,
      map,
    ).positions;
    positions = planModeChange("original", "split", positions, map).positions;
    positions = planModeChange("split", "translated", positions, map).positions;
  }
  same(positions.translated, start);
});
test("zoom, sidebar and viewport changes keep the same content at the same viewport reference line", () => {
  const oldPage = { page: 3, top: 1700, height: 800 };
  const position = captureViewport([oldPage], 1860, 600);
  same(position, { page: 3, fraction: 0.35, viewport: 0.2 });
  const newPage = { page: 3, top: 1100, height: 500 };
  const top = scrollToPosition(newPage, position, 700);
  assert.ok(Math.abs(top - 1135) < 1e-9);
  same(captureViewport([newPage], top, 700), position);
});
test("PDFs without common destinations use page-local coordinates, never document-length proportions", () => {
  const fallback = createPositionMapper(null, {
    original: 100,
    translated: 80,
  });
  same(fallback("translated", { page: 60, fraction: 0.7, viewport: 0.2 }), {
    page: 60,
    fraction: 0.7,
    viewport: 0.2,
  });
  same(fallback("original", { page: 99, fraction: 0.7 }), {
    page: 80,
    fraction: 0.7,
  });
});

test("a destination at the document boundary does not disable other content landmarks", () => {
  const withBoundary = {
    ...alignment,
    pairs: [
      {
        id: "start",
        original: { page: 1, fraction: 0 },
        translated: { page: 1, fraction: 0 },
      },
      ...alignment.pairs,
    ],
  };
  const mapper = createPositionMapper(withBoundary, {
    original: 15,
    translated: 14,
  });
  same(mapper("translated", { page: 9, fraction: 0.0872 }), {
    page: 10,
    fraction: 0.08567,
  });
});
test("mismatched PDF versions never reuse a stale content map", () => {
  const stale = {
    ...alignment,
    documents: { original: "old-a", translated: "old-b" },
  };
  const mapper = createPositionMapper(
    stale,
    { original: 15, translated: 14 },
    { original: "new-a", translated: "new-b" },
  );
  same(mapper("translated", { page: 9, fraction: 0.0872 }), {
    page: 9,
    fraction: 0.0872,
  });
});

test("page input accepts whole pages and safely retains the current page for incomplete text", () => {
  const {
    parsePageInput,
  } = require("../../tmp/reader-tests/readerNavigation.js");
  assert.equal(parsePageInput("", 9, 14), 9);
  assert.equal(parsePageInput("invalid", 9, 14), 9);
  assert.equal(parsePageInput("2.5", 9, 14), 2);
  assert.equal(parsePageInput("100", 9, 14), 14);
  assert.equal(parsePageInput("0", 9, 14), 1);
});

test("a moved figure follows the identical artwork across section boundaries in both directions", () => {
  const regions = [
    {
      id: "figure.17",
      original: { page: 38, start: 0.24, end: 0.49 },
      translated: { page: 33, start: 0.09, end: 0.34 },
    },
  ];
  const mapper = createPositionMapper(
    {
      heights: { original: Array(87).fill(1), translated: Array(79).fill(1) },
      pairs: [
        {
          id: "section.7",
          original: { page: 38, fraction: 0.6 },
          translated: { page: 32, fraction: 0.2 },
        },
      ],
      regions,
    },
    { original: 87, translated: 79 },
  );
  const translation = { page: 33, fraction: 0.2, viewport: 0.2 };
  same(mapper("translated", translation), {
    page: 38,
    fraction: 0.35,
    viewport: 0.2,
  });
  same(mapper("original", mapper("translated", translation)), translation);
});

test("ambiguous or stale figure regions fall back to the normal content map", () => {
  const region = {
    id: "figure.17",
    original: { page: 38, start: 0.24, end: 0.49 },
    translated: { page: 33, start: 0.09, end: 0.34 },
  };
  const metadata = {
    documents: { original: "a", translated: "b" },
    heights: { original: [], translated: [] },
    pairs: [],
    regions: [region, { ...region, id: "figure.18" }],
  };
  const counts = { original: 87, translated: 79 };
  const position = { page: 33, fraction: 0.2, viewport: 0.2 };
  same(
    createPositionMapper(metadata, counts)("translated", position),
    position,
  );
  same(
    createPositionMapper({ ...metadata, regions: [region] }, counts, {
      original: "new-a",
      translated: "new-b",
    })("translated", position),
    position,
  );
});
