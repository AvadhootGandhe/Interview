import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import ReportView from "@/components/ReportView";
import type { Report } from "@/lib/types";

const report: Report = {
  session_id: "s1", profile: "Backend", level: "SDE-2/3", company: "Amazon", overall_score: 82,
  verdict: "Solid fundamentals, light on failure modes.", strengths: ["Clear structure"], gaps: ["Failure modes"],
  questions: [
    { index: 0, topic: "Caching", question: "Design a cache.", score: 75, followups: 1, covered_points: ["TTL"], missing_points: ["eviction"],
      thread: [{ role: "interviewer", kind: "ask", text: "How would you design a cache?" },
               { role: "candidate", kind: "answer", text: "Use Redis." }] },
    { index: 1, topic: "Kafka", question: "Explain offsets.", score: 90, followups: 0, covered_points: [], missing_points: [], thread: [] },
  ],
};

describe("ReportView", () => {
  it("shows overall score, verdict, strengths and gaps", () => {
    render(<ReportView report={report} />);
    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText(/solid fundamentals/i)).toBeInTheDocument();
    expect(screen.getByText("Clear structure")).toBeInTheDocument();
    expect(screen.getByText("Failure modes")).toBeInTheDocument();
  });

  it("lists each question with its score and expands to the thread", async () => {
    const user = userEvent.setup();
    render(<ReportView report={report} />);
    expect(screen.getByRole("button", { name: /caching/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /kafka/i })).toBeInTheDocument();
    expect(screen.queryByText("Use Redis.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /caching/i }));
    expect(screen.getByText("Use Redis.")).toBeInTheDocument();
  });

  it("offers one way forward", () => {
    render(<ReportView report={report} />);
    expect(screen.getByRole("link", { name: /practice again/i })).toHaveAttribute("href", "/");
  });
});
