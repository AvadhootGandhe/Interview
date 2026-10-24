import { cx } from "@/components/ui";
import type { Progress } from "@/lib/api";

export function ProgressDots({ progress }: { progress: Progress }) {
  const total = Math.max(1, progress.total);
  const current = Math.min(Math.max(0, progress.current), total);
  return (
    <div
      role="progressbar"
      aria-label="Interview progress"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={current}
      aria-valuetext={`Question ${current} of ${total}`}
      className="flex items-center gap-2"
    >
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={cx(
            "h-1.5 rounded-full transition-all duration-300 motion-reduce:transition-none",
            i === current - 1 ? "w-4 bg-accent" : i < current ? "w-1.5 bg-fg/40" : "w-1.5 bg-hairline",
          )}
        />
      ))}
    </div>
  );
}
