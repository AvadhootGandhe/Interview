import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import InterviewScreen from "@/components/InterviewScreen";
import type { SessionApi, Turn } from "@/lib/types";

const turn = (over: Partial<Turn> = {}): Turn => ({ messages: ["Next question?"], kind: "ask", state: "active", audio_urls: [], ...over });

function setup(over: Partial<SessionApi> = {}, onDone = vi.fn()) {
  const api: SessionApi = {
    sendText: vi.fn(async () => turn()),
    sendAudio: vi.fn(async () => turn()),
    end: vi.fn(async () => turn({ kind: "closing", state: "done", messages: ["Thanks!"] })),
    ...over,
  };
  render(<InterviewScreen api={api} sessionId="s1" initial={{ messages: ["Hello.", "How would you design a cache?"], audio_urls: [] }}
    total={5} onDone={onDone} />);
  return { api, onDone };
}

describe("InterviewScreen", () => {
  it("shows only the current question and one primary action", () => {
    setup();
    expect(screen.getByText("How would you design a cache?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /hold to answer/i })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("hides transcript, typed answer and End behind the menu", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByText(/transcript/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /type your answer/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /end interview/i })).toBeInTheDocument();
  });

  it("sends a typed answer and shows the interviewer's next line", async () => {
    const user = userEvent.setup();
    const { api } = setup();
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.type(screen.getByRole("textbox", { name: /type your answer/i }), "Use Redis");
    await user.click(screen.getByRole("button", { name: /send/i }));
    expect(api.sendText).toHaveBeenCalledWith("s1", "Use Redis");
    expect(await screen.findByText("Next question?")).toBeInTheDocument();
  });

  it("calls onDone when the interview finishes", async () => {
    const user = userEvent.setup();
    const { onDone } = setup({ sendText: vi.fn(async () => turn({ state: "done", kind: "closing", messages: ["Bye."] })) });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.type(screen.getByRole("textbox", { name: /type your answer/i }), "answer");
    await user.click(screen.getByRole("button", { name: /send/i }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("ends early from the menu", async () => {
    const user = userEvent.setup();
    const { api, onDone } = setup();
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("button", { name: /end interview/i }));
    expect(api.end).toHaveBeenCalledWith("s1");
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("shows a calm one-line error with a retry", async () => {
    const user = userEvent.setup();
    const sendText = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(turn());
    setup({ sendText });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.type(screen.getByRole("textbox", { name: /type your answer/i }), "answer");
    await user.click(screen.getByRole("button", { name: /send/i }));
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Next question?")).toBeInTheDocument();
  });
});
