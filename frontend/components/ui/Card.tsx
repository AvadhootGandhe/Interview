import type { HTMLAttributes } from "react";
import { cx } from "./cx";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("rounded-lg bg-surface p-5", className)} {...props} />;
}
