import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8100;
const WEB_PORT = 3100;
const WEB = `http://localhost:${WEB_PORT}`;

const desktop = { viewport: { width: 1440, height: 900 } };
const phone = { ...devices["iPhone 13"], viewport: { width: 390, height: 844 }, defaultBrowserType: "chromium" as const };

// One real run of the whole interview per project; each also saves its screenshots
// (light/dark x 1440/390) to e2e/screenshots/ (git-ignored).
export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  testIgnore: /voice\//, // needs Whisper/Kokoro: npm run e2e:voice
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: WEB, trace: "retain-on-failure" },
  projects: [
    { name: "desktop-light", use: { ...devices["Desktop Chrome"], ...desktop, colorScheme: "light" } },
    { name: "desktop-dark", use: { ...devices["Desktop Chrome"], ...desktop, colorScheme: "dark" } },
    { name: "mobile-light", use: { ...phone, colorScheme: "light" } },
    { name: "mobile-dark", use: { ...phone, colorScheme: "dark" } },
  ],
  webServer: [
    {
      command: "bash e2e/start-backend.sh",
      url: `http://localhost:${API_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { E2E_API_PORT: String(API_PORT), E2E_WEB_ORIGIN: WEB },
    },
    {
      command: `npx next dev -p ${WEB_PORT}`,
      url: WEB,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { NEXT_PUBLIC_API_URL: `http://localhost:${API_PORT}` },
    },
  ],
});
