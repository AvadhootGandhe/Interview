import { expect, type Page } from "@playwright/test";

type AudioEntry = { src: string; playing: boolean; ended: boolean; error: boolean };

/**
 * Observation hooks installed before the app loads (headless Chromium has no speakers, so we watch the
 * media element and the orb instead of listening):
 *  - window.__audio: one entry per HTMLMediaElement.play() call, with the src and events seen.
 *  - window.__orb: every distinct orb data-state, in order.
 */
export async function installProbes(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __audio: AudioEntry[]; __orb: string[] };
    w.__audio = [];
    w.__orb = [];
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
      const entry: AudioEntry = { src: this.currentSrc || this.src, playing: false, ended: false, error: false };
      w.__audio.push(entry);
      this.addEventListener("playing", () => (entry.playing = true));
      this.addEventListener("ended", () => (entry.ended = true));
      this.addEventListener("error", () => (entry.error = true));
      return play.call(this);
    };
    const note = () => {
      const s = document.querySelector('[data-testid="orb"]')?.getAttribute("data-state");
      if (s && w.__orb[w.__orb.length - 1] !== s) w.__orb.push(s);
    };
    new MutationObserver(note).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-state"] });
  });
}

export const audioLog = (page: Page) => page.evaluate(() => (window as unknown as { __audio: AudioEntry[] }).__audio);
export const orbLog = (page: Page) => page.evaluate(() => (window as unknown as { __orb: string[] }).__orb);
export const resetOrb = (page: Page) => page.evaluate(() => ((window as unknown as { __orb: string[] }).__orb.length = 0));

/** Setup screen -> Start -> interview screen, and wait for the interviewer's greeting to finish playing. */
export async function startInterview(page: Page) {
  await installProbes(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Backend", exact: true }).click();
  await page.getByRole("radio", { name: "SDE-2/3" }).click();
  await page.getByRole("searchbox", { name: "Search companies" }).fill("ama");
  await page.getByRole("button", { name: "Amazon" }).click();
  await page.getByRole("button", { name: "Any topic" }).click();
  await page.getByRole("button", { name: "Start" }).click();
  await page.waitForURL(/\/interview\//);
  await expect(page.getByTestId("question").last()).not.toBeEmpty();
  // The greeting is spoken: an /audio/ clip is requested, and the orb settles back to idle when it ends.
  await expect.poll(async () => (await audioLog(page)).some((a) => a.src.includes("/audio/")), { timeout: 30_000 }).toBe(true);
  await expect(page.getByTestId("orb")).toHaveAttribute("data-state", "idle", { timeout: 60_000 });
}

/** Holds the mic (pointer or Space) for `ms`, then releases. */
export async function hold(page: Page, how: "pointer" | "space", ms: number) {
  if (how === "pointer") {
    const box = (await page.getByRole("button", { name: "Hold to talk" }).boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await expect(page.getByTestId("orb")).toHaveAttribute("data-state", "listening");
    await page.waitForTimeout(ms);
    await page.mouse.up();
  } else {
    await page.keyboard.down("Space");
    await expect(page.getByTestId("orb")).toHaveAttribute("data-state", "listening");
    await page.waitForTimeout(ms);
    await page.keyboard.up("Space");
  }
}

export function isSubsequence(want: string[], got: string[]) {
  let i = 0;
  for (const g of got) if (g === want[i]) i++;
  return i === want.length;
}
