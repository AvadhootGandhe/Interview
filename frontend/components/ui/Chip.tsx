import type { ButtonHTMLAttributes } from "react";
import { cx } from "./cx";

export interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
}

export function Chip({ selected = false, className, type = "button", ...props }: ChipProps) {
  return (
    <button
      type={type}
      aria-pressed={selected}
      className={cx(
        "inline-flex items-center min-h-tap rounded-full px-5 text-body border-hairline border",
        "transition-[transform,background-color,color] duration-200 ease-out active:scale-[0.97]",
        "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/30",
        "motion-reduce:transition-none motion-reduce:active:scale-100",
        selected ? "bg-accent text-on-accent border-transparent" : "bg-bg text-fg hover:bg-surface",
        className,
      )}
      {...props}
    />
  );
}
