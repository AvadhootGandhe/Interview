"use client";
import { motion } from "framer-motion";

export type OrbState = "idle" | "speaking" | "listening";

export default function Orb({ state = "idle" }: { state?: OrbState }) {
  const scale = state === "speaking" ? [1, 1.12, 1] : state === "listening" ? 1.08 : [1, 1.04, 1];
  const duration = state === "speaking" ? 1.1 : 3.2;
  return (
    <motion.div
      aria-hidden
      data-state={state}
      animate={{ scale }}
      transition={{ duration, repeat: Array.isArray(scale) ? Infinity : 0, ease: "easeInOut" }}
      className="h-40 w-40 rounded-full"
      style={{
        background: state === "listening"
          ? "var(--accent)"
          : "radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--accent) 45%, white), var(--accent))",
        boxShadow: "0 20px 60px -20px var(--accent)",
      }}
    />
  );
}
