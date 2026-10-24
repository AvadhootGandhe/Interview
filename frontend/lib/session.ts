import type { SessionReply } from "./api";

// Hand-off of the greeting from the setup screen to /interview/[id].
// Server state lives in the backend; this is only a per-tab convenience,
// so every access is guarded and the screen still works without it.
const key = (id: string) => `interview:session:${id}`;

export function rememberSession(start: SessionReply): void {
  try {
    window.sessionStorage.setItem(key(start.session_id), JSON.stringify(start));
  } catch {
    /* storage unavailable */
  }
}

export function recallSession(id: string): SessionReply | null {
  try {
    const raw = window.sessionStorage.getItem(key(id));
    return raw ? (JSON.parse(raw) as SessionReply) : null;
  } catch {
    return null;
  }
}
