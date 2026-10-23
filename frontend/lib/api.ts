/**
 * Every backend call lives here, typed, so the shapes in plan.md can be
 * adjusted in one place once the FastAPI backend lands. Small `normalize*`
 * helpers accept a few likely variants (e.g. `greeting` vs `text`,
 * `["a"]` vs `[{name:"a"}]`) so the UI does not break on minor drift.
 */

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

export type SessionState = "greeting" | "asking" | "follow_up" | "closing" | "done" | (string & {});

export interface Progress {
  current: number;
  total: number;
}

export interface SessionSetup {
  profile: string;
  level: string;
  company: string | null;
  topic: string | null;
}

export interface SessionStart {
  id: string;
  /** The interviewer's greeting (backend may call it `greeting` or `text`). */
  text: string;
  audio_url?: string | null;
  progress?: Progress;
}

export interface AnswerResult {
  transcript: string;
  text: string;
  audio_url?: string | null;
  state: SessionState;
  progress: Progress;
}

export interface ReportQuestion {
  question: string;
  score: number;
  /** Number of follow-ups needed, or the follow-up questions themselves. */
  followups: number | string[];
  feedback: string;
}

export interface ThreadTurn {
  role: "interviewer" | "candidate";
  text: string;
}

export interface Report {
  overall: number;
  verdict?: string;
  questions: ReportQuestion[];
  strengths: string[];
  gaps: string[];
  thread: ThreadTurn[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const DEFAULT_TOTAL = 5;

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function normalizeNames(data: unknown): string[] {
  const list = Array.isArray(data)
    ? data
    : data && typeof data === "object" && Array.isArray((data as { items?: unknown }).items)
      ? (data as { items: unknown[] }).items
      : [];
  return list
    .map((x) => (typeof x === "string" ? x : x && typeof x === "object" ? (x as { name?: unknown }).name : null))
    .filter((x): x is string => typeof x === "string" && x.length > 0);
}

export function normalizeProgress(p: unknown, fallbackTotal = DEFAULT_TOTAL): Progress {
  if (typeof p === "number") return { current: p, total: fallbackTotal };
  if (p && typeof p === "object") {
    const o = p as Partial<Progress>;
    return { current: Number(o.current ?? 0), total: Number(o.total ?? fallbackTotal) };
  }
  return { current: 0, total: fallbackTotal };
}

function normalizeStart(raw: Record<string, unknown>): SessionStart {
  const out: SessionStart = {
    id: String(raw.id),
    text: String(raw.greeting ?? raw.text ?? ""),
    audio_url: (raw.audio_url as string | null | undefined) ?? null,
  };
  if (raw.progress !== undefined) out.progress = normalizeProgress(raw.progress);
  return out;
}

function normalizeAnswer(raw: Record<string, unknown>): AnswerResult {
  return {
    transcript: String(raw.transcript ?? ""),
    text: String(raw.text ?? ""),
    audio_url: (raw.audio_url as string | null | undefined) ?? null,
    state: String(raw.state ?? "asking"),
    progress: normalizeProgress(raw.progress),
  };
}

export const api = {
  companies: async (q: string) => normalizeNames(await request(`/catalog/companies?q=${encodeURIComponent(q)}`)),
  profiles: async () => normalizeNames(await request("/catalog/profiles")),
  levels: async () => normalizeNames(await request("/catalog/levels")),
  topics: async (profile?: string) =>
    normalizeNames(
      await request(`/catalog/topics${profile ? `?profile=${encodeURIComponent(profile)}` : ""}`),
    ),

  createSession: async (setup: SessionSetup) =>
    normalizeStart(await request<Record<string, unknown>>("/sessions", json(setup))),

  answerText: async (id: string, text: string) =>
    normalizeAnswer(
      await request<Record<string, unknown>>(`/sessions/${encodeURIComponent(id)}/answer`, json({ text })),
    ),

  answerAudio: async (id: string, audio: Blob) => {
    const form = new FormData();
    const ext = audio.type.includes("mp4") ? "m4a" : audio.type.includes("ogg") ? "ogg" : "webm";
    form.append("audio", audio, `answer.${ext}`);
    return normalizeAnswer(
      await request<Record<string, unknown>>(`/sessions/${encodeURIComponent(id)}/answer`, {
        method: "POST",
        body: form,
      }),
    );
  },

  endSession: async (id: string): Promise<void> => {
    await request(`/sessions/${encodeURIComponent(id)}/end`, { method: "POST" });
  },

  report: (id: string) => request<Report>(`/sessions/${encodeURIComponent(id)}/report`),
};

/** Resolve a (possibly relative) audio URL from the API against its base. */
export function audioSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  return /^https?:\/\//.test(url) ? url : `${API_URL}${url.startsWith("/") ? "" : "/"}${url}`;
}
