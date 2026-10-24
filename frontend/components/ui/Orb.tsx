"use client";

import { motion, useReducedMotion, type TargetAndTransition } from "framer-motion";
import { cx } from "./cx";

export type OrbState = "idle" | "speaking" | "listening" | "thinking";

const neutral =
  "radial-gradient(circle at 35% 30%, rgb(var(--bg)) 0%, rgb(var(--surface)) 45%, rgb(var(--muted) / 0.55) 100%)";
const blue =
  "radial-gradient(circle at 35% 30%, rgb(var(--accent) / 0.55) 0%, rgb(var(--accent)) 70%, rgb(var(--accent)) 100%)";

function animationFor(state: OrbState, reduce: boolean): TargetAndTransition {
  if (reduce) {
    return { scale: state === "listening" ? 1.04 : 1, opacity: state === "thinking" ? 0.7 : 1, transition: { duration: 0.2 } };
  }
  switch (state) {
    case "speaking":
      return { scale: [1, 1.08, 1], opacity: 1, transition: { duration: 0.9, repeat: Infinity, ease: "easeInOut" } };
    case "listening":
      return { scale: 1.06, opacity: 1, transition: { type: "spring", stiffness: 200, damping: 18 } };
    case "thinking":
      return { scale: 1, opacity: [1, 0.6, 1], transition: { duration: 1.6, repeat: Infinity, ease: "easeInOut" } };
    default:
      // Slow, calm breathing.
      return { scale: [1, 1.035, 1], opacity: 1, transition: { duration: 4.5, repeat: Infinity, ease: "easeInOut" } };
  }
}

export interface OrbProps {
  state: OrbState;
  className?: string;
}

export function Orb({ state, className }: OrbProps) {
  const reduce = useReducedMotion() ?? false;
  return (
    <motion.div
      data-testid="orb"
      data-state={state}
      aria-hidden
      animate={animationFor(state, reduce)}
      className={cx(
        "rounded-full transition-[background,box-shadow] duration-500 motion-reduce:transition-none",
        "h-44 w-44 sm:h-56 sm:w-56",
        state === "listening" ? "shadow-[0_0_80px_rgb(var(--accent)/0.35)]" : "shadow-[0_20px_60px_rgb(0_0_0/0.08)]",
        className,
      )}
      style={{ background: state === "listening" ? blue : neutral }}
    />
  );
}
