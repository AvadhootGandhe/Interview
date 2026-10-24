"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import SetupFlow from "@/components/SetupFlow";
import { catalogApi, createSession } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(false);

  async function start(selection: object) {
    setStarting(true);
    setError(false);
    try {
      const session = await createSession(selection);
      try { sessionStorage.setItem(`session:${session.session_id}`, JSON.stringify(session)); } catch {}
      router.push(`/interview/${session.session_id}`);
    } catch {
      setError(true);
      setStarting(false);
    }
  }

  return (
    <>
      <SetupFlow api={catalogApi} onStart={start} starting={starting} />
      {error && <p role="alert" className="pb-8 text-center text-[15px] text-muted">Something went wrong. Please try again.</p>}
    </>
  );
}
