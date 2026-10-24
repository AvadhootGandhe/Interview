"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Button, cx, spring } from "@/components/ui";
import type { ThreadTurn } from "@/lib/api";

export interface MoreMenuProps {
  transcript: ThreadTurn[];
  busy: boolean;
  focusAnswer?: boolean;
  onSend: (text: string) => void;
  onEnd: () => void;
  onClose: () => void;
}

/** Everything secondary on the interview screen: transcript, typing, End. */
export function MoreMenu({ transcript, busy, focusAnswer, onSend, onEnd, onClose }: MoreMenuProps) {
  const reduce = useReducedMotion();
  const [draft, setDraft] = useState("");
  const answerRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (focusAnswer) answerRef.current?.focus();
  }, [focusAnswer]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [transcript.length]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    onSend(text);
    setDraft("");
  }

  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center sm:items-center">
      <motion.div
        className="absolute inset-0 bg-[rgb(0_0_0/0.25)] backdrop-blur-sm"
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        onClick={onClose}
        aria-hidden
      />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label="More"
        initial={reduce ? false : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={spring}
        className="relative m-0 flex max-h-[85dvh] w-full max-w-content flex-col gap-5 rounded-t-lg bg-bg p-6 shadow-2xl sm:m-6 sm:rounded-lg"
      >
        <div className="flex items-center justify-between">
          <p className="text-body font-medium text-fg">Transcript</p>
          <Button variant="plain" className="-mr-4" onClick={onClose}>
            Done
          </Button>
        </div>

        <ol ref={listRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          {transcript.length === 0 && <li className="text-body text-muted">Nothing yet.</li>}
          {transcript.map((t, i) => (
            <li key={i} className={cx("text-body", t.role === "candidate" ? "text-fg" : "text-muted")}>
              <span className="sr-only">{t.role === "candidate" ? "You: " : "Interviewer: "}</span>
              {t.text}
            </li>
          ))}
        </ol>

        <form onSubmit={submit} className="flex flex-col gap-3">
          <textarea
            ref={answerRef}
            aria-label="Type your answer"
            placeholder="Type your answer"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) submit(e);
            }}
            className="w-full resize-none rounded-sm bg-surface px-4 py-3 text-body text-fg placeholder:text-muted outline-none focus-visible:ring-4 focus-visible:ring-accent/30"
          />
          <Button type="submit" variant="secondary" disabled={!draft.trim() || busy}>
            Send
          </Button>
        </form>

        <Button variant="plain" onClick={onEnd} className="self-center">
          End interview
        </Button>
      </motion.div>
    </div>
  );
}
