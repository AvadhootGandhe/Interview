import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const SHOTS = path.join(__dirname, "screenshots");

const WEAK = "I don't know.";
const STRONG =
  "I would start from the requirements, pick a simple design and measure it. The trade-off is consistency " +
  "versus latency, so I add timeouts, retries with backoff and monitoring for failures.";

async function shot(page: Page, name: string, fullPage = false) {
  await page.waitForTimeout(700); // let spring/fade animations settle
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${test.info().project.name}-${name}.png`), fullPage });
}

/** G7 mechanical checks: no horizontal scroll, every control at least 44px tall. */
async function expectCalmLayout(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "horizontal scroll").toBeLessThanOrEqual(0);
  const small = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("button, a[href], input, textarea, [role=radio]")]
      .filter((el) => el.offsetParent !== null || getComputedStyle(el).position === "fixed")
      .map((el) => ({ name: (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 30), h: el.getBoundingClientRect().height }))
      .filter((c) => c.h > 0 && c.h < 43.5),
  );
  expect(small, "controls under 44px").toEqual([]);
}

test("setup -> typed interview with a follow-up -> closing -> report", async ({ page }) => {
  // ---- Setup: role -> level -> company -> topic -> Start
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Practice your next interview." })).toBeVisible();
  await page.getByRole("button", { name: "Backend", exact: true }).click();
  await page.getByRole("radio", { name: "SDE-2/3" }).click();

  await page.getByRole("searchbox", { name: "Search companies" }).fill("ama");
  await page.getByRole("button", { name: "Amazon" }).click();

  await expect(page.getByRole("button", { name: "Any topic" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start" })).toBeDisabled();
  await page.getByRole("button", { name: "Any topic" }).click();
  await expect(page.getByRole("button", { name: "Start" })).toBeEnabled();
  await expectCalmLayout(page);
  await shot(page, "1-setup");
  await page.getByRole("button", { name: "Start" }).click();

  // ---- Interview: answer everything through the ••• typed box
  await page.waitForURL(/\/interview\//);
  const line = page.getByTestId("question").last();
  await expect(line).not.toBeEmpty();
  const progress = page.getByRole("progressbar");
  const total = Number(await progress.getAttribute("aria-valuemax"));
  expect(total).toBeGreaterThanOrEqual(4);
  await expectCalmLayout(page);
  await shot(page, "2-interview");

  await page.getByRole("button", { name: "More" }).click();
  const box = page.getByRole("textbox", { name: "Type your answer" });
  await expect(box).toBeVisible();
  await shot(page, "3-interview-menu");

  async function answer(text: string) {
    const before = await line.textContent();
    await box.fill(text);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(line).not.toHaveText(before ?? "");
  }

  // One deliberately weak answer: the interviewer must probe, not move on.
  const firstQuestion = (await line.textContent()) ?? "";
  await answer(WEAK);
  await expect(line).toContainText("Could you say more");
  await expect(progress).toHaveAttribute("aria-valuenow", "1"); // still on question 1
  await answer(STRONG); // resolves the follow-up and moves on
  await expect(line).not.toContainText("Could you say more");
  expect(await line.textContent()).not.toBe(firstQuestion);

  // The rest of the interview with strong answers until the closing.
  const report = page.getByRole("button", { name: "See your report" });
  for (let i = 0; i < total + 2 && !(await report.isVisible()); i++) {
    await answer(STRONG);
  }
  await expect(report).toBeVisible();
  await expect(page.getByRole("button", { name: "Hold to talk" })).toHaveCount(0);
  await expectCalmLayout(page);
  await shot(page, "4-closing");

  // ---- Report
  await report.click();
  await page.waitForURL(/\/report\//);
  await expect(page.getByRole("img", { name: /Overall score \d+ out of 100/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Strengths" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "To work on" })).toBeVisible();
  const cards = page.getByRole("region", { name: "Questions" }).getByRole("button");
  expect(await cards.count()).toBe(total);
  for (let i = 0; i < total; i++) {
    await expect(cards.nth(i)).toContainText(/\b\d{1,3}$/); // per-question score
  }
  await cards.first().click();
  await expect(cards.first()).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("link", { name: "Practice again" })).toBeVisible();
  await expectCalmLayout(page);
  await shot(page, "5-report", true);

  await page.getByRole("button", { name: "Full conversation" }).click();
  await expect(page.getByText("Could you say more")).toBeVisible(); // the follow-up is in the thread
});
