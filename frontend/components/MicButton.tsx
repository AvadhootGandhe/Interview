"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { createBrowserRecorder } from "@/lib/recorder";

export type RecorderLike = { start(): void; stop(): void; onstop?: (audio: Blob) => void };

type Props = {
  onRecorded: (audio: Blob) => void;
  onError?: (error: unknown) => void;
  disabled?: boolean;
  createRecorder?: () => Promise<RecorderLike>;
};

const DENIED = "Microphone access is needed. Allow it in your browser and try again.";

export default function MicButton({ onRecorded, onError, disabled = false, createRecorder = createBrowserRecorder }: Props) {
  const [pressed, setPressed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wanted = useRef(false);
  const recorder = useRef<RecorderLike | null>(null);

  const begin = useCallback(async () => {
    if (disabled || wanted.current) return;
    wanted.current = true;
    setPressed(true);
    setError(null);
    try {
      const rec = await createRecorder();
      if (!wanted.current) return; // released before the mic was ready
      rec.onstop = onRecorded;
      recorder.current = rec;
      rec.start();
    } catch (e) {
      wanted.current = false;
      setPressed(false);
      setError(DENIED);
      onError?.(e);
    }
  }, [disabled, createRecorder, onRecorded, onError]);

  const end = useCallback(() => {
    if (!wanted.current) return;
    wanted.current = false;
    setPressed(false);
    recorder.current?.stop();
    recorder.current = null;
  }, []);

  useEffect(() => {
    const isTyping = (t: EventTarget | null) => t instanceof HTMLElement && ["INPUT", "TEXTAREA"].includes(t.tagName);
    const down = (e: KeyboardEvent) => { if (e.code === "Space" && !e.repeat && !isTyping(e.target)) { e.preventDefault(); void begin(); } };
    const up = (e: KeyboardEvent) => { if (e.code === "Space") end(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [begin, end]);

  return (
    <div className="flex flex-col items-center gap-3">
      <button
        type="button"
        aria-label="Hold to answer"
        aria-pressed={pressed}
        disabled={disabled}
        onPointerDown={() => void begin()}
        onPointerUp={end}
        onPointerLeave={end}
        onPointerCancel={end}
        className={`flex h-20 w-20 items-center justify-center rounded-full text-white transition active:scale-95 disabled:opacity-40 ${pressed ? "scale-110 bg-red-500" : "bg-accent"}`}
      >
        <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z" />
        </svg>
      </button>
      <p className="text-[13px] text-muted" role={error ? "alert" : undefined}>{error ?? (pressed ? "Listening…" : "Hold to answer, or press Space")}</p>
    </div>
  );
}
