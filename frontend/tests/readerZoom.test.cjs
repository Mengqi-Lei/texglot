const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  attachWheelZoom,
  zoomFromWheel,
} = require("../../tmp/reader-tests/readerZoom.js");

function harness(t) {
  const oldRequest = global.requestAnimationFrame;
  const oldCancel = global.cancelAnimationFrame;
  const frames = new Map();
  let id = 0;
  global.requestAnimationFrame = (callback) => {
    frames.set(++id, callback);
    return id;
  };
  global.cancelAnimationFrame = (frame) => frames.delete(frame);
  t.after(() => {
    global.requestAnimationFrame = oldRequest;
    global.cancelAnimationFrame = oldCancel;
  });
  const element = new EventTarget();
  element.clientHeight = 800;
  const deltas = [];
  const dispose = attachWheelZoom(element, (delta) => deltas.push(delta));
  const dispatch = (values) => {
    const event = new Event("wheel", { cancelable: true });
    Object.assign(event, { ctrlKey: true, deltaY: 0, deltaMode: 0 }, values);
    element.dispatchEvent(event);
    return event;
  };
  const flush = () => {
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach((callback) => callback());
  };
  return { deltas, dispose, dispatch, flush };
}

test("Ctrl wheel consumes browser zoom, batches trackpad input, and leaves normal scrolling alone", (t) => {
  const h = harness(t);
  assert.equal(
    h.dispatch({ ctrlKey: false, deltaY: 80 }).defaultPrevented,
    false,
  );
  h.flush();
  assert.deepEqual(h.deltas, []);
  assert.equal(h.dispatch({ deltaY: -40 }).defaultPrevented, true);
  h.dispatch({ deltaY: -30 });
  h.dispatch({ deltaY: -30 });
  assert.deepEqual(h.deltas, []);
  h.flush();
  assert.deepEqual(h.deltas, [-100]);
  assert.ok(zoomFromWheel(1, h.deltas[0]) > 1);
  assert.ok(Math.abs(zoomFromWheel(zoomFromWheel(1, -100), 100) - 1) < 1e-12);
  h.dispose();
});

test("mouse line/page units are normalized and reader zoom cannot exceed its limits", (t) => {
  const h = harness(t);
  h.dispatch({ deltaY: 3, deltaMode: 1 });
  h.flush();
  h.dispatch({ deltaY: 48 });
  h.flush();
  h.dispatch({ deltaY: 0.06, deltaMode: 2 });
  h.flush();
  assert.deepEqual(h.deltas, [48, 48, 48]);
  h.dispatch({ deltaY: -1e8 });
  h.flush();
  assert.ok(zoomFromWheel(1, h.deltas.at(-1)) < 1.3);
  assert.equal(zoomFromWheel(2.5, -100), 2.5);
  assert.equal(zoomFromWheel(0.5, 100), 0.5);
  assert.ok(zoomFromWheel(2.5, 100) < 2.5);
  assert.ok(zoomFromWheel(0.5, -100) > 0.5);
  h.dispose();
});

test("leaving the reader cancels pending zoom and removes interception", (t) => {
  const h = harness(t);
  h.dispatch({ deltaY: -100 });
  h.dispose();
  h.flush();
  assert.deepEqual(h.deltas, []);
  assert.equal(h.dispatch({ deltaY: -100 }).defaultPrevented, false);
  h.flush();
  assert.deepEqual(h.deltas, []);
});
