"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { api, type Report, type ReportQuestion } from "@/lib/api";
import { useLoad } from "@/lib/useLoad";
import { Card, StatusLine, buttonClasses, cx, spring } from "@/components/ui";

export function verdictFor(score: number): string {
  if (score >= 85) return "Excellent interview.";
  if (score >= 70) return "Strong interview.";
  if (score >= 50) return "A good start.";
  return "Keep practising.";
}

const clamp = (n: number) => Math.max(0, Math.min(100, Math.round(Number(n) || 0)));

function ScoreRing({ score }: { score: number }) {
  const reduce = useReducedMotion();
  const value = clamp(score);
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <div role="img" aria-label={`Overall score ${value} out of 100`} className="relative h-40 w-40">
      <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90" aria-hidden>
        <circle cx="60" cy="60" r={r} fill="none" strokeWidth="8" className="stroke-surface" />
        <motion.circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="8"
          strokeLinecap="round"
          className="stroke-accent"
          strokeDasharray={c}
          initial={reduce ? false : { strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - value / 100) }}
          transition={reduce ? { duration: 0 } : { ...spring, delay: 0.15 }}
        />
      </svg>
      <span aria-hidden className="absolute inset-0 grid place-items-center text-display text-fg">
        {value}
      </span>
    </div>
  );
}

function QuestionCard({ q }: { q: ReportQuestion }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const n = q.follow_ups;
  return (
    <Card className="p-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full min-h-tap items-start justify-between gap-4 rounded-lg p-5 text-left focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/30"
      >
        <span className="text-body text-fg">{q.text}</span>
        <span className="text-body font-medium tabular-nums text-fg">{clamp(q.final_score)}</span>
      </button>
      {open && (
        <div id={panel} className="flex flex-col gap-2 px-5 pb-5">
          {q.missing_points.map((m, i) => (
            <p key={i} className="text-body text-muted">
              {m}
            </p>
          ))}
          {n > 0 && (
            <p className="text-caption text-muted">
              {n} follow-up{n === 1 ? "" : "s"}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-body font-medium text-fg">{title}</h2>
      <ul className="flex flex-col gap-2">
        {items.map((s, i) => (
          <li key={i} className="text-body text-muted">
            {s}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ReportView({ report }: { report: Report }) {
  const [threadOpen, setThreadOpen] = useState(false);
  const thread = report.questions.flatMap((q) => q.thread);
  const threadId = useId();
  return (
    <main className="mx-auto flex w-full max-w-content flex-col gap-12 px-6 pb-16 pt-[10vh]">
      <header className="flex flex-col items-center gap-5 text-center">
        <ScoreRing score={report.overall_score} />
        <p className="text-body text-fg">{report.verdict || verdictFor(clamp(report.overall_score))}</p>
      </header>

      {report.questions.length > 0 && (
        <section className="flex flex-col gap-3" aria-label="Questions">
          {report.questions.map((q, i) => (
            <QuestionCard key={i} q={q} />
          ))}
        </section>
      )}

      <List title="Strengths" items={report.strengths} />
      <List title="To work on" items={report.gaps} />

      {thread.length > 0 && (
        <section className="flex flex-col gap-3">
          <button
            type="button"
            aria-expanded={threadOpen}
            aria-controls={threadId}
            onClick={() => setThreadOpen((o) => !o)}
            className="flex min-h-tap items-center gap-2 self-start text-body text-muted hover:text-fg focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/30 rounded-sm"
          >
            Full conversation
            <svg
              aria-hidden
              viewBox="0 0 20 20"
              className={cx("h-4 w-4 transition-transform duration-200 motion-reduce:transition-none", threadOpen && "rotate-180")}
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M5 8l5 5 5-5" />
            </svg>
          </button>
          {threadOpen && (
            <ol id={threadId} className="flex flex-col gap-3">
              {thread.map((t, i) => (
                <li key={i} className={cx("text-body", t.role === "candidate" ? "text-fg" : "text-muted")}>
                  <span className="sr-only">{t.role === "candidate" ? "You: " : "Interviewer: "}</span>
                  {t.text}
                </li>
              ))}
            </ol>
          )}
        </section>
      )}

      <div className="flex justify-center">
        <Link href="/" className={buttonClasses("primary")}>
          Practice again
        </Link>
      </div>
    </main>
  );
}

export function ReportScreen({ id }: { id: string }) {
  const report = useLoad(() => api.report(id), id);
  if (report.data) return <ReportView report={report.data} />;
  return (
    <main className="mx-auto grid min-h-[100dvh] w-full max-w-content place-items-center px-6">
      {report.error ? (
        <StatusLine text="Couldn’t load your report." action={{ label: "Try again", onClick: report.retry }} />
      ) : (
        <StatusLine text="Preparing your report…" />
      )}
    </main>
  );
}
