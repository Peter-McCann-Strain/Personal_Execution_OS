import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { StatCard, StatCardSkeleton } from "@/components/dashboard/stat-card";

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("../../recharts-mock")>("../../recharts-mock");
  return actual.rechartsMock;
});

describe("StatCard", () => {
  it("renders formatted values, decimal trends, and sparklines", () => {
    renderWithProviders(
      <StatCard
        value={7.25}
        label="Today's Mood"
        trend={1.5}
        sparkline={[5, 6, 7]}
        subLabel="steady"
        agentColor="diary"
        formatValue={(value) => value.toFixed(1)}
      />,
    );

    expect(screen.getByText("Today's Mood")).toBeInTheDocument();
    expect(screen.getByText("7.3")).toBeInTheDocument();
    expect(screen.getByText("+1.5")).toBeInTheDocument();
    expect(screen.getByText("steady")).toBeInTheDocument();
  });

  it("renders empty-state content and neutral trends when value is missing", () => {
    renderWithProviders(
      <StatCard
        value={null}
        label="Inbox"
        trend={0}
        sparkline={[]}
        subLabel={null}
        agentColor="communications"
        emptyText="Inbox unavailable"
      />,
    );

    expect(screen.getByText("Inbox")).toBeInTheDocument();
    expect(screen.getByText("--")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByText("Inbox unavailable")).toBeInTheDocument();
  });

  it("renders negative trends and the loading skeleton", () => {
    const { container } = renderWithProviders(
      <>
        <StatCard
          value={12}
          label="Projects"
          trend={-2}
          sparkline={[2, 1]}
          subLabel="active"
          agentColor="project"
        />
        <StatCardSkeleton />
      </>,
    );

    expect(screen.getByText("-2")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });
});
