import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InterviewScreen } from "@/components/interview/InterviewScreen";
import { rememberSession } from "@/lib/session";
import * as fx from "@/test/fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

class FakeAudio {
  static all: FakeAudio[] = [];
  static playImpl: (a: FakeAudio) => Promise<void> = () => Promise.resolve();
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  preload = "";
  paused = true;
  pause = vi.fn(() => {
    this.paused = true;
  });
  play = vi.fn(() => {
    this.paused = false;
    return FakeAudio.playImpl(this);
  });
  constructor(public src: string) {
    FakeAudio.all.push(this);
  }
  end() {
    act(() => this.onended?.());
  }
  fail() {
    act(() => this.onerror?.());
  }
}
const clip = (n: number) => FakeAudio.all.find((a) => a.src.endsWith(`/audio/${n}.wav`))!;
const played = () => FakeAudio.all.filter((a) => a.play.mock.calls.length > 0).map((a) => a.src.split("/audio/")[1]);
const orb = () => screen.getByTestId("orb");

function start(extra: Partial<typeof fx.sessionStart>) {
  rememberSession({ ...fx.sessionStart, ...extra });
}

beforeEach(() => {
  FakeAudio.all = [];
  FakeAudio.playImpl = () => Promise.resolve();
  vi.stubGlobal("Audio", FakeAudio);
});
afterEach(() => vi.unstubAllGlobals());

describe("per-sentence clips", () => {
  it("plays audio_urls in order, one at a time, with the orb speaking until the last ends", async () => {
    start({ audio_url: "/audio/all.wav", audio_urls: ["/audio/1.wav", "/audio/2.wav", "/audio/3.wav"] });
    render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(played()).toEqual(["1.wav"]));
    expect(orb()).toHaveAttribute("data-state", "speaking");
    clip(1).end();
    await waitFor(() => expect(played()).toEqual(["1.wav", "2.wav"]));
    expect(orb()).toHaveAttribute("data-state", "speaking");
    clip(2).end();
    await waitFor(() => expect(played()).toEqual(["1.wav", "2.wav", "3.wav"]));
    expect(orb()).toHaveAttribute("data-state", "speaking");
    clip(3).end();
    await waitFor(() => expect(orb()).toHaveAttribute("data-state", "idle"));
    expect(FakeAudio.all.some((a) => a.src.endsWith("all.wav"))).toBe(false);
  });

  it("preloads the next clip while the current one plays, without playing it", async () => {
    start({ audio_urls: ["/audio/1.wav", "/audio/2.wav"] });
    render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(played()).toEqual(["1.wav"]));
    expect(clip(2)).toBeDefined();
    expect(clip(2).preload).toBe("auto");
    expect(clip(2).play).not.toHaveBeenCalled();
  });

  it("falls back to audio_url when audio_urls is missing or empty", async () => {
    start({ audio_url: "/audio/all.wav", audio_urls: [] });
    render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(FakeAudio.all.map((a) => a.src)).toEqual([expect.stringContaining("/audio/all.wav")]));
    expect(orb()).toHaveAttribute("data-state", "speaking");
  });

  it("is text-only when there is no audio at all", async () => {
    start({ audio_url: null, audio_urls: null });
    render(<InterviewScreen id="s1" />);
    expect(await screen.findByTestId("question")).not.toBeEmptyDOMElement();
    expect(FakeAudio.all).toHaveLength(0);
    expect(orb()).toHaveAttribute("data-state", "idle");
  });

  it("skips a failing clip calmly and keeps going", async () => {
    start({ audio_urls: ["/audio/1.wav", "/audio/2.wav", "/audio/3.wav"] });
    render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(played()).toEqual(["1.wav"]));
    clip(1).end();
    await waitFor(() => expect(played()).toEqual(["1.wav", "2.wav"]));
    clip(2).fail();
    await waitFor(() => expect(played()).toEqual(["1.wav", "2.wav", "3.wav"]));
    expect(orb()).toHaveAttribute("data-state", "speaking");
    expect(screen.queryByText(/Couldn’t play/)).not.toBeInTheDocument();
    clip(3).end();
    await waitFor(() => expect(orb()).toHaveAttribute("data-state", "idle"));
    expect(screen.queryByText(/Couldn’t play/)).not.toBeInTheDocument();
  });

  it("skips a clip whose play() rejects (non-autoplay error)", async () => {
    FakeAudio.playImpl = (a) => (a.src.endsWith("/1.wav") ? Promise.reject(new DOMException("x", "NotSupportedError")) : Promise.resolve());
    start({ audio_urls: ["/audio/1.wav", "/audio/2.wav"] });
    render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(played()).toEqual(["1.wav", "2.wav"]));
    expect(screen.queryByText(/Couldn’t play/)).not.toBeInTheDocument();
  });

  it("only shows a quiet message when every clip fails", async () => {
    start({ audio_urls: ["/audio/1.wav", "/audio/2.wav"] });
    render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(played()).toEqual(["1.wav"]));
    clip(1).fail();
    await waitFor(() => expect(played()).toEqual(["1.wav", "2.wav"]));
    clip(2).fail();
    expect(await screen.findByText(/Couldn’t play/)).toBeInTheDocument();
    expect(orb()).toHaveAttribute("data-state", "idle");
  });

  it("autoplay blocked: one Play tap resumes and carries on through the whole sequence", async () => {
    let first = true;
    FakeAudio.playImpl = () => {
      if (first) {
        first = false;
        return Promise.reject(new DOMException("blocked", "NotAllowedError"));
      }
      return Promise.resolve();
    };
    start({ audio_urls: ["/audio/1.wav", "/audio/2.wav"] });
    const user = userEvent.setup();
    render(<InterviewScreen id="s1" />);
    const btn = await screen.findByRole("button", { name: "Play" });
    expect(orb()).toHaveAttribute("data-state", "idle");
    await user.click(btn);
    await waitFor(() => expect(clip(1).play).toHaveBeenCalledTimes(2));
    expect(orb()).toHaveAttribute("data-state", "speaking");
    expect(screen.queryByRole("button", { name: "Play" })).not.toBeInTheDocument();
    clip(1).end();
    await waitFor(() => expect(clip(2).play).toHaveBeenCalledTimes(1));
    clip(2).end();
    await waitFor(() => expect(orb()).toHaveAttribute("data-state", "idle"));
  });

  it("autoplay blocked mid-sequence still offers Play for the remaining clips", async () => {
    FakeAudio.playImpl = (a) =>
      a.src.endsWith("/2.wav") && a.play.mock.calls.length === 1 ? Promise.reject(new DOMException("b", "NotAllowedError")) : Promise.resolve();
    start({ audio_urls: ["/audio/1.wav", "/audio/2.wav"] });
    const user = userEvent.setup();
    render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(played()).toEqual(["1.wav"]));
    clip(1).end();
    await user.click(await screen.findByRole("button", { name: "Play" }));
    await waitFor(() => expect(clip(2).play).toHaveBeenCalledTimes(2));
  });

  it("barge-in: starting to record stops the sequence for good", async () => {
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] });
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
    vi.stubGlobal(
      "MediaRecorder",
      class {
        static isTypeSupported = () => false;
        state = "inactive";
        start() {
          this.state = "recording";
        }
        stop() {}
      },
    );
    start({ audio_urls: ["/audio/1.wav", "/audio/2.wav"] });
    render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(played()).toEqual(["1.wav"]));
    fireEvent.pointerDown(screen.getByRole("button", { name: "Hold to talk" }));
    expect(clip(1).pause).toHaveBeenCalled();
    clip(1).end(); // a late event must not advance the queue
    await waitFor(() => expect(orb()).toHaveAttribute("data-state", "listening"));
    expect(played()).toEqual(["1.wav"]);
  });

  it("leaving the page stops playback", async () => {
    start({ audio_urls: ["/audio/1.wav", "/audio/2.wav"] });
    const { unmount } = render(<InterviewScreen id="s1" />);
    await waitFor(() => expect(played()).toEqual(["1.wav"]));
    unmount();
    expect(clip(1).pause).toHaveBeenCalled();
    clip(1).end();
    expect(played()).toEqual(["1.wav"]);
  });
});
