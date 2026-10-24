import { describe, expect, it, vi, beforeEach } from "vitest";
import { API_URL, ApiError, api, audioSrc, lineOf, progressOf, turnsOf } from "@/lib/api";
import * as fx from "@/test/fixtures";

function mockFetch(body: unknown, init: { status?: number } = {}) {
  const fn = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status: init.status ?? 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("lib/api", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults the base URL to localhost:8000", () => {
    expect(API_URL).toBe("http://localhost:8000");
  });

  it("searches companies with an encoded query (the API returns plain names)", async () => {
    const fetch = mockFetch(["Amazon", "Apple"]);
    const out = await api.companies("am az");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/catalog/companies?q=am%20az",
      expect.anything(),
    );
    expect(out).toEqual(["Amazon", "Apple"]);
  });

  it("lists profiles, levels and topics", async () => {
    const fetch = mockFetch(["Backend"]);
    expect(await api.profiles()).toEqual(["Backend"]);
    await api.levels();
    await api.topics("Backend");
    const urls = fetch.mock.calls.map((c) => (c as unknown[])[0]);
    expect(urls).toEqual([
      "http://localhost:8000/catalog/profiles",
      "http://localhost:8000/catalog/levels",
      "http://localhost:8000/catalog/topics?profile=Backend",
    ]);
  });

  it("creates a session with JSON and returns the real reply shape", async () => {
    const fetch = mockFetch(fx.sessionStart);
    const out = await api.createSession({ profile: "Backend", level: "SDE-1", company: null, topic: null });
    expect(out.session_id).toBe("s1");
    expect(out.messages).toHaveLength(2);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/sessions");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      profile: "Backend",
      level: "SDE-1",
      company: null,
      topic: null,
    });
  });

  it("sends a typed answer as JSON", async () => {
    const fetch = mockFetch(fx.answerReply);
    const out = await api.answerText("s1", "hi");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/sessions/s1/answer");
    expect(JSON.parse(init.body as string)).toEqual({ text: "hi" });
    expect(out.kind).toBe("follow_up");
  });

  it("sends a recorded answer as multipart audio", async () => {
    const fetch = mockFetch(fx.answerReply);
    await api.answerAudio("s1", new Blob(["x"], { type: "audio/webm" }));
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("audio")).toBeInstanceOf(Blob);
  });

  it("derives progress, the spoken line and turns from a reply", () => {
    expect(progressOf(fx.sessionStart)).toEqual({ current: 1, total: 5 });
    expect(progressOf(fx.answerReply)).toEqual({ current: 2, total: 5 });
    expect(lineOf(fx.sessionStart)).toBe("How would you design a cache for a read-heavy API?");
    expect(lineOf({ ...fx.answerReply, messages: [] })).toBe(fx.answerReply.text);
    expect(turnsOf(fx.sessionStart).map((t) => t.role)).toEqual(["interviewer", "interviewer"]);
  });

  it("ends a session and fetches the report", async () => {
    const fetch = mockFetch(fx.report);
    await api.endSession("s1");
    const report = await api.report("s1");
    const urls = fetch.mock.calls.map((c) => (c as unknown[])[0]);
    expect(urls).toEqual([
      "http://localhost:8000/sessions/s1/end",
      "http://localhost:8000/sessions/s1/report",
    ]);
    expect(report.overall_score).toBe(78);
  });

  it("throws ApiError on a non-2xx response", async () => {
    mockFetch({ detail: "nope" }, { status: 503 });
    await expect(api.profiles()).rejects.toBeInstanceOf(ApiError);
  });

  it("resolves relative audio URLs against the API", () => {
    expect(audioSrc("/audio/a.wav")).toBe("http://localhost:8000/audio/a.wav");
    expect(audioSrc("https://x.test/a.wav")).toBe("https://x.test/a.wav");
    expect(audioSrc(null)).toBeNull();
  });
});
