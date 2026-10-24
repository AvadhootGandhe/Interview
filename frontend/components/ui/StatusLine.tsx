import { Button } from "./Button";
import { cx } from "./cx";

export interface StatusLineProps {
  text: string;
  action?: { label: string; onClick: () => void };
  className?: string;
}

/** Calm loading / error / empty state: one line, at most one action. */
export function StatusLine({ text, action, className }: StatusLineProps) {
  return (
    <div role="status" className={cx("flex flex-col items-center gap-2 text-center", className)}>
      <p className="text-body text-muted">{text}</p>
      {action && (
        <Button variant="plain" className="text-accent hover:text-accent" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}
