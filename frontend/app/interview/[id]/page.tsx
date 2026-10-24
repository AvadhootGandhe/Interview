"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo } from "react";
import InterviewScreen from "@/components/InterviewScreen";
import { sessionApi, type Created } from "@/lib/api";

export default function InterviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const initial = useMemo<Created | null>(() => {
    try { return JSON.parse(sessionStorage.getItem(`session:${id}`) ?? "null"); } catch { return null; }
  }, [id]);

  if (!initial) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4">
        <p className="text-muted">This interview isn&apos;t available on this device.</p>
        <Link href="/" className="text-accent">Start a new one</Link>
      </main>
    );
  }
  return <InterviewScreen api={sessionApi} sessionId={id} initial={initial} onDone={() => router.push(`/report/${id}`)} />;
}
