const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  normalizedRect,
  mergeRects,
} = require("../../tmp/reader-tests/readerGeometry.js");

test("annotation geometry remains proportional after zoom and page resize", () => {
  const region = normalizedRect(
    { left: 100, top: 200, right: 400, bottom: 216 },
    { left: 40, top: 80, width: 600, height: 800 },
  );
  assert.equal(region.x, 0.1);
  assert.equal(region.y, 0.15);
  assert.equal(region.width, 0.5);
  assert.ok(Math.abs(region.height - 0.02) < 1e-12);
  const resized = normalizedRect(
    { left: 50, top: 100, right: 200, bottom: 108 },
    { left: 20, top: 40, width: 300, height: 400 },
  );
  assert.deepEqual(region, resized);
  assert.equal(
    normalizedRect(
      { left: -30, top: 5, right: -10, bottom: 20 },
      { left: 0, top: 0, width: 100, height: 100 },
    ),
    null,
  );
});
test("merge overlapping glyph rectangles without merging columns or lines", () => {
  const rectangles = [
    { x: 0.1, y: 0.2, width: 0.2, height: 0.02 },
    { x: 0.2, y: 0.2, width: 0.2, height: 0.02 },
    { x: 0.1, y: 0.3, width: 0.4, height: 0.02 },
    { x: 0.7, y: 0.2, width: 0.2, height: 0.02 },
  ];
  const merged = mergeRects(rectangles);
  assert.equal(merged.length, 3);
  assert.ok(Math.abs(merged[0].width - 0.3) < 1e-12);
  assert.equal(rectangles[0].width, 0.2);
});

const {
  writeDraft,
  readDrafts,
  clearDraft,
} = require("../../tmp/reader-tests/annotationDrafts.js");
test("a completed save cannot erase newer unsent annotation text", () => {
  class Storage {
    getItem(key) {
      return this[key] ?? null;
    }
    setItem(key, value) {
      this[key] = value;
    }
    removeItem(key) {
      delete this[key];
    }
  }
  global.localStorage = new Storage();
  writeDraft("job", {
    id: "annotation",
    comment: "latest edit",
    revision: 2,
    updated: 1,
  });
  clearDraft("job", "annotation", "older edit");
  assert.equal(readDrafts("job")[0].comment, "latest edit");
  assert.equal(readDrafts("another-job").length, 0);
  clearDraft("job", "annotation", "latest edit");
  assert.equal(readDrafts("job").length, 0);
  delete global.localStorage;
});
