import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MicButton, { type RecorderLike } from "@/components/MicButton";

function fakeRecorder() {
  const rec: RecorderLike & { started: boolean } = {
    started: false,
    start() { rec.started = true; },
    stop() { rec.started = false; rec.onstop?.(new Blob(["audio"], { type: "audio/webm" })); },
    onstop: undefined,
  };
  return rec;
}

describe("MicButton", () => {
  it("records while held and delivers audio on release", async () => {
    const rec = fakeRecorder();
    const onRecorded = vi.fn();
    render(<MicButton onRecorded={onRecorded} createRecorder={async () => rec} />);
    const button = screen.getByRole("button", { name: /hold to answer/i });
    fireEvent.pointerDown(button);
    await waitFor(() => expect(rec.started).toBe(true));
    expect(button).toHaveAttribute("aria-pressed", "true");
    fireEvent.pointerUp(button);
    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1));
    expect(button).toHaveAttribute("aria-pressed", "false");
  });

  it("works with the Space key and ignores key repeat", async () => {
    const rec = fakeRecorder();
    const onRecorded = vi.fn();
    const create = vi.fn(async () => rec);
    render(<MicButton onRecorded={onRecorded} createRecorder={create} />);
    fireEvent.keyDown(window, { code: "Space" });
    fireEvent.keyDown(window, { code: "Space", repeat: true });
    await waitFor(() => expect(rec.started).toBe(true));
    expect(create).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(window, { code: "Space" });
    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1));
  });

  it("shows a calm message when the microphone is denied", async () => {
    const onError = vi.fn();
    render(<MicButton onRecorded={vi.fn()} onError={onError}
      createRecorder={async () => { throw new Error("denied"); }} />);
    fireEvent.pointerDown(screen.getByRole("button", { name: /hold to answer/i }));
    expect(await screen.findByText(/microphone access/i)).toBeInTheDocument();
    expect(onError).toHaveBeenCalled();
  });

  it("does nothing when disabled", () => {
    const create = vi.fn();
    render(<MicButton onRecorded={vi.fn()} createRecorder={create} disabled />);
    fireEvent.pointerDown(screen.getByRole("button", { name: /hold to answer/i }));
    expect(create).not.toHaveBeenCalled();
  });
});
