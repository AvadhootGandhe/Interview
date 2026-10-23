"use client";

import type { PointerEvent } from "react";
import { cx } from "@/components/ui";

export interface MicButtonProps {
  recording: boolean;
  disabled?: boolean;
  onPress: () => void;
  onRelease: () => void;
}

/** One round hold-to-talk button. Space is handled by the screen. */
export function MicButton({ recording, disabled, onPress, onRelease }: MicButtonProps) {
  function down(e: PointerEvent<HTMLButtonElement>) {
    if (disabled || (e.pointerType === "mouse" && e.button !== 0)) return;
    e.preventDefault();
    try {
      e.currentTarget.setPointerCapture?.(e.pointerId);
    } catch {
      /* not supported */
    }
    onPress();
  }

  return (
    <button
      type="button"
      aria-label="Hold to talk"
      aria-pressed={recording}
      disabled={disabled}
      onPointerDown={down}
      onPointerUp={onRelease}
      onPointerCancel={onRelease}
      onContextMenu={(e) => e.preventDefault()}
      className={cx(
        "grid h-[76px] w-[76px] touch-none select-none place-items-center rounded-full",
        "transition-[transform,background-color,color,box-shadow] duration-200 ease-out motion-reduce:transition-none",
        "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/30 disabled:opacity-40",
        recording
          ? "scale-110 bg-accent text-on-accent shadow-[0_0_0_10px_rgb(var(--accent)/0.15)] motion-reduce:scale-100"
          : "bg-surface text-fg border border-hairline",
      )}
    >
      <svg aria-hidden viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <rect x="9" y="3" width="6" height="12" rx="3" />
        <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
      </svg>
    </button>
  );
}
