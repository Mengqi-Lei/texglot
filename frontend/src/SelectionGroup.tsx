import { useLayoutEffect, useRef, useState, type HTMLAttributes } from "react";

type Bounds = { x: number; y: number; width: number; height: number };

/** A shared selection background; the original buttons retain their semantics. */
export default function SelectionGroup({
  as: Element = "div",
  value,
  children,
  className = "",
  onKeyDown,
  ...props
}: HTMLAttributes<HTMLElement> & { as?: "div" | "nav"; value: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [bounds, setBounds] = useState<Bounds | null>(null);
  useLayoutEffect(() => {
    const element = container.current;
    if (!element) return;
    const buttons = Array.from(
      element.querySelectorAll<HTMLButtonElement>(":scope > button"),
    );
    const measure = () => {
      const selected = buttons.find((button) =>
        button.matches(
          '.selected, [aria-pressed="true"], [aria-selected="true"], [aria-current="page"]',
        ),
      );
      if (!selected || !selected.offsetWidth) {
        setBounds(null);
        return;
      }
      const next = {
        x: selected.offsetLeft,
        y: selected.offsetTop,
        width: selected.offsetWidth,
        height: selected.offsetHeight,
      };
      setBounds((previous) =>
        previous &&
        Object.keys(next).every(
          (key) => previous[key as keyof Bounds] === next[key as keyof Bounds],
        )
          ? previous
          : next,
      );
    };
    measure();
    // Observe every label: changing language can move an unchanged selection.
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    buttons.forEach((button) => observer.observe(button));
    return () => observer.disconnect();
  }, [value]);

  return (
    <Element
      {...props}
      ref={container}
      className={`selection-group ${className}`}
      data-sliding={bounds ? "ready" : undefined}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.defaultPrevented || props.role !== "tablist") return;
        const buttons = Array.from(
          event.currentTarget.querySelectorAll<HTMLButtonElement>(
            ":scope > button:not(:disabled)",
          ),
        );
        const index = buttons.indexOf(
          document.activeElement as HTMLButtonElement,
        );
        if (index < 0) return;
        const next = {
          ArrowRight: (index + 1) % buttons.length,
          ArrowLeft: (index - 1 + buttons.length) % buttons.length,
          Home: 0,
          End: buttons.length - 1,
        }[event.key];
        if (next === undefined) return;
        event.preventDefault();
        buttons[next].focus();
        buttons[next].click();
      }}
    >
      {children}
      {bounds && (
        <span
          className="selection-indicator"
          aria-hidden="true"
          style={{
            width: bounds.width,
            height: bounds.height,
            transform: `translate(${bounds.x}px, ${bounds.y}px)`,
          }}
        />
      )}
    </Element>
  );
}
