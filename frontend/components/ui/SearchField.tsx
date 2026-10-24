import type { InputHTMLAttributes } from "react";

export default function SearchField({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="search"
      autoComplete="off"
      className={`w-full rounded-control border border-hairline bg-surface px-4 py-3 text-[17px] text-ink outline-none placeholder:text-muted focus:border-accent ${className}`}
      {...rest}
    />
  );
}
