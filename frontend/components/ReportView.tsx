"use client";
import Link from "next/link";
import { useState } from "react";
import Card from "@/components/ui/Card";
import type { Report } from "@/lib/types";

function ScoreRing({ score }: { score: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative h-36 w-36">
      <svg viewBox="0 0 120 120" className="-rotate-90" aria-hidden>
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--hairline)" strokeWidth="8" />
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--accent)" strokeWidth="8" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-4xl font-semibold">{score}</span>
    </div>
  );
}

export default function ReportView({ report }: { report: Report }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <main className="mx-auto flex max-w-xl flex-col items-center gap-10 px-4 py-12">
      <ScoreRing score={report.overall_score} />
      <p className="text-center text-2xl font-medium leading-snug tracking-tight">{report.verdict}</p>

      <div className="grid w-full gap-4 sm:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-[13px] font-medium uppercase tracking-wide text-muted">Strengths</h2>
          <ul className="space-y-1 text-[15px]">{report.strengths.map((s) => <li key={s}>{s}</li>)}</ul>
        </Card>
        <Card>
          <h2 className="mb-2 text-[13px] font-medium uppercase tracking-wide text-muted">To work on</h2>
          <ul className="space-y-1 text-[15px]">{report.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        </Card>
      </div>

      <section className="w-full space-y-3">
        {report.questions.map((q) => (
          <Card key={q.index} className="p-0">
            <button type="button" aria-expanded={open === q.index} onClick={() => setOpen(open === q.index ? null : q.index)}
              className="flex w-full items-center justify-between px-5 py-4 text-left">
              <span className="text-[17px] font-medium">{q.topic}</span>
              <span className="text-[17px] text-muted">{q.score}</span>
            </button>
            {open === q.index && (
              <div className="space-y-3 border-t border-hairline px-5 py-4 text-[15px]">
                {q.thread.map((t, i) => (
                  <p key={i}><span className="text-muted">{t.role === "candidate" ? "You" : "Interviewer"}: </span>{t.text}</p>
                ))}
                {q.followups > 0 && <p className="text-muted">{q.followups} follow-up{q.followups > 1 ? "s" : ""}</p>}
              </div>
            )}
          </Card>
        ))}
      </section>

      <Link href="/" className="rounded-full bg-accent px-7 py-3 text-[17px] font-medium text-white hover:opacity-90">Practice again</Link>
    </main>
  );
}
