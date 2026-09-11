export const MIN_ZOOM = 0.5;
export const MAX_ZOOM = 2.5;

export const clampZoom = (zoom: number) =>
  Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));

export const zoomFromWheel = (zoom: number, delta: number) =>
  clampZoom(zoom * Math.exp(-delta / 1000));

/** Intercept browser zoom only over the PDF area, batching trackpad events. */
export function attachWheelZoom(
  element: HTMLElement,
  onDelta: (delta: number) => void,
) {
  let frame = 0;
  let pending = 0;
  const wheel = (event: WheelEvent) => {
    if (!event.ctrlKey) return;
    // A non-passive native listener is required: React wheel listeners may
    // otherwise let Chromium zoom the entire interface as well as the PDF.
    event.preventDefault();
    if (!Number.isFinite(event.deltaY) || !event.deltaY) return;
    const unit =
      event.deltaMode === 1
        ? 16
        : event.deltaMode === 2
          ? element.clientHeight
          : 1;
    pending += Math.max(-240, Math.min(240, event.deltaY * unit));
    if (!frame)
      frame = requestAnimationFrame(() => {
        frame = 0;
        const delta = pending;
        pending = 0;
        if (delta) onDelta(delta);
      });
  };
  element.addEventListener("wheel", wheel, { passive: false });
  return () => {
    element.removeEventListener("wheel", wheel);
    cancelAnimationFrame(frame);
  };
}
