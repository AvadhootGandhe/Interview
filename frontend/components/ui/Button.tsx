import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cx } from "./cx";

export type ButtonVariant = "primary" | "secondary" | "plain";

const base =
  "inline-flex items-center justify-center gap-2 min-h-tap min-w-tap select-none text-body font-medium " +
  "transition-[transform,background-color,opacity] duration-200 ease-out active:scale-[0.97] " +
  "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/30 " +
  "disabled:opacity-40 disabled:active:scale-100 disabled:cursor-not-allowed motion-reduce:transition-none motion-reduce:active:scale-100";

const variants: Record<ButtonVariant, string> = {
  // The only place the accent fills a surface: the screen's one primary action.
  primary: "rounded-full px-8 bg-accent text-on-accent hover:bg-accent/90",
  secondary: "rounded-full px-6 bg-surface text-fg hover:bg-hairline",
  plain: "rounded-full px-4 text-muted hover:text-fg",
};

export function buttonClasses(variant: ButtonVariant = "primary", className?: string) {
  return cx(base, variants[variant], className);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", className, type = "button", ...props },
  ref,
) {
  return <button ref={ref} type={type} className={buttonClasses(variant, className)} {...props} />;
});
