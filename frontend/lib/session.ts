import type { SessionStart } from "./api";

// Hand-off of the greeting from the setup screen to /interview/[id].
// Server state lives in the backend; this is only a per-tab convenience,
// so every access is guarded and the screen still works without it.
const key = (id: string) => `interview:session:${id}`;

export function rememberSession(start: SessionStart): void {
  try {
    window.sessionStorage.setItem(key(start.id), JSON.stringify(start));
  } catch {
    /* storage unavailable */
  }
}

export function recallSession(id: string): SessionStart | null {
  try {
    const raw = window.sessionStorage.getItem(key(id));
    return raw ? (JSON.parse(raw) as SessionStart) : null;
  } catch {
    return null;
  }
}
