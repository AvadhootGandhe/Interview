import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button, Card, Chip, Orb, SearchField, SegmentedControl } from "@/components/ui";

describe("design system", () => {
  it("Button: primary is a pill with a 44px tap target and can be disabled", () => {
    render(<Button disabled>Start</Button>);
    const btn = screen.getByRole("button", { name: "Start" });
    expect(btn).toBeDisabled();
    expect(btn.className).toMatch(/min-h-tap/);
    expect(btn.className).toMatch(/rounded-full/);
    expect(btn.className).toMatch(/bg-accent/);
  });

  it("Button: secondary variant does not use the accent fill", () => {
    render(<Button variant="secondary">Skip</Button>);
    expect(screen.getByRole("button", { name: "Skip" }).className).not.toMatch(/bg-accent/);
  });

  it("Chip toggles via aria-pressed and calls onClick", async () => {
    const onClick = vi.fn();
    render(
      <Chip selected onClick={onClick}>
        Backend
      </Chip>,
    );
    const chip = screen.getByRole("button", { name: "Backend" });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(chip);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("SegmentedControl exposes radio semantics and reports changes", async () => {
    const onChange = vi.fn();
    render(<SegmentedControl label="Level" options={["SDE-1", "SDE-2/3"]} value="SDE-1" onChange={onChange} />);
    expect(screen.getByRole("radiogroup", { name: "Level" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "SDE-1" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("radio", { name: "SDE-2/3" }));
    expect(onChange).toHaveBeenCalledWith("SDE-2/3");
  });

  it("SearchField is a labelled search box", async () => {
    const onChange = vi.fn();
    render(<SearchField label="Search companies" value="" onChange={onChange} />);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search companies" }), "a");
    expect(onChange).toHaveBeenCalledWith("a");
  });

  it("Card renders its children", () => {
    render(<Card>Inside</Card>);
    expect(screen.getByText("Inside")).toBeInTheDocument();
  });

  it("Orb reflects its state", () => {
    const { rerender } = render(<Orb state="idle" />);
    expect(screen.getByTestId("orb")).toHaveAttribute("data-state", "idle");
    rerender(<Orb state="listening" />);
    expect(screen.getByTestId("orb")).toHaveAttribute("data-state", "listening");
  });
});
