"use client";
import { useCallback, useRef, useState } from "react";
import MicButton, { type RecorderLike } from "@/components/MicButton";
import Button from "@/components/ui/Button";
import Orb, { type OrbState } from "@/components/ui/Orb";
import type { SessionApi, Turn } from "@/lib/types";

type Props = {
  api: SessionApi;
  sessionId: string;
  initial: { messages: string[]; audio_urls: string[] };
  total?: number;
  onDone: () => void;
  createRecorder?: () => Promise<RecorderLike>;
};

type Line = { who: "Interviewer" | "You"; text: string };

export default function InterviewScreen({ api, sessionId, initial, total = 5, onDone, createRecorder }: Props) {
  const [question, setQuestion] = useState(initial.messages[initial.messages.length - 1] ?? "");
  const [lines, setLines] = useState<Line[]>(initial.messages.map((text) => ({ who: "Interviewer", text })));
  const [asked, setAsked] = useState(1);
  const [menu, setMenu] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [orb, setOrb] = useState<OrbState>(initial.audio_urls.length ? "speaking" : "idle");
  const retry = useRef<(() => Promise<Turn>) | null>(null);

  const play = useCallback((urls: string[]) => {
    if (!urls.length || typeof Audio === "undefined") return;
    setOrb("speaking");
    const queue = [...urls];
    const next = () => {
      const url = queue.shift();
      if (!url) return setOrb("idle");
      const audio = new Audio(`/api${url}`);
      audio.onended = next;
      audio.onerror = () => setOrb("idle");
      audio.play().catch(() => setOrb("idle"));
    };
    next();
  }, []);

  const run = useCallback(async (action: () => Promise<Turn>, userText?: string) => {
    retry.current = action;
    setBusy(true);
    setFailed(false);
    try {
      const turn = await action();
      const said = userText ?? turn.transcript ?? "";
      setLines((l) => [...l, ...(said ? [{ who: "You" as const, text: said }] : []),
        ...turn.messages.map((text) => ({ who: "Interviewer" as const, text }))]);
      setQuestion(turn.messages[turn.messages.length - 1] ?? "");
      if (turn.kind === "ask") setAsked((n) => n + 1);
      setTyped("");
      setMenu(false);
      play(turn.audio_urls);
      if (turn.state === "done") onDone();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }, [onDone, play]);

  const sendTyped = () => { const text = typed.trim(); if (text) void run(() => api.sendText(sessionId, text), text); };
  const sendAudio = useCallback((blob: Blob) => { void run(() => api.sendAudio(sessionId, blob)); }, [run, api, sessionId]);

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center px-4 py-6">
      <header className="flex w-full items-center justify-between">
        <div className="flex gap-1.5" aria-label={`Question ${Math.min(asked, total)} of ${total}`}>
          {Array.from({ length: total }, (_, i) => (
            <span key={i} className={`h-1.5 w-6 rounded-full ${i < asked ? "bg-accent" : "bg-hairline"}`} />
          ))}
        </div>
        <button type="button" aria-label="More" onClick={() => setMenu((m) => !m)} className="px-2 text-2xl leading-none text-muted">•••</button>
      </header>

      <div className="flex flex-1 flex-col items-center justify-center gap-10 text-center">
        <Orb state={busy ? "listening" : orb} />
        <p className="max-w-md text-2xl font-medium leading-snug tracking-tight">{question}</p>
        {failed && (
          <p role="alert" className="text-[15px] text-muted">
            Something went wrong.{" "}
            <button type="button" className="text-accent" onClick={() => retry.current && void run(retry.current)}>Try again</button>
          </p>
        )}
      </div>

      <MicButton onRecorded={sendAudio} disabled={busy} createRecorder={createRecorder} />

      {menu && (
        <aside className="mt-6 w-full space-y-4 rounded-card border border-hairline bg-surface p-5 text-left">
          <h2 className="text-[13px] font-medium uppercase tracking-wide text-muted">Transcript</h2>
          <ul className="max-h-48 space-y-2 overflow-y-auto text-[15px]">
            {lines.map((l, i) => (<li key={i}><span className="text-muted">{l.who}: </span>{l.text}</li>))}
          </ul>
          <textarea
            aria-label="Type your answer"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            rows={3}
            className="w-full rounded-control border border-hairline bg-bg p-3 text-[15px] outline-none focus:border-accent"
          />
          <div className="flex items-center justify-between">
            <Button variant="ghost" onClick={() => void run(() => api.end(sessionId))}>End interview</Button>
            <Button disabled={busy || !typed.trim()} onClick={sendTyped}>Send</Button>
          </div>
        </aside>
      )}
    </main>
  );
}
