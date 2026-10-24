import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { selected?: boolean };

export default function Chip({ selected = false, className = "", type = "button", ...rest }: Props) {
  const tone = selected ? "bg-accent text-white border-accent" : "bg-surface text-ink border-hairline hover:border-accent";
  return (
    <button type={type} aria-pressed={selected} className={`min-h-[44px] rounded-full border px-5 py-2.5 text-[15px] transition ${tone} ${className}`} {...rest} />
  );
}
