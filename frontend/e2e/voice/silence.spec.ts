import { expect, test } from "@playwright/test";
import { hold, orbLog, resetOrb, startInterview } from "./helpers";

// The fake microphone plays e2e/fixtures/silence.wav: the backend must answer no_speech and the UI stays calm.
test("a silent recording shows one calm line and does not advance", async ({ page }) => {
  await startInterview(page);
  const progress = page.getByRole("progressbar");
  await expect(progress).toHaveAttribute("aria-valuenow", "1");
  const question = (await page.getByTestId("question").last().textContent()) ?? "";
  await resetOrb(page);
  const res = page.waitForResponse((r) => r.url().includes("/answer"));

  await hold(page, "pointer", 2_500);

  const reply = await res;
  expect(reply.status()).toBe(422);
  expect((await reply.json()).code).toBe("no_speech");
  await expect(page.getByRole("status")).toContainText(/didn.t catch that/i);
  await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(0);
  await expect(progress).toHaveAttribute("aria-valuenow", "1");
  await expect(page.getByTestId("question").last()).toHaveText(question);
  await expect(page.getByTestId("orb")).toHaveAttribute("data-state", "idle");
  expect(await orbLog(page)).not.toContain("speaking");
  await expect(page.getByRole("button", { name: "Hold to talk" })).toBeEnabled();

  await page.getByRole("button", { name: "More" }).click();
  await expect(page.getByRole("dialog", { name: "More" })).not.toContainText(/queue|backoff/i);
});
