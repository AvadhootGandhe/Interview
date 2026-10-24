import { expect, test } from "@playwright/test";
import { audioLog, hold, isSubsequence, orbLog, resetOrb, startInterview } from "./helpers";

// G1 voice path in a real browser: the fake microphone plays e2e/fixtures/answer.wav ("I would use a message queue
// with retries and backoff."), real mlx-whisper transcribes it, the FAKE_LLM interviewer replies, real Kokoro speaks.
test("hold to talk (pointer, then Space): audio reaches the backend, the interviewer replies aloud", async ({ page }) => {
  await startInterview(page);

  for (const how of ["pointer", "space"] as const) {
    const audioBefore = (await audioLog(page)).length;
    await resetOrb(page);
    const req = page.waitForRequest((r) => r.url().includes("/answer") && r.method() === "POST");
    const res = page.waitForResponse((r) => r.url().includes("/answer"));

    await hold(page, how, 4_000);

    // The backend received multipart audio and transcribed it.
    const request = await req;
    expect(request.headers()["content-type"]).toMatch(/^multipart\/form-data/);
    const sent = Number((await request.allHeaders())["content-length"] ?? 0);
    expect(sent, "uploaded bytes").toBeGreaterThan(2_000);
    const body = await (await res).json();
    expect(body.transcript, `transcript (${how})`).toMatch(/queue|retries|backoff|message/i);

    // The interviewer reply is spoken: a new /audio/ clip starts playing.
    await expect
      .poll(async () => (await audioLog(page)).slice(audioBefore).find((a) => a.src.includes("/audio/") && a.playing), { timeout: 30_000 })
      .toBeTruthy();
    // ... and finishes; the orb returns to idle.
    await expect(page.getByTestId("orb")).toHaveAttribute("data-state", "idle", { timeout: 60_000 });
    const orb = await orbLog(page);
    expect(isSubsequence(["listening", "thinking", "speaking", "idle"], orb), orb.join(">")).toBe(true);
    expect((await audioLog(page)).slice(audioBefore).some((a) => a.error)).toBe(false);

    // The transcript (••• menu) shows what was heard.
    await page.getByRole("button", { name: "More" }).click();
    await expect(page.getByRole("dialog", { name: "More" })).toContainText(/queue|retries|backoff/i);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
});
