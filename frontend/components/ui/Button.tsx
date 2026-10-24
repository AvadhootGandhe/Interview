import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" };

export default function Button({ variant = "primary", className = "", type = "button", ...rest }: Props) {
  const base = "rounded-full px-7 py-3 text-[17px] font-medium transition active:scale-[0.98] disabled:opacity-40 disabled:active:scale-100";
  const styles = variant === "primary" ? "bg-accent text-white hover:opacity-90" : "text-accent hover:opacity-70 px-3 py-2 text-[15px]";
  return <button type={type} className={`${base} ${styles} ${className}`} {...rest} />;
}
