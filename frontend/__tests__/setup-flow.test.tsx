import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { SetupFlow } from "@/components/setup/SetupFlow";
import * as fx from "@/test/fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn() }),
}));

function mockCatalog() {
  return {
    profiles: vi.spyOn(api, "profiles").mockResolvedValue(fx.profiles),
    levels: vi.spyOn(api, "levels").mockResolvedValue(fx.levels),
    topics: vi.spyOn(api, "topics").mockResolvedValue(fx.topics),
    companies: vi.spyOn(api, "companies").mockImplementation(async (q: string) =>
      ["Amazon", "Apple", "Stripe"].filter((c) => c.toLowerCase().includes(q.toLowerCase())),
    ),
    create: vi.spyOn(api, "createSession").mockResolvedValue(fx.sessionStart),
  };
}

async function toCompanyStep(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Backend" }));
  await user.click(await screen.findByRole("radio", { name: "SDE-2/3" }));
  await screen.findByText("Choose a company.");
}

describe("setup flow", () => {
  beforeEach(() => push.mockReset());

  it("shows the headline and starts with the role step only", async () => {
    mockCatalog();
    render(<SetupFlow />);
    expect(screen.getByRole("heading", { name: "Practice your next interview." })).toBeInTheDocument();
    expect(await screen.findByText("Choose your role.")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
  });

  it("moves step by step: role → level → company (Skip) → topic (Any topic) → Start", async () => {
    const m = mockCatalog();
    const user = userEvent.setup();
    render(<SetupFlow />);

    await user.click(await screen.findByRole("button", { name: "Backend" }));
    expect(await screen.findByText("Choose your level.")).toBeInTheDocument();
    expect(screen.queryByText("Choose your role.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "SDE-2/3" }));
    expect(await screen.findByText("Choose a company.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(await screen.findByText("Choose a topic.")).toBeInTheDocument();
    expect(m.topics).toHaveBeenCalledWith("Backend");

    const start = screen.getByRole("button", { name: "Start" });
    expect(start).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Any topic" }));
    expect(start).toBeEnabled();

    await user.click(start);
    await waitFor(() =>
      expect(m.create).toHaveBeenCalledWith({ profile: "Backend", level: "SDE-2/3", company: null, topic: null }),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/interview/s1"));
  });

  it("searches and picks a company, then a specific topic", async () => {
    const m = mockCatalog();
    const user = userEvent.setup();
    render(<SetupFlow />);
    await toCompanyStep(user);

    await user.type(screen.getByRole("searchbox", { name: "Search companies" }), "ama");
    await waitFor(() => expect(m.companies).toHaveBeenLastCalledWith("ama"));
    await user.click(await screen.findByRole("button", { name: "Amazon" }));

    await screen.findByText("Choose a topic.");
    await user.click(await screen.findByRole("button", { name: "Caching" }));
    await user.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() =>
      expect(m.create).toHaveBeenCalledWith({
        profile: "Backend",
        level: "SDE-2/3",
        company: "Amazon",
        topic: "Caching",
      }),
    );
  });

  it("shows one calm empty line when no company matches, with Skip still available", async () => {
    mockCatalog();
    const user = userEvent.setup();
    render(<SetupFlow />);
    await toCompanyStep(user);
    await user.type(screen.getByRole("searchbox", { name: "Search companies" }), "zzz");
    expect(await screen.findByText("No companies match.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip" })).toBeInTheDocument();
  });

  it("Back returns to the previous step", async () => {
    mockCatalog();
    const user = userEvent.setup();
    render(<SetupFlow />);
    await user.click(await screen.findByRole("button", { name: "Backend" }));
    await screen.findByText("Choose your level.");
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByText("Choose your role.")).toBeInTheDocument();
  });

  it("disables Start while the session is being created", async () => {
    const m = mockCatalog();
    m.create.mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    render(<SetupFlow />);
    await toCompanyStep(user);
    await user.click(screen.getByRole("button", { name: "Skip" }));
    await user.click(await screen.findByRole("button", { name: "Any topic" }));
    await user.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByRole("button", { name: "Starting…" })).toBeDisabled();
  });

  it("shows a one-line error with a single retry when the catalog fails", async () => {
    const m = mockCatalog();
    m.profiles.mockRejectedValueOnce(new Error("down"));
    const user = userEvent.setup();
    render(<SetupFlow />);
    expect(await screen.findByText("Couldn’t load roles.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: "Backend" })).toBeInTheDocument();
  });
});
