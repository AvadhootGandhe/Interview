/**
 * Every backend call lives here, typed, so response shapes can be adjusted in
 * one place. Shapes mirror backend/app/api/{catalog,sessions}.py.
 */

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

export const DEFAULT_TOTAL = 5;

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

export interface ReplyMessage {
  kind: "greeting" | "ask" | "follow_up" | "closing" | (string & {});
  text: string;
}

export interface EvaluationSummary {
  satisfaction: number;
  missing_points: string[];
  mentioned_terms: string[];
}

/** POST /sessions, /sessions/{id}/answer and /sessions/{id}/end all answer with this. */
export interface SessionReply {
  session_id: string;
  text: string;
  kind: "ask" | "follow_up" | "closing" | (string & {});
  state: "asking" | "done" | (string & {});
  done: boolean;
  /** 0-based index of the current question. */
  question_index: number;
  total_questions: number;
  messages: ReplyMessage[];
  /** The whole reply as one clip. */
  audio_url?: string | null;
  /** One clip per sentence, in speaking order (time to first audio). Empty/absent: use audio_url. */
  audio_urls?: string[] | null;
  evaluation?: EvaluationSummary | null;
  /** What the candidate said, when the answer was spoken (speech-to-text). */
  transcript?: string | null;
}

export interface ThreadTurn {
  role: "interviewer" | "candidate" | (string & {});
  text: string;
}

export interface ReportQuestion {
  question_id: string;
  topic: string;
  text: string;
  final_score: number;
  follow_ups: number;
  thread: ThreadTurn[];
  missing_points: string[];
}

/** GET /sessions/{id}/report */
export interface Report {
  overall_score: number;
  verdict: string;
  strengths: string[];
  gaps: string[];
  questions: ReportQuestion[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    let code: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : detail;
      code = typeof body?.code === "string" ? body.code : undefined;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`, code);
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

export function progressOf(r: Pick<SessionReply, "question_index" | "total_questions">): Progress {
  return { current: r.question_index + 1, total: Math.max(1, r.total_questions || DEFAULT_TOTAL) };
}

/** The one calm line to show: the last thing the interviewer said. */
export function lineOf(r: SessionReply): string {
  return r.messages.length ? r.messages[r.messages.length - 1].text : r.text;
}

/** The interviewer's turns in a reply, for the transcript. */
export function turnsOf(r: SessionReply): ThreadTurn[] {
  const texts = r.messages.length ? r.messages.map((m) => m.text) : r.text ? [r.text] : [];
  return texts.map((text) => ({ role: "interviewer", text }));
}

const sid = encodeURIComponent;

export const api = {
  companies: (q: string) => request<string[]>(`/catalog/companies?q=${encodeURIComponent(q)}`),
  profiles: () => request<string[]>("/catalog/profiles"),
  levels: () => request<string[]>("/catalog/levels"),
  topics: (profile?: string) =>
    request<string[]>(`/catalog/topics${profile ? `?profile=${encodeURIComponent(profile)}` : ""}`),

  createSession: (setup: SessionSetup) => request<SessionReply>("/sessions", json(setup)),

  answerText: (id: string, text: string) => request<SessionReply>(`/sessions/${sid(id)}/answer`, json({ text })),

  answerAudio: (id: string, audio: Blob) => {
    const form = new FormData();
    const ext = audio.type.includes("mp4") ? "m4a" : audio.type.includes("ogg") ? "ogg" : "webm";
    form.append("audio", audio, `answer.${ext}`);
    return request<SessionReply>(`/sessions/${sid(id)}/answer`, { method: "POST", body: form });
  },

  endSession: (id: string) => request<SessionReply>(`/sessions/${sid(id)}/end`, { method: "POST" }),

  report: (id: string) => request<Report>(`/sessions/${sid(id)}/report`),
};

/** Resolve a (possibly relative) audio URL from the API against its base. */
export function audioSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  return /^https?:\/\//.test(url) ? url : `${API_URL}${url.startsWith("/") ? "" : "/"}${url}`;
}
