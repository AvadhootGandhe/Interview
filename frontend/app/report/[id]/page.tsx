"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import ReportView from "@/components/ReportView";
import { getReport } from "@/lib/api";
import type { Report } from "@/lib/types";

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => { getReport(id).then(setReport).catch(() => setFailed(true)); }, [id]);

  if (failed) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4">
        <p className="text-muted">We couldn&apos;t load this report.</p>
        <Link href="/" className="text-accent">Practice again</Link>
      </main>
    );
  }
  return report ? <ReportView report={report} /> : <main className="flex min-h-screen items-center justify-center text-muted">Preparing your report…</main>;
}
