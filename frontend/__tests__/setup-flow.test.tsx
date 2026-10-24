import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import SetupFlow, { canStart } from "@/components/SetupFlow";
import type { CatalogApi } from "@/lib/types";

const api: CatalogApi = {
  profiles: async () => ["Backend", "DevOps"],
  levels: async () => ["Fresher", "SDE-1", "SDE-2/3"],
  companies: vi.fn(async (q: string) => (q.toLowerCase().startsWith("am") ? ["Amazon"] : [])),
  topics: async () => ["Kafka", "Caching"],
};

describe("canStart", () => {
  it("needs a role and a level", () => {
    expect(canStart({})).toBe(false);
    expect(canStart({ profile: "Backend" })).toBe(false);
    expect(canStart({ level: "SDE-1" })).toBe(false);
    expect(canStart({ profile: "Backend", level: "SDE-1" })).toBe(true);
  });
});

describe("SetupFlow", () => {
  it("shows the headline and the role step first", async () => {
    render(<SetupFlow api={api} onStart={vi.fn()} />);
    expect(screen.getByRole("heading", { name: /practice your next interview/i })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Backend" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start/i })).not.toBeInTheDocument();
  });

  it("moves step by step and lets company and topic be skipped", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    render(<SetupFlow api={api} onStart={onStart} />);
    await user.click(await screen.findByRole("button", { name: "Backend" }));
    await user.click(await screen.findByRole("button", { name: "SDE-2/3" }));
    await user.click(await screen.findByRole("button", { name: /skip/i })); // company
    expect(await screen.findByRole("button", { name: "Kafka" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /start/i }));
    expect(onStart).toHaveBeenCalledWith({ profile: "Backend", level: "SDE-2/3", company: undefined, topic: undefined });
  });

  it("searches companies and passes company and topic through", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    render(<SetupFlow api={api} onStart={onStart} />);
    await user.click(await screen.findByRole("button", { name: "DevOps" }));
    await user.click(await screen.findByRole("button", { name: "SDE-1" }));
    await user.type(screen.getByRole("searchbox"), "ama");
    await user.click(await screen.findByRole("button", { name: "Amazon" }));
    await user.click(await screen.findByRole("button", { name: "Caching" }));
    await user.click(screen.getByRole("button", { name: /start/i }));
    expect(onStart).toHaveBeenCalledWith({ profile: "DevOps", level: "SDE-1", company: "Amazon", topic: "Caching" });
  });

  it("disables Start while starting", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<SetupFlow api={api} onStart={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Backend" }));
    await user.click(await screen.findByRole("button", { name: "SDE-1" }));
    await user.click(await screen.findByRole("button", { name: /skip/i }));
    rerender(<SetupFlow api={api} onStart={vi.fn()} starting />);
    await waitFor(() => expect(screen.getByRole("button", { name: /start|starting/i })).toBeDisabled());
  });

  it("can go back a step", async () => {
    const user = userEvent.setup();
    render(<SetupFlow api={api} onStart={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Backend" }));
    await user.click(await screen.findByRole("button", { name: /back/i }));
    expect(await screen.findByRole("button", { name: "DevOps" })).toBeInTheDocument();
  });
});
