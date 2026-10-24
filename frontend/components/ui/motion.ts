import type { Transition } from "framer-motion";

/** Soft, slightly damped spring used across the app. */
export const spring: Transition = { type: "spring", stiffness: 260, damping: 30, mass: 0.9 };

/** Gentle enter used for step changes and sheets. */
export const enter = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: spring,
};
