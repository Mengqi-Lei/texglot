import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from "react";

const reducedMotion = "(prefers-reduced-motion: reduce)";
const subscribe = (changed: () => void) => {
  const media = window.matchMedia(reducedMotion);
  media.addEventListener("change", changed);
  return () => media.removeEventListener("change", changed);
};
const snapshot = () => window.matchMedia(reducedMotion).matches;

export function useReducedMotion() {
  return useSyncExternalStore(subscribe, snapshot, () => true);
}

function timing(speed: "fast" | "standard") {
  const style = getComputedStyle(document.documentElement);
  const duration = style.getPropertyValue(`--motion-${speed}`).trim();
  return {
    // CSS minifiers may turn 220ms into .22s; Web Animations use milliseconds.
    duration: parseFloat(duration) * (duration.endsWith("ms") ? 1 : 1000),
    easing: style.getPropertyValue("--motion-ease").trim(),
  };
}

/** Retain a closing overlay until its short exit animation has finished. */
export function usePresence(open: boolean) {
  const [present, setPresent] = useState(open);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (open || reduced) {
      setPresent(open);
      return;
    }
    const timer = setTimeout(() => setPresent(false), timing("fast").duration);
    return () => clearTimeout(timer);
  }, [open, reduced]);
  return open || present;
}

/** Animate explicit view changes without remounting forms or animating polling. */
export function useContentMotion<T extends HTMLElement>(
  ref: RefObject<T | null>,
  value: string,
  {
    resize = false,
    active = true,
  }: { resize?: boolean; active?: boolean } = {},
) {
  const reduced = useReducedMotion();
  const previous = useRef({ value, height: 0 });
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !active) return;
    const before = previous.current;
    const height = element.getBoundingClientRect().height;
    previous.current = { value, height };
    const observer = resize
      ? new ResizeObserver(() => {
          if (animation?.playState !== "running")
            previous.current.height = element.getBoundingClientRect().height;
        })
      : null;
    let animation: Animation | undefined;
    observer?.observe(element);
    if (before.value !== value && !reduced)
      animation = element.animate(
        [
          {
            opacity: 0.65,
            ...(resize
              ? { height: `${before.height}px` }
              : { translate: "0 3px" }),
          },
          {
            opacity: 1,
            ...(resize ? { height: `${height}px` } : { translate: "0 0" }),
          },
        ],
        timing("standard"),
      );
    return () => {
      observer?.disconnect();
      if (resize && animation?.playState === "running")
        previous.current.height = element.getBoundingClientRect().height;
      animation?.cancel();
    };
  }, [ref, value, resize, reduced, active]);
}
