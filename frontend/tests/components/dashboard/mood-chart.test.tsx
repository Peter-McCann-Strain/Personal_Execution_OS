import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, waitFor } from "../../test-utils";
import { MoodChart } from "@/components/dashboard/mood-chart";

vi.mock("recharts", async () => {
  const { rechartsMock } = await import("../../recharts-mock");
  return rechartsMock;
});

const mocks = vi.hoisted(() => ({
  getMoodEnergyTrends: vi.fn(),
}));

vi.mock("@/api/dashboard", () => ({
  getMoodEnergyTrends: mocks.getMoodEnergyTrends,
}));

describe("MoodChart", () => {
  beforeEach(() => {
    mocks.getMoodEnergyTrends.mockReset();
  });

  it("renders a loading skeleton while trend data is pending", () => {
    mocks.getMoodEnergyTrends.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(<MoodChart />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders an error state when trend data cannot be loaded", async () => {
    mocks.getMoodEnergyTrends.mockRejectedValue(new Error("trends failed"));

    renderWithProviders(<MoodChart />);

    expect(await screen.findByText("Unable to load trend data.")).toBeInTheDocument();
  });

  it("renders the empty state when there are no diary points", async () => {
    mocks.getMoodEnergyTrends.mockResolvedValue([]);

    renderWithProviders(<MoodChart />);

    expect(
      await screen.findByText("No diary entries yet. Start capturing your thoughts."),
    ).toBeInTheDocument();
  });

  it("renders chart metadata and legend when data is available", async () => {
    mocks.getMoodEnergyTrends.mockResolvedValue([
      { date: "2026-04-01", mood: 6.5, energy: 4.2 },
      { date: "2026-04-02", mood: 7.1, energy: 5.4 },
    ]);

    renderWithProviders(<MoodChart days={14} />);

    expect(await screen.findByText("Mood & Energy Trends")).toBeInTheDocument();
    expect(screen.getByText("14 days")).toBeInTheDocument();
    expect(screen.getByText("Mood")).toBeInTheDocument();
    expect(screen.getByText("Energy")).toBeInTheDocument();
    expect(screen.getByText("Wed 1 Apr")).toBeInTheDocument();
    expect(screen.getByText("Mood: 6.5")).toBeInTheDocument();
    expect(screen.getByText("Energy: 4.2")).toBeInTheDocument();

    await waitFor(() => {
      expect(mocks.getMoodEnergyTrends).toHaveBeenCalledWith(14);
    });
  });
});
