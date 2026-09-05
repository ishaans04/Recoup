import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ConsoleTabs, { type TabSpec } from "@/components/console/ConsoleTabs";

const TABS: TabSpec[] = [
  { id: "work-items", label: "Work items", count: 20 },
  { id: "human-queue", label: "Human Queue", count: 6, alert: true },
  { id: "live-audit", label: "Live audit stream", count: 107 },
  { id: "gate", label: "Constraint gate & Rejections", count: 4, alert: true },
  { id: "by-cause", label: "Recovery by cause" },
];

describe("ConsoleTabs", () => {
  afterEach(cleanup);

  it("renders the five sections in the order given", () => {
    render(<ConsoleTabs tabs={TABS} active="work-items" onSelect={() => {}} />);
    const labels = screen.getAllByTestId("console-tab").map((tab) => tab.textContent);
    expect(labels[0]).toContain("Work items");
    expect(labels[1]).toContain("Human Queue");
    expect(labels[2]).toContain("Live audit stream");
    expect(labels[3]).toContain("Constraint gate & Rejections");
    expect(labels[4]).toContain("Recovery by cause");
  });

  it("marks exactly one tab selected", () => {
    render(<ConsoleTabs tabs={TABS} active="gate" onSelect={() => {}} />);
    const selected = screen
      .getAllByTestId("console-tab")
      .filter((tab) => tab.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent("Constraint gate & Rejections");
  });

  it("reports its section to assistive tech", () => {
    render(<ConsoleTabs tabs={TABS} active="work-items" onSelect={() => {}} />);
    expect(screen.getByRole("tablist", { name: /console sections/i })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(5);
  });

  it("carries each section's count, omitting it where it has no meaning", () => {
    render(<ConsoleTabs tabs={TABS} active="work-items" onSelect={() => {}} />);
    const tabs = screen.getAllByTestId("console-tab");
    expect(tabs[0]).toHaveTextContent("20");
    expect(tabs[1]).toHaveTextContent("6");
    // "Recovery by cause" is not a queue depth; a number there would invent one.
    expect(tabs[4]).toHaveTextContent("Recovery by cause");
    expect(tabs[4].textContent?.replace("Recovery by cause", "")).toMatch(/^\s*$/);
  });

  it("selects a section when its tab is clicked", () => {
    const onSelect = vi.fn();
    render(<ConsoleTabs tabs={TABS} active="work-items" onSelect={onSelect} />);
    fireEvent.click(screen.getByText("Live audit stream").closest("button")!);
    expect(onSelect).toHaveBeenCalledWith("live-audit");
  });
});
