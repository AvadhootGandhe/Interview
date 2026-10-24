"use client";

import { useId, useRef, type KeyboardEvent } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cx } from "./cx";
import { spring } from "./motion";

export interface SegmentedControlProps {
  label: string;
  options: string[];
  value: string | null;
  onChange: (value: string) => void;
  className?: string;
}

/**
 * iOS-style segmented control. Stacks vertically on narrow screens so long
 * labels ("Architect/Principal") never cause horizontal scroll.
 */
export function SegmentedControl({ label, options, value, onChange, className }: SegmentedControlProps) {
  const id = useId();
  const reduce = useReducedMotion();
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!dir || options.length === 0) return;
    e.preventDefault();
    const current = Math.max(0, options.indexOf(value ?? ""));
    const next = (current + dir + options.length) % options.length;
    refs.current[next]?.focus();
    onChange(options[next]);
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cx("flex flex-col sm:flex-row gap-1 rounded-lg sm:rounded-full bg-surface p-1", className)}
    >
      {options.map((opt, i) => {
        const checked = opt === value;
        return (
          <button
            key={opt}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked || (value === null && i === 0) ? 0 : -1}
            onClick={() => onChange(opt)}
            className={cx(
              "relative flex-1 min-h-tap rounded-md sm:rounded-full px-4 text-body whitespace-nowrap",
              "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/30",
              checked ? "text-accent font-medium" : "text-fg",
            )}
          >
            {checked && (
              <motion.span
                layoutId={`seg-${id}`}
                transition={reduce ? { duration: 0 } : spring}
                className="absolute inset-0 rounded-md sm:rounded-full bg-bg shadow-sm"
                aria-hidden
              />
            )}
            <span className="relative">{opt}</span>
          </button>
        );
      })}
    </div>
  );
}
