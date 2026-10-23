import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto grid min-h-[100dvh] w-full max-w-content place-items-center px-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <p className="text-body text-muted">This page doesn’t exist.</p>
        <Link href="/" className="inline-flex min-h-tap items-center rounded-full px-4 text-body text-accent">
          Start over
        </Link>
      </div>
    </main>
  );
}
