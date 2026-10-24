"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  api,
  audioSrc,
  DEFAULT_TOTAL,
  lineOf,
  progressOf,
  turnsOf,
  type Progress,
  type SessionReply,
  type ThreadTurn,
} from "@/lib/api";
import { recallSession } from "@/lib/session";
import { useRecorder } from "@/lib/useRecorder";
import { Button, Orb, StatusLine, type OrbState } from "@/components/ui";
import { MicButton } from "./MicButton";
import { MoreMenu } from "./MoreMenu";
import { ProgressDots } from "./ProgressDots";

type Problem = { kind: "mic" } | { kind: "send"; retry: () => void } | null;

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable;
}

export function InterviewScreen({ id }: { id: string }) {
  const router = useRouter();
  const reduce = useReducedMotion();
  const [question, setQuestion] = useState("");
  const [transcript, setTranscript] = useState<ThreadTurn[]>([]);
  const [progress, setProgress] = useState<Progress>({ current: 1, total: DEFAULT_TOTAL });
  const [speaking, setSpeaking] = useState(false);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [focusAnswer, setFocusAnswer] = useState(false);
  const [problem, setProblem] = useState<Problem>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopAudio = useCallback(() => {
    const a = audioRef.current;
    if (a) {
      a.onended = null;
      try {
        a.pause();
      } catch {
        /* jsdom */
      }
    }
    audioRef.current = null;
    setSpeaking(false);
  }, []);

  const speak = useCallback(
    (url: string | null | undefined) => {
      stopAudio();
      const src = audioSrc(url);
      if (!src || typeof Audio === "undefined") return;
      const audio = new Audio(src);
      audioRef.current = audio;
      audio.onended = () => setSpeaking(false);
      audio.onerror = () => setSpeaking(false);
      setSpeaking(true);
      try {
        Promise.resolve(audio.play()).catch(() => setSpeaking(false));
      } catch {
        setSpeaking(false);
      }
    },
    [stopAudio],
  );

  // Greeting handed over from the setup screen.
  useEffect(() => {
    const start = recallSession(id);
    if (!start) return;
    setQuestion(lineOf(start));
    setTranscript(turnsOf(start));
    setProgress(progressOf(start));
    speak(start.audio_url);
    return stopAudio;
  }, [id, speak, stopAudio]);

  const apply = useCallback(
    (res: SessionReply, typed?: string) => {
      const said = res.transcript || typed;
      setTranscript((t) => [...t, ...(said ? [{ role: "candidate" as const, text: said }] : []), ...turnsOf(res)]);
      const line = lineOf(res);
      if (line) setQuestion(line);
      setProgress(progressOf(res));
      if (res.done) {
        setDone(true);
        setMenuOpen(false);
      }
      speak(res.audio_url);
    },
    [speak],
  );

  const send = useCallback(
    async (call: () => Promise<SessionReply>, typed?: string) => {
      setSending(true);
      setProblem(null);
      try {
        apply(await call(), typed);
      } catch {
        setProblem({ kind: "send", retry: () => void send(call, typed) });
      } finally {
        setSending(false);
      }
    },
    [apply],
  );

  const recorder = useRecorder((audio) => void send(() => api.answerAudio(id, audio)));

  const press = useCallback(() => {
    if (sending || done) return;
    stopAudio(); // let the candidate barge in
    setProblem(null);
    recorder.start().catch(() => setProblem({ kind: "mic" }));
  }, [sending, done, stopAudio, recorder]);

  const release = recorder.stop;

  // Space: hold to talk.
  useEffect(() => {
    if (menuOpen || done) return;
    const isSpace = (e: KeyboardEvent) => e.code === "Space" || e.key === " ";
    const down = (e: KeyboardEvent) => {
      if (!isSpace(e) || isTyping(e.target)) return;
      e.preventDefault();
      if (e.repeat) return;
      press();
    };
    const up = (e: KeyboardEvent) => {
      if (!isSpace(e) || isTyping(e.target)) return;
      e.preventDefault();
      release();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [menuOpen, done, press, release]);

  async function end() {
    stopAudio();
    try {
      await api.endSession(id);
    } catch {
      /* the report screen has its own retry */
    }
    router.push(`/report/${encodeURIComponent(id)}`);
  }

  const orb: OrbState = recorder.recording ? "listening" : sending ? "thinking" : speaking ? "speaking" : "idle";

  return (
    <main className="mx-auto flex min-h-[100dvh] w-full max-w-content flex-col items-center px-6 pb-10 pt-6">
      <header className="relative flex w-full min-h-tap items-center justify-center">
        <ProgressDots progress={progress} />
        <button
          type="button"
          aria-label="More"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
          onClick={() => {
            setFocusAnswer(false);
            setMenuOpen(true);
          }}
          className="absolute right-0 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full text-muted hover:text-fg focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/30"
        >
          <span aria-hidden className="text-body leading-none tracking-[0.12em]">
            •••
          </span>
        </button>
      </header>

      <section className="flex w-full flex-1 flex-col items-center justify-center gap-12 py-10">
        <Orb state={orb} />
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.p
            key={question}
            initial={reduce ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? undefined : { opacity: 0 }}
            transition={{ duration: 0.35 }}
            aria-live="polite"
            data-testid="question"
            className="min-h-[3em] max-w-[30rem] text-center text-body text-fg"
          >
            {question}
          </motion.p>
        </AnimatePresence>
      </section>

      <footer className="flex w-full flex-col items-center gap-4">
        {done ? (
          <Button onClick={() => router.push(`/report/${encodeURIComponent(id)}`)}>See your report</Button>
        ) : (
          <MicButton recording={recorder.recording} disabled={sending} onPress={press} onRelease={release} />
        )}
        <div className="min-h-[52px]">
          {problem?.kind === "mic" ? (
            <StatusLine
              text="Microphone unavailable."
              action={{
                label: "Type instead",
                onClick: () => {
                  setFocusAnswer(true);
                  setMenuOpen(true);
                },
              }}
            />
          ) : problem?.kind === "send" ? (
            <StatusLine text="Couldn’t send your answer." action={{ label: "Try again", onClick: problem.retry }} />
          ) : !done ? (
            <p className="text-caption text-muted">{sending ? "Thinking…" : "Hold to talk, or press Space."}</p>
          ) : null}
        </div>
      </footer>

      {menuOpen && (
        <MoreMenu
          transcript={transcript}
          busy={sending}
          focusAnswer={focusAnswer}
          onSend={(text) => void send(() => api.answerText(id, text), text)}
          onEnd={end}
          onClose={() => setMenuOpen(false)}
        />
      )}
    </main>
  );
}
