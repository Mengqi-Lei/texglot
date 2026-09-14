const { test } = require("node:test");
const assert = require("node:assert/strict");
const { textSlices } = require("../../tmp/reader-tests/searchRanges.js");

test("search ranges cross text items and retain exact UTF-16 offsets", () => {
  const texts = ["Atten", "tion", "", " 注意", "力机制", " 𝛼"];
  const parts = textSlices(
    texts.map((t) => t.length),
    [0, 10, 16],
    [9, 5, 2],
  );
  assert.deepEqual(
    parts.map((slices) =>
      slices.map((s) => texts[s.item].slice(s.start, s.end)).join(""),
    ),
    ["Attention", "注意力机制", "𝛼"],
  );
});

test("item boundaries, empty spans and end-of-page matches do not include neighboring glyphs", () => {
  assert.deepEqual(textSlices([0, 2, 0, 3, 0], [0, 2, 4], [2, 1, 1]), [
    [{ item: 1, start: 0, end: 2 }],
    [{ item: 3, start: 0, end: 1 }],
    [{ item: 3, start: 2, end: 3 }],
  ]);
  assert.deepEqual(textSlices([], [], []), []);
});
