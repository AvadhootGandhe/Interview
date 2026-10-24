import type { InputHTMLAttributes } from "react";
import { cx } from "./cx";

export interface SearchFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  label: string;
  value: string;
  onChange: (value: string) => void;
}

export function SearchField({ label, value, onChange, className, placeholder, ...props }: SearchFieldProps) {
  return (
    <label className={cx("relative block", className)}>
      <span className="sr-only">{label}</span>
      <svg
        aria-hidden
        viewBox="0 0 20 20"
        className="pointer-events-none absolute left-4 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-muted"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      >
        <circle cx="8.5" cy="8.5" r="5.75" />
        <path d="M13 13l4 4" />
      </svg>
      <input
        type="search"
        aria-label={label}
        value={value}
        placeholder={placeholder ?? label}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        spellCheck={false}
        className={cx(
          "w-full min-h-tap rounded-sm bg-surface pl-11 pr-4 py-3 text-body text-fg placeholder:text-muted",
          "outline-none focus-visible:ring-4 focus-visible:ring-accent/30",
        )}
        {...props}
      />
    </label>
  );
}
