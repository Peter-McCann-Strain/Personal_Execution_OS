import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/components/ui/error-boundary", () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="error-boundary">{children}</div>
  ),
}));

vi.mock("@/components/layout/app-layout", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    AppLayout: () => (
      <div>
        <div>App layout shell</div>
        <actual.Outlet />
      </div>
    ),
  };
});

vi.mock("@/components/auth/auth-gate", () => ({
  AuthGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/pages/landing", () => ({
  LandingPage: () => <div>Landing page</div>,
}));
vi.mock("@/pages/dashboard", () => ({
  DashboardPage: () => <div>Dashboard page</div>,
}));
vi.mock("@/pages/chat", () => ({
  ChatPage: () => <div>Chat page</div>,
}));
vi.mock("@/pages/diary", () => ({
  DiaryPage: () => <div>Diary page</div>,
}));
vi.mock("@/pages/memory", () => ({
  MemoryPage: () => <div>Memory page</div>,
}));
vi.mock("@/pages/workbench", () => ({
  WorkbenchPage: () => <div>Workbench page</div>,
}));
vi.mock("@/pages/projects", () => ({
  ProjectsPage: () => <div>Projects page</div>,
}));
vi.mock("@/pages/goals", () => ({
  GoalsPage: () => <div>Goals page</div>,
}));
vi.mock("@/pages/reviews", () => ({
  ReviewsPage: () => <div>Reviews page</div>,
}));
vi.mock("@/pages/contacts", () => ({
  ContactsPage: () => <div>Contacts page</div>,
}));
vi.mock("@/pages/calendar", () => ({
  CalendarPage: () => <div>Calendar page</div>,
}));
vi.mock("@/pages/email", () => ({
  EmailPage: () => <div>Email page</div>,
}));
vi.mock("@/pages/notifications", () => ({
  NotificationsPage: () => <div>Notifications page</div>,
}));
vi.mock("@/pages/monitoring", () => ({
  MonitoringPage: () => <div>Monitoring page</div>,
}));
vi.mock("@/pages/settings", () => ({
  SettingsPage: () => <div>Settings page</div>,
}));
vi.mock("@/pages/knowledge-graph", () => ({
  KnowledgeGraphPage: () => <div>Knowledge graph page</div>,
}));
vi.mock("@/pages/notes", () => ({
  NotesPage: () => <div>Notes page</div>,
}));
vi.mock("@/pages/commitments", () => ({
  CommitmentsPage: () => <div>Commitments page</div>,
}));
vi.mock("@/pages/habits", () => ({
  HabitsPage: () => <div>Habits page</div>,
}));
vi.mock("@/pages/decisions", () => ({
  DecisionsPage: () => <div>Decisions page</div>,
}));
vi.mock("@/pages/tutorials", () => ({
  TutorialsPage: () => <div>Tutorials page</div>,
}));

describe("AppRouter rendering", () => {
  const appRoutes = [
    ["/dashboard", "Dashboard page"],
    ["/chat", "Chat page"],
    ["/diary", "Diary page"],
    ["/memory", "Memory page"],
    ["/knowledge-graph", "Knowledge graph page"],
    ["/notes", "Notes page"],
    ["/workbench", "Workbench page"],
    ["/projects", "Projects page"],
    ["/goals", "Goals page"],
    ["/reviews", "Reviews page"],
    ["/habits", "Habits page"],
    ["/commitments", "Commitments page"],
    ["/decisions", "Decisions page"],
    ["/contacts", "Contacts page"],
    ["/calendar", "Calendar page"],
    ["/email", "Email page"],
    ["/tutorials", "Tutorials page"],
    ["/notifications", "Notifications page"],
    ["/monitoring", "Monitoring page"],
    ["/settings", "Settings page"],
  ] as const;

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    cleanup();
    window.history.pushState({}, "", "/");
  });

  it("renders the standalone welcome route", async () => {
    window.history.pushState({}, "", "/welcome");

    const { AppRouter } = await import("@/router");
    render(<AppRouter />);

    expect(await screen.findByText("Landing page")).toBeInTheDocument();
    expect(screen.queryByText("App layout shell")).not.toBeInTheDocument();
  });

  it("redirects the index route to the dashboard inside the app layout", async () => {
    window.history.pushState({}, "", "/");

    const { AppRouter } = await import("@/router");
    render(<AppRouter />);

    expect(await screen.findByText("App layout shell")).toBeInTheDocument();
    expect(await screen.findByText("Dashboard page")).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/dashboard");
    });
  });

  it.each(appRoutes)("renders %s inside the app layout", async (path, expectedText) => {
    window.history.pushState({}, "", path);

    const { AppRouter } = await import("@/router");
    render(<AppRouter />);

    expect(await screen.findByText(expectedText)).toBeInTheDocument();
    expect(screen.getByText("App layout shell")).toBeInTheDocument();
    expect(window.location.pathname).toBe(path);
  });

  it("redirects unknown routes to the dashboard", async () => {
    window.history.pushState({}, "", "/does-not-exist");

    const { AppRouter } = await import("@/router");
    render(<AppRouter />);

    expect(await screen.findByText("Dashboard page")).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/dashboard");
    });
  });
});
