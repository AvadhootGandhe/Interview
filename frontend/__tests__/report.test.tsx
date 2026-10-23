import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { ReportScreen, ReportView } from "@/components/report/ReportView";
import * as fx from "@/test/fixtures";

describe("report", () => {
  it("renders the overall score, verdict and per-question scores", () => {
    render(<ReportView report={fx.report} />);
    expect(screen.getByRole("img", { name: "Overall score 78 out of 100" })).toBeInTheDocument();
    expect(screen.getByText(fx.report.verdict!)).toBeInTheDocument();
    for (const q of fx.report.questions) {
      expect(screen.getByText(q.question)).toBeInTheDocument();
      expect(screen.getByText(String(q.score))).toBeInTheDocument();
    }
  });

  it("lists strengths and gaps", () => {
    render(<ReportView report={fx.report} />);
    expect(screen.getByRole("heading", { name: "Strengths" })).toBeInTheDocument();
    expect(screen.getByText("Clear structure")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "To work on" })).toBeInTheDocument();
    expect(screen.getByText("Cache invalidation strategies")).toBeInTheDocument();
  });

  it("keeps per-question feedback and the full thread collapsed until tapped", async () => {
    const user = userEvent.setup();
    render(<ReportView report={fx.report} />);
    expect(screen.queryByText("Clear layering and eviction choice.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /How would you design a cache/ }));
    expect(screen.getByText("Clear layering and eviction choice.")).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Full conversation" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("I would put Redis in front of the database.")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("I would put Redis in front of the database.")).toBeInTheDocument();
  });

  it("derives a verdict when the API sends none, and offers Practice again", () => {
    render(<ReportView report={{ ...fx.report, verdict: undefined, overall: 90 }} />);
    expect(screen.getByText("Excellent interview.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Practice again" })).toHaveAttribute("href", "/");
  });

  it("loads the report, with a calm loading line and a retry on error", async () => {
    const spy = vi
      .spyOn(api, "report")
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce(fx.report);
    const user = userEvent.setup();
    render(<ReportScreen id="s1" />);
    expect(screen.getByText("Preparing your report…")).toBeInTheDocument();
    expect(await screen.findByText("Couldn’t load your report.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(fx.report.verdict!)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith("s1");
  });
});
