import type { CatalogApi, Report, SessionApi, Turn } from "@/lib/types";

const BASE = "/api";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json() as Promise<T>;
}

const get = <T>(path: string) => fetch(`${BASE}${path}`).then((r) => json<T>(r));
const post = <T>(path: string, body?: unknown) =>
  fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => json<T>(r));

export const catalogApi: CatalogApi = {
  profiles: () => get("/catalog/profiles"),
  levels: () => get("/catalog/levels"),
  companies: (q) => get(`/catalog/companies?q=${encodeURIComponent(q)}`),
  topics: (profile, company) =>
    get(`/catalog/topics?profile=${encodeURIComponent(profile)}${company ? `&company=${encodeURIComponent(company)}` : ""}`),
};

export const sessionApi: SessionApi = {
  sendText: (id, text) => post<Turn>(`/sessions/${id}/answer`, { text }),
  sendAudio: (id, audio) => {
    const form = new FormData();
    form.append("audio", audio, "answer.webm");
    return fetch(`${BASE}/sessions/${id}/audio`, { method: "POST", body: form }).then((r) => json<Turn>(r));
  },
  end: (id) => post<Turn>(`/sessions/${id}/end`),
};

export type Created = { session_id: string; messages: string[]; audio_urls: string[] };
export const createSession = (selection: object) => post<Created>("/sessions", selection);
export const getReport = (id: string) => get<Report>(`/sessions/${id}/report`);
