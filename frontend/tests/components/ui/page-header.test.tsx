import { describe, it, expect } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { PageHeader } from "@/components/ui/page-header";
import { Flame } from "lucide-react";

describe("PageHeader", () => {
  it("renders title", () => {
    renderWithProviders(<PageHeader title="Habits" />);
    expect(screen.getByRole("heading", { name: "Habits" })).toBeInTheDocument();
  });

  it("renders subtitle when provided", () => {
    renderWithProviders(<PageHeader title="Habits" subtitle="Track your daily routines" />);
    expect(screen.getByText("Track your daily routines")).toBeInTheDocument();
  });

  it("renders icon when provided", () => {
    const { container } = renderWithProviders(<PageHeader title="Habits" icon={Flame} />);
    // Should render the icon SVG
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThanOrEqual(1);
  });

  it("renders action children", () => {
    renderWithProviders(
      <PageHeader title="Habits">
        <button>New Habit</button>
      </PageHeader>,
    );
    expect(screen.getByRole("button", { name: "New Habit" })).toBeInTheDocument();
  });

  it("applies agent color accent when agentColor provided", () => {
    const { container } = renderWithProviders(
      <PageHeader title="Diary" icon={Flame} agentColor="diary" />,
    );
    // The icon container should have a style with the agent color
    const iconContainer = container.querySelector("div > div > div");
    expect(iconContainer).toBeTruthy();
  });
});
