import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "@/lib/api";
import { InterviewScreen } from "@/components/interview/InterviewScreen";
import { pickMimeType } from "@/lib/useRecorder";
import { rememberSession } from "@/lib/session";
import * as fx from "@/test/fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

const stopTrack = vi.fn();
const getUserMedia = vi.fn();
let supported: string[] = [];
let ctorArgs: unknown[][] = [];
let ctorThrows = false;

class FakeRecorder {
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  static isTypeSupported = (t: string) => supported.includes(t);
  constructor(s: unknown, opts?: { mimeType?: string }) {
    ctorArgs.push([s, opts]);
    if (ctorThrows) throw new Error("nope");
    this.mimeType = opts?.mimeType ?? "audio/webm";
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["v"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

beforeEach(() => {
  supported = [];
  ctorArgs = [];
  ctorThrows = false;
  stopTrack.mockReset();
  getUserMedia.mockReset();
  getUserMedia.mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
  rememberSession(fx.sessionStart);
});

afterEach(() => vi.unstubAllGlobals());

async function holdAndRelease() {
  const mic = screen.getByRole("button", { name: "Hold to talk" });
  fireEvent.pointerDown(mic);
  await waitFor(() => expect(ctorArgs.length).toBeGreaterThan(0));
  fireEvent.pointerUp(mic);
}

describe("pickMimeType", () => {
  it("prefers webm/opus, then webm, then mp4 (Safari), else the browser default", () => {
    supported = ["audio/mp4", "audio/webm"];
    expect(pickMimeType()).toBe("audio/webm");
    supported = ["audio/mp4"];
    expect(pickMimeType()).toBe("audio/mp4");
    supported = ["audio/webm;codecs=opus", "audio/webm"];
    expect(pickMimeType()).toBe("audio/webm;codecs=opus");
    supported = [];
    expect(pickMimeType()).toBeUndefined();
  });
});

describe("recording robustness", () => {
  it("records with the first supported mime type", async () => {
    supported = ["audio/mp4"];
    vi.spyOn(api, "answerAudio").mockResolvedValue(fx.answerReply);
    render(<InterviewScreen id="s1" />);
    await holdAndRelease();
    expect(ctorArgs[0][1]).toEqual({ mimeType: "audio/mp4" });
  });

  it("releases the microphone when the recorder cannot be created", async () => {
    ctorThrows = true;
    render(<InterviewScreen id="s1" />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Hold to talk" }));
    expect(await screen.findByText(/Microphone/)).toBeInTheDocument();
    expect(stopTrack).toHaveBeenCalled();
    expect(screen.getByTestId("orb")).toHaveAttribute("data-state", "idle");
  });

  it("stops the microphone tracks after a recording", async () => {
    vi.spyOn(api, "answerAudio").mockResolvedValue(fx.answerReply);
    render(<InterviewScreen id="s1" />);
    await holdAndRelease();
    await waitFor(() => expect(stopTrack).toHaveBeenCalled());
  });

  it("says the microphone is off, with one action, when permission is denied", async () => {
    getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    render(<InterviewScreen id="s1" />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Hold to talk" }));
    expect(await screen.findByText("Microphone access is off.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Type instead" })).toHaveLength(1);
  });
});

describe("voice errors from the server", () => {
  it("shows the calm no-speech message with no retry button, and stays on the question", async () => {
    vi.spyOn(api, "answerAudio").mockRejectedValue(
      new ApiError(422, "I didn’t catch that. Could you say it again?", "no_speech"),
    );
    render(<InterviewScreen id="s1" />);
    await holdAndRelease();
    expect(await screen.findByText("I didn’t catch that. Could you say it again?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByRole("button", { name: "Hold to talk" })).toBeEnabled();
  });

  it("offers typing when speech is unavailable on the server", async () => {
    vi.spyOn(api, "answerAudio").mockRejectedValue(
      new ApiError(503, "Voice answers are not available. Please type your answer.", "speech_unavailable"),
    );
    render(<InterviewScreen id="s1" />);
    await holdAndRelease();
    expect(await screen.findByText(/not available/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Type instead" })).toBeInTheDocument();
  });
});

describe("autoplay policy", () => {
  it("offers one Play action when the browser blocks the interviewer audio, and plays it on the tap", async () => {
    const play = vi.fn().mockRejectedValueOnce(new DOMException("blocked", "NotAllowedError")).mockResolvedValue(undefined);
    class FakeAudio {
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      play = play;
      pause = vi.fn();
      constructor(public src: string) {}
    }
    vi.stubGlobal("Audio", FakeAudio);
    rememberSession({ ...fx.sessionStart, audio_url: "/audio/a.wav" });
    const user = userEvent.setup();
    render(<InterviewScreen id="s1" />);
    const btn = await screen.findByRole("button", { name: "Play" });
    expect(screen.getByTestId("orb")).toHaveAttribute("data-state", "idle");
    await user.click(btn);
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("orb")).toHaveAttribute("data-state", "speaking");
    expect(screen.queryByRole("button", { name: "Play" })).not.toBeInTheDocument();
  });
});
