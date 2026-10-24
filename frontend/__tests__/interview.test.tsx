import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { InterviewScreen } from "@/components/interview/InterviewScreen";
import { rememberSession } from "@/lib/session";
import * as fx from "@/test/fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn() }),
}));

class FakeRecorder {
  static instances: FakeRecorder[] = [];
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(public stream: unknown) {
    FakeRecorder.instances.push(this);
  }
  start = vi.fn(() => {
    this.state = "recording";
  });
  stop = vi.fn(() => {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["voice"], { type: "audio/webm" }) });
    this.onstop?.();
  });
}

const getUserMedia = vi.fn();

beforeEach(() => {
  push.mockReset();
  FakeRecorder.instances = [];
  getUserMedia.mockReset();
  getUserMedia.mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] });
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  rememberSession(fx.sessionStart);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const recorder = () => FakeRecorder.instances[FakeRecorder.instances.length - 1];

describe("interview screen", () => {
  it("shows the greeting as one calm line, an idle orb, the mic and progress", () => {
    render(<InterviewScreen id="s1" />);
    expect(screen.getByText(fx.sessionStart.text)).toBeInTheDocument();
    expect(screen.getByTestId("orb")).toHaveAttribute("data-state", "idle");
    expect(screen.getByRole("button", { name: "Hold to talk" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuemax", "5");
    // secondary things are hidden until "•••" is opened
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End interview" })).not.toBeInTheDocument();
  });

  it("holding the mic button records, and releasing sends the audio", async () => {
    const answer = vi.spyOn(api, "answerAudio").mockResolvedValue(fx.answerResult);
    render(<InterviewScreen id="s1" />);
    const mic = screen.getByRole("button", { name: "Hold to talk" });

    fireEvent.pointerDown(mic);
    await waitFor(() => expect(recorder()?.start).toHaveBeenCalled());
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(screen.getByTestId("orb")).toHaveAttribute("data-state", "listening");
    expect(mic).toHaveAttribute("aria-pressed", "true");

    fireEvent.pointerUp(mic);
    expect(recorder().stop).toHaveBeenCalled();
    await waitFor(() => expect(answer).toHaveBeenCalledWith("s1", expect.any(Blob)));
    expect(await screen.findByText(fx.answerResult.text)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
  });

  it("pressing and releasing Space starts and stops recording", async () => {
    const answer = vi.spyOn(api, "answerAudio").mockResolvedValue(fx.answerResult);
    render(<InterviewScreen id="s1" />);

    fireEvent.keyDown(window, { key: " ", code: "Space" });
    await waitFor(() => expect(recorder()?.start).toHaveBeenCalled());
    // key repeat must not start a second recording
    fireEvent.keyDown(window, { key: " ", code: "Space", repeat: true });
    expect(FakeRecorder.instances).toHaveLength(1);

    fireEvent.keyUp(window, { key: " ", code: "Space" });
    expect(recorder().stop).toHaveBeenCalled();
    await waitFor(() => expect(answer).toHaveBeenCalledOnce());
  });

  it("stops cleanly when released before the microphone is ready", async () => {
    let resolve: (v: unknown) => void = () => {};
    getUserMedia.mockReturnValue(new Promise((r) => (resolve = r)));
    const answer = vi.spyOn(api, "answerAudio").mockResolvedValue(fx.answerResult);
    render(<InterviewScreen id="s1" />);
    const mic = screen.getByRole("button", { name: "Hold to talk" });
    fireEvent.pointerDown(mic);
    fireEvent.pointerUp(mic);
    await act(async () => resolve({ getTracks: () => [{ stop: vi.fn() }] }));
    await waitFor(() => expect(screen.getByTestId("orb")).toHaveAttribute("data-state", "idle"));
    expect(answer).not.toHaveBeenCalled();
  });

  it("offers typing instead when the microphone is denied", async () => {
    getUserMedia.mockRejectedValue(new Error("denied"));
    const user = userEvent.setup();
    render(<InterviewScreen id="s1" />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Hold to talk" }));
    expect(await screen.findByText("Microphone unavailable.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Type instead" }));
    expect(screen.getByRole("textbox", { name: "Type your answer" })).toBeInTheDocument();
  });

  it("the ••• menu holds the transcript, the typed-answer box and End", async () => {
    const answer = vi.spyOn(api, "answerText").mockResolvedValue(fx.answerResult);
    const end = vi.spyOn(api, "endSession").mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<InterviewScreen id="s1" />);

    await user.click(screen.getByRole("button", { name: "More" }));
    const menu = screen.getByRole("dialog", { name: "More" });
    expect(within(menu).getByText(fx.sessionStart.text)).toBeInTheDocument();

    await user.type(within(menu).getByRole("textbox", { name: "Type your answer" }), "Use Redis");
    await user.click(within(menu).getByRole("button", { name: "Send" }));
    await waitFor(() => expect(answer).toHaveBeenCalledWith("s1", "Use Redis"));
    expect(await within(menu).findByText(fx.answerResult.transcript)).toBeInTheDocument();

    await user.click(within(menu).getByRole("button", { name: "End interview" }));
    await waitFor(() => expect(end).toHaveBeenCalledWith("s1"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/report/s1"));
  });

  it("closes the menu with Escape", async () => {
    const user = userEvent.setup();
    render(<InterviewScreen id="s1" />);
    await user.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("swaps the mic for a single report button when the interview is done", async () => {
    vi.spyOn(api, "answerText").mockResolvedValue({
      ...fx.answerResult,
      text: "That's all from me. Thank you!",
      state: "done",
      progress: { current: 5, total: 5 },
    });
    const user = userEvent.setup();
    render(<InterviewScreen id="s1" />);
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.type(screen.getByRole("textbox", { name: "Type your answer" }), "Done");
    await user.click(screen.getByRole("button", { name: "Send" }));
    const reportBtn = await screen.findByRole("button", { name: "See your report" });
    expect(screen.queryByRole("button", { name: "Hold to talk" })).not.toBeInTheDocument();
    await user.click(reportBtn);
    expect(push).toHaveBeenCalledWith("/report/s1");
  });

  it("shows one calm line with a retry when sending fails", async () => {
    const answer = vi
      .spyOn(api, "answerAudio")
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(fx.answerResult);
    const user = userEvent.setup();
    render(<InterviewScreen id="s1" />);
    const mic = screen.getByRole("button", { name: "Hold to talk" });
    fireEvent.pointerDown(mic);
    await waitFor(() => expect(recorder()?.start).toHaveBeenCalled());
    fireEvent.pointerUp(mic);
    expect(await screen.findByText("Couldn’t send your answer.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(answer).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(fx.answerResult.text)).toBeInTheDocument();
  });
});
