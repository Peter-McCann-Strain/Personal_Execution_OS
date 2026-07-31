import { beforeEach, describe, expect, it, vi } from "vitest";
import { isValidElement, cloneElement } from "react";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, waitFor } from "../../test-utils";
import { createEpisodeStats } from "../../factories";
import { DiaryTrends } from "@/components/diary/diary-trends";
import type { EpisodeStats } from "@/api/episodes";

vi.mock("recharts", async () => {
  const { rechartsMock } = await import("../../recharts-mock");
  const Tooltip = (props: { content?: unknown }) => {
    const { content } = props;
    const state =
      (
        globalThis as {
          __diaryTooltipState?: {
            chartActive?: boolean;
            chartLabel?: string;
            chartPayload?: Array<{ value: number; name: string; color: string }>;
            barActive?: boolean;
            barPayload?: Array<{
              value: number;
              payload: { tag?: string; category?: string };
            }>;
          };
        }
      ).__diaryTooltipState ?? {};

    if (typeof content === "function") {
      return content({
        active: state.barActive ?? true,
        payload: state.barPayload ?? [
          { name: "project", value: 2, payload: { category: "project" } },
        ],
      });
    }

    if (isValidElement(content)) {
      const name = typeof content.type === "function" ? content.type.name : "";
      if (name === "ChartTooltip") {
        return cloneElement(content, {
          active: state.chartActive ?? true,
          label:
            state.chartLabel ??
            (globalThis as { __diaryTooltipLabel?: string }).__diaryTooltipLabel,
          payload: state.chartPayload ?? [
            {
              value: 123.456,
              name: "Mood",
              color: "var(--color-agent-diary)",
            },
          ],
        });
      }

      if (name === "BarTooltip") {
        return cloneElement(content, {
          active: state.barActive ?? true,
          payload: state.barPayload ?? [
            {
              value: 4,
              payload: { tag: "focus" },
            },
          ],
        });
      }
    }

    return null;
  };

  return {
    ...rechartsMock,
    Tooltip,
  };
});

const mocks = vi.hoisted(() => ({
  getEpisodeStats: vi.fn(),
}));

vi.mock("@/api/episodes", () => ({
  getEpisodeStats: mocks.getEpisodeStats,
}));

describe("DiaryTrends", () => {
  beforeEach(() => {
    mocks.getEpisodeStats.mockReset();
    (globalThis as { __diaryTooltipLabel?: string }).__diaryTooltipLabel = "2026-04-08T12:00:00Z";
    (
      globalThis as {
        __diaryTooltipState?: {
          chartActive?: boolean;
          chartLabel?: string;
          chartPayload?: Array<{ value: number; name: string; color: string }>;
          barActive?: boolean;
          barPayload?: Array<{
            value: number;
            payload: { tag?: string; category?: string };
          }>;
        };
      }
    ).__diaryTooltipState = {};
  });

  it("renders charts and switches time ranges", async () => {
    const stats30 = createEpisodeStats({
      totalEntries: 8,
      averageMood: 6.2,
      averageEnergy: 5.9,
      moodTrend: [{ date: "2026-04-01T12:00:00Z", mood: 6.2, energy: 5.5, count: 1 }],
      tagFrequency: [
        { tag: "focus", count: 5 },
        { tag: "work", count: 3 },
      ],
      paraDistribution: [
        { category: "project", count: 2 },
        { category: "resource", count: 1 },
      ],
    });
    const stats90 = createEpisodeStats({
      totalEntries: 18,
      averageMood: 7.1,
      averageEnergy: 6.3,
      tagFrequency: [{ tag: "review", count: 4 }],
      paraDistribution: [{ category: "area", count: 3 }],
    });
    const stats365 = createEpisodeStats({
      totalEntries: 42,
      averageMood: 6.8,
      averageEnergy: 6.0,
      tagFrequency: [{ tag: "planning", count: 2 }],
      paraDistribution: [{ category: "archive", count: 6 }],
    });

    mocks.getEpisodeStats.mockImplementation(async (days: number = 30): Promise<EpisodeStats> => {
      if (days === 90) return stats90;
      if (days === 365) return stats365;
      return stats30;
    });

    renderWithProviders(<DiaryTrends />);

    expect(await screen.findByText("Mood & Energy")).toBeInTheDocument();
    expect(
      screen.getAllByText((_, node) => node?.textContent?.includes("Total entries: 8") ?? false)
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByTestId("recharts-cell").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("project: 67%")).toBeInTheDocument();
    expect(screen.getByText("Mood: 123.5")).toBeInTheDocument();
    expect(screen.getByText("focus: 4")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "90d" }));
    await waitFor(() => {
      expect(mocks.getEpisodeStats).toHaveBeenLastCalledWith(90);
    });
    expect(
      (
        await screen.findAllByText(
          (_, node) => node?.textContent?.includes("Total entries: 18") ?? false,
        )
      ).length,
    ).toBeGreaterThan(0);
    expect(
      (await screen.findAllByText((_, node) => node?.textContent?.includes("area: 100%") ?? false))
        .length,
    ).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "365d" }));
    await waitFor(() => {
      expect(mocks.getEpisodeStats).toHaveBeenLastCalledWith(365);
    });
    expect(
      (
        await screen.findAllByText(
          (_, node) => node?.textContent?.includes("Total entries: 42") ?? false,
        )
      ).length,
    ).toBeGreaterThan(0);
    expect(
      (
        await screen.findAllByText(
          (_, node) => node?.textContent?.includes("archive: 100%") ?? false,
        )
      ).length,
    ).toBeGreaterThan(0);
  });

  it("falls back to the raw label when the chart tooltip label is not a valid date", async () => {
    (globalThis as { __diaryTooltipLabel?: string }).__diaryTooltipLabel = "not-a-date";

    mocks.getEpisodeStats.mockResolvedValue(
      createEpisodeStats({
        totalEntries: 5,
        averageMood: 6.4,
        averageEnergy: 5.1,
        moodTrend: [{ date: "2026-04-01T12:00:00Z", mood: 6.4, energy: 5.1, count: 1 }],
        tagFrequency: [{ tag: "focus", count: 2 }],
        paraDistribution: [{ category: "project", count: 1 }],
      }),
    );

    renderWithProviders(<DiaryTrends />);

    expect(await screen.findByText("not-a-date")).toBeInTheDocument();
  });

  it("renders the empty states when the query resolves without data", async () => {
    mocks.getEpisodeStats.mockResolvedValue(
      createEpisodeStats({
        totalEntries: 0,
        averageMood: null,
        averageEnergy: null,
        moodTrend: [],
        tagFrequency: [],
        paraDistribution: [],
      }),
    );

    renderWithProviders(<DiaryTrends />);

    expect(
      await screen.findByText("Start journaling to see your mood trends."),
    ).toBeInTheDocument();
    expect(screen.getByText("No tag data available.")).toBeInTheDocument();
    expect(screen.getByText("No PARA data available.")).toBeInTheDocument();
  });

  it("renders the loading state while the query is pending", () => {
    mocks.getEpisodeStats.mockReturnValueOnce(new Promise(() => {}));

    const { container } = renderWithProviders(<DiaryTrends />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders the error state when the query fails", async () => {
    mocks.getEpisodeStats.mockReset();
    mocks.getEpisodeStats.mockRejectedValueOnce(new Error("diary trends failed"));

    renderWithProviders(<DiaryTrends />);

    expect(await screen.findByText("Unable to load trends. Try refreshing.")).toBeInTheDocument();
  });

  it("handles chart tooltips with missing payloads without rendering fallback text", async () => {
    (
      globalThis as {
        __diaryTooltipState?: {
          chartActive?: boolean;
          barActive?: boolean;
        };
      }
    ).__diaryTooltipState = {
      chartActive: false,
      barActive: false,
    };

    mocks.getEpisodeStats.mockResolvedValue(
      createEpisodeStats({
        totalEntries: 2,
        averageMood: 6.1,
        averageEnergy: 5.2,
        moodTrend: [{ date: "2026-04-01T12:00:00Z", mood: 6.1, energy: 5.2, count: 1 }],
        tagFrequency: [{ tag: "focus", count: 2 }],
        paraDistribution: [{ category: "project", count: 1 }],
      }),
    );

    renderWithProviders(<DiaryTrends />);

    expect(await screen.findByText("Mood & Energy")).toBeInTheDocument();
    expect(screen.queryByText("Mood: 123.5")).not.toBeInTheDocument();
    expect(screen.queryByText("focus: 4")).not.toBeInTheDocument();
  });
});
