import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

// `npm run e2e:voice`: the voice path with a fake microphone, real Whisper STT and real Kokoro TTS (FAKE_LLM=1).
// Needs the Mac speech stack (backend/requirements-local.txt + cached models); kept out of `npm run e2e`.
const API_PORT = 8101;
const WEB_PORT = 3101;
const WEB = `http://localhost:${WEB_PORT}`;
const wav = (name: string) => path.join(__dirname, "e2e", "fixtures", name);

const withMic = (file: string) => ({
  ...devices["Desktop Chrome"],
  viewport: { width: 1440, height: 900 },
  colorScheme: "light" as const,
  permissions: ["microphone"],
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${wav(file)}`,
      // Real-browser autoplay rules: audio may only start after a user gesture.
      "--autoplay-policy=document-user-activation-required",
    ],
  },
});

export default defineConfig({
  testDir: "./e2e/voice",
  testMatch: /.*\.spec\.ts/,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: WEB, trace: "retain-on-failure" },
  projects: [
    { name: "voice-speech", testMatch: /speech\.spec\.ts/, use: withMic("answer.wav") },
    { name: "voice-silence", testMatch: /silence\.spec\.ts/, use: withMic("silence.wav") },
  ],
  webServer: [
    {
      command: "bash e2e/start-backend.sh",
      url: `http://localhost:${API_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { E2E_API_PORT: String(API_PORT), E2E_WEB_ORIGIN: WEB, E2E_SPEECH: "real" },
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
