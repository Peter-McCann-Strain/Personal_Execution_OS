import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, waitFor } from "../test-utils";
import { createEpisode, createPaginatedResponse } from "../factories";
import { DiaryPage } from "@/pages/diary";
import type { Episode, EpisodeQueryParams } from "@/api/episodes";

const mocks = vi.hoisted(() => ({
  getEpisodes: vi.fn(),
}));

vi.mock("@/api/episodes", () => ({
  getEpisodes: mocks.getEpisodes,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({
    children,
    subtitle,
    title,
  }: {
    children?: React.ReactNode;
    subtitle: string;
    title: string;
  }) => (
    <header>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <div>{children}</div>
    </header>
  ),
}));

vi.mock("@/components/ui/segmented-control", () => ({
  SegmentedControl: ({
    label,
    onChange,
    options,
    value,
  }: {
    label: string;
    onChange: (value: string) => void;
    options: Array<{ label: string; value: string }>;
    value: string;
  }) => (
    <div role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("@/components/diary/diary-entry-card", () => ({
  DiaryEntryCard: ({
    episode,
    onTagClick,
  }: {
    episode: Episode;
    onTagClick?: (tag: string) => void;
  }) => (
    <article>
      <h2>{episode.summary ?? episode.content}</h2>
      <button type="button" onClick={() => onTagClick?.(episode.tags[0])}>
        Tag {episode.tags[0]}
      </button>
    </article>
  ),
  DiaryEntryCardSkeleton: () => <div>Diary entry skeleton</div>,
}));

vi.mock("@/components/diary/diary-trends", () => ({
  DiaryTrends: () => <div>Diary Trends Panel</div>,
}));

vi.mock("@/components/diary/quick-capture-modal", () => ({
  QuickCaptureModal: ({
    externalOpen,
    onExternalOpenChange,
  }: {
    externalOpen?: boolean;
    onExternalOpenChange?: (open: boolean) => void;
  }) => (
    <div>
      <div>{externalOpen ? "Quick Capture Open" : "Quick Capture Closed"}</div>
      <button type="button" onClick={() => onExternalOpenChange?.(false)}>
        Close capture
      </button>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message }: { message: string }) => <div>Page Error: {message}</div>,
}));

function createDiaryEpisode(overrides: Partial<Episode> = {}): Episode {
  return createEpisode({
    id: "episode-1",
    summary: "First diary entry",
    content: "First diary entry",
    tags: ["focus", "work"],
    people_mentioned: ["Ada"],
    created_at: "2026-04-01T12:00:00Z",
    ...overrides,
  });
}

describe("DiaryPage", () => {
  beforeEach(() => {
    mocks.getEpisodes.mockReset();
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-08T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the feed, applies filters, loads more, and opens quick capture", async () => {
    const primary = createDiaryEpisode();
    const secondary = createDiaryEpisode({
      id: "episode-2",
      summary: "Second diary entry",
      content: "Second diary entry",
      tags: ["review"],
      people_mentioned: [],
      created_at: "2026-04-02T12:00:00Z",
    });

    mocks.getEpisodes.mockImplementation(async (params?: EpisodeQueryParams) => {
      if (params?.offset === 20) {
        return createPaginatedResponse(
          [createDiaryEpisode({ id: "episode-3", summary: "Loaded more entry" })],
          { total: 41, page: 2, page_size: 20, has_more: false },
        );
      }

      return createPaginatedResponse([primary, secondary], {
        total: 40,
        page: 1,
        page_size: 20,
        has_more: true,
      });
    });

    renderWithProviders(<DiaryPage />);

    expect(await screen.findByText("First diary entry")).toBeInTheDocument();
    expect(screen.getByText("Load more entries...")).toBeInTheDocument();

    const firstCall = mocks.getEpisodes.mock.calls[0]?.[0] as EpisodeQueryParams;
    expect(firstCall.date_from).toBe("2026-04-01T00:00:00.000Z");

    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[0], { target: { value: "all" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.sort).toBe("created_at");
      expect(lastCall.order).toBe("desc");
      expect(lastCall.date_from).toBeUndefined();
    });

    fireEvent.change(selects[1], { target: { value: "project" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.para_category).toBe("project");
    });

    fireEvent.change(selects[2], { target: { value: "research" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.episode_type).toBe("research");
    });

    fireEvent.change(selects[3], { target: { value: "oldest" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.sort).toBe("created_at");
      expect(lastCall.order).toBe("asc");
    });

    fireEvent.click(screen.getByRole("button", { name: "Tag focus" }));
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.tags).toEqual(["focus"]);
    });

    fireEvent.click(screen.getByRole("button", { name: "Tag focus" }));
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.tags).toEqual(["focus"]);
    });

    fireEvent.click(screen.getByRole("button", { name: "Load more entries..." }));
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.offset).toBe(20);
    });

    fireEvent.click(screen.getByRole("tab", { name: "Trends" }));
    expect(screen.getByText("Diary Trends Panel")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "New Entry" }));
    expect(screen.getByText("Quick Capture Open")).toBeInTheDocument();
  });

  it("recomputes episode params for alternate date ranges and sort modes, then resets filters", async () => {
    mocks.getEpisodes.mockResolvedValue(
      createPaginatedResponse([createDiaryEpisode()], {
        total: 1,
        page: 1,
        page_size: 20,
        has_more: false,
      }),
    );

    renderWithProviders(<DiaryPage />);

    expect(await screen.findByText("First diary entry")).toBeInTheDocument();
    const initialDateFrom = (mocks.getEpisodes.mock.calls[0]?.[0] as EpisodeQueryParams).date_from;

    const selects = screen.getAllByRole("combobox");

    fireEvent.change(selects[0], { target: { value: "30d" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.date_from).not.toBe(initialDateFrom);
    });

    fireEvent.change(selects[0], { target: { value: "90d" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.date_from).not.toBe(initialDateFrom);
    });

    fireEvent.change(selects[1], { target: { value: "archive" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.para_category).toBe("archive");
    });

    fireEvent.change(selects[2], { target: { value: "capture" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.episode_type).toBe("capture");
    });

    fireEvent.change(selects[3], { target: { value: "mood_high" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.sort).toBe("mood_score");
      expect(lastCall.order).toBe("desc");
    });

    fireEvent.change(selects[3], { target: { value: "mood_low" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.sort).toBe("mood_score");
      expect(lastCall.order).toBe("asc");
    });

    fireEvent.change(selects[3], { target: { value: "energy_high" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.sort).toBe("energy_rating");
      expect(lastCall.order).toBe("desc");
    });

    fireEvent.change(selects[3], { target: { value: "energy_low" } });
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.sort).toBe("energy_rating");
      expect(lastCall.order).toBe("asc");
    });

    fireEvent.click(screen.getByRole("button", { name: "Tag focus" }));
    expect(screen.getByRole("button", { name: "Clear all" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    await waitFor(() => {
      const lastCall = mocks.getEpisodes.mock.calls.at(-1)?.[0] as EpisodeQueryParams;
      expect(lastCall.date_from).toBeDefined();
      expect(lastCall.para_category).toBeUndefined();
      expect(lastCall.episode_type).toBeUndefined();
      expect(lastCall.tags).toBeUndefined();
      expect(lastCall.mood_min).toBeUndefined();
      expect(lastCall.mood_max).toBeUndefined();
    });
  });

  it("renders the empty state", async () => {
    mocks.getEpisodes.mockResolvedValueOnce(
      createPaginatedResponse([], { total: 0, page_size: 20, has_more: false }),
    );

    renderWithProviders(<DiaryPage />);

    expect(await screen.findByText("No diary entries yet")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New Entry" }).length).toBeGreaterThan(0);
  });

  it("renders the error state", async () => {
    mocks.getEpisodes.mockReset();
    mocks.getEpisodes.mockRejectedValueOnce(new Error("diary failed"));

    renderWithProviders(<DiaryPage />);

    expect(await screen.findByText("Page Error: diary failed")).toBeInTheDocument();
  });
});
