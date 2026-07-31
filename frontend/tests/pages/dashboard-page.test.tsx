import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen } from "../test-utils";
import { DashboardPage } from "@/pages/dashboard";

const mocks = vi.hoisted(() => ({
  getDashboardStats: vi.fn(),
  getRecentDiaryEntries: vi.fn(),
  pageError: vi.fn(),
}));

vi.mock("@/api/dashboard", () => ({
  getDashboardStats: mocks.getDashboardStats,
  getRecentDiaryEntries: mocks.getRecentDiaryEntries,
}));

vi.mock("@/components/dashboard/stat-card", () => ({
  StatCard: ({
    label,
    emptyText,
    value,
    formatValue,
  }: {
    label: string;
    emptyText: string;
    value: number | null;
    formatValue?: (v: number) => string;
  }) => (
    <div>
      <span>{label}</span>
      <span>{emptyText}</span>
      <span>{value != null ? (formatValue ? formatValue(value) : value) : "--"}</span>
    </div>
  ),
  StatCardSkeleton: () => <div>StatCardSkeleton</div>,
}));

vi.mock("@/components/dashboard/morning-briefing", () => ({
  MorningBriefing: () => <div>Morning Briefing</div>,
}));

vi.mock("@/components/dashboard/mood-chart", () => ({
  MoodChart: () => <div>Mood Chart</div>,
}));

vi.mock("@/components/dashboard/goal-progress", () => ({
  GoalProgress: () => <div>Goal Progress</div>,
}));

vi.mock("@/components/dashboard/recent-activity", () => ({
  RecentActivity: () => <div>Recent Activity</div>,
}));

vi.mock("@/components/dashboard/quick-actions", () => ({
  QuickActions: () => <div>Quick Actions</div>,
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: () => <div>Skeleton</div>,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({ title, subtitle }: { title: string; subtitle: string }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message, onRetry }: { message: string; onRetry: () => void }) => {
    mocks.pageError({ message, onRetry });
    return (
      <div>
        <div>Page Error: {message}</div>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  },
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  ParaBadge: ({ category }: { category: string }) => <span>PARA:{category}</span>,
}));

describe("DashboardPage", () => {
  beforeEach(() => {
    mocks.pageError.mockReset();
    mocks.getDashboardStats.mockReset();
    mocks.getRecentDiaryEntries.mockReset();
  });

  function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  }

  it("renders dashboard content, fallback empty text, and recent diary entries", async () => {
    mocks.getDashboardStats.mockResolvedValue({
      mood: {
        value: 7.3,
        trend: "up",
        sparkline: [5, 6, 7],
        subLabel: "steady",
        message: null,
      },
      projects: {
        value: 3,
        trend: "flat",
        sparkline: [2, 3, 3],
        subLabel: "active",
        message: "Projects available",
      },
      emails: {
        value: 0,
        trend: "down",
        sparkline: [2, 1, 0],
        subLabel: "quiet inbox",
        message: null,
      },
      events: {
        value: 0,
        trend: "flat",
        sparkline: [0, 0, 0],
        subLabel: "clear calendar",
        message: null,
      },
    });
    mocks.getRecentDiaryEntries.mockResolvedValue([
      {
        id: "episode-1",
        created_at: "2026-04-07T08:00:00Z",
        summary: "Met with the product team to review the roadmap",
        content: "Met with the product team to review the roadmap",
        mood_score: 8.2,
        energy_rating: 7.4,
        para_category: "project",
        tags: ["planning", "roadmap", "team", "q2"],
      },
    ]);

    renderWithProviders(<DashboardPage />);

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText("Your personal command centre")).toBeInTheDocument();
    expect(await screen.findByText("Today's Mood")).toBeInTheDocument();
    expect(screen.getByText("7.3")).toBeInTheDocument();
    expect(screen.getByText("Log your first diary entry")).toBeInTheDocument();
    expect(screen.getByText("Inbox zero!")).toBeInTheDocument();
    expect(screen.getByText("No events -- Free day!")).toBeInTheDocument();
    expect(screen.getByText("Morning Briefing")).toBeInTheDocument();
    expect(screen.getByText("Mood Chart")).toBeInTheDocument();
    expect(screen.getByText("Goal Progress")).toBeInTheDocument();
    expect(screen.getByText("Recent Activity")).toBeInTheDocument();
    expect(screen.getByText("Quick Actions")).toBeInTheDocument();
    expect(screen.getByText("Recent Diary")).toBeInTheDocument();
    expect(screen.getByText("PARA:project")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
  });

  it("renders loading placeholders and empty diary state", async () => {
    const stats = deferred<Awaited<ReturnType<typeof mocks.getDashboardStats>>>();
    const diary = deferred<Awaited<ReturnType<typeof mocks.getRecentDiaryEntries>>>();

    mocks.getDashboardStats.mockReturnValue(stats.promise);
    mocks.getRecentDiaryEntries.mockReturnValue(diary.promise);

    renderWithProviders(<DashboardPage />);

    expect(screen.getAllByText("Skeleton").length).toBeGreaterThanOrEqual(7);

    stats.resolve({
      mood: {
        value: 5.1,
        trend: "flat",
        sparkline: [5, 5, 5],
        subLabel: "steady",
        message: null,
      },
      projects: {
        value: 1,
        trend: "up",
        sparkline: [0, 1, 1],
        subLabel: "one active",
        message: null,
      },
      emails: {
        value: 2,
        trend: "up",
        sparkline: [1, 1, 2],
        subLabel: "mailbox",
        message: null,
      },
      events: {
        value: 1,
        trend: "flat",
        sparkline: [1, 1, 1],
        subLabel: "calendar",
        message: null,
      },
    });
    diary.resolve([]);

    expect(
      await screen.findByText("No diary entries yet. Start capturing your thoughts."),
    ).toBeInTheDocument();
  });

  it("renders a minimal diary entry without optional metadata", async () => {
    mocks.getDashboardStats.mockResolvedValue({
      mood: {
        value: 7.3,
        trend: "up",
        sparkline: [5, 6, 7],
        subLabel: "steady",
        message: null,
      },
      projects: {
        value: 3,
        trend: "flat",
        sparkline: [2, 3, 3],
        subLabel: "active",
        message: "Projects available",
      },
      emails: {
        value: 0,
        trend: "down",
        sparkline: [2, 1, 0],
        subLabel: "quiet inbox",
        message: null,
      },
      events: {
        value: 0,
        trend: "flat",
        sparkline: [0, 0, 0],
        subLabel: "clear calendar",
        message: null,
      },
    });
    mocks.getRecentDiaryEntries.mockResolvedValue([
      {
        id: "episode-2",
        created_at: "2026-04-07T08:00:00Z",
        summary: null,
        content: "Captured a short reflection without any structured metadata.",
        mood_score: null,
        energy_rating: null,
        para_category: null,
        tags: [],
      },
    ]);

    renderWithProviders(<DashboardPage />);

    expect(
      await screen.findByText("Captured a short reflection without any structured metadata."),
    ).toBeInTheDocument();
    expect(screen.queryByText("PARA:project")).not.toBeInTheDocument();
    expect(screen.queryByText(/Mood:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Energy:/)).not.toBeInTheDocument();
  });

  it("renders the page error state when dashboard stats fail", async () => {
    mocks.getDashboardStats.mockRejectedValue(new Error("dashboard failed"));
    mocks.getRecentDiaryEntries.mockResolvedValue([]);

    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Dashboard stats unavailable")).toBeInTheDocument();
    expect(screen.getByText("dashboard failed")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  });
});
