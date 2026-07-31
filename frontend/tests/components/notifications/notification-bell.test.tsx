import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { createPaginatedResponse } from "../../factories";
import { NotificationBell } from "@/components/notifications/notification-bell";
import type { Notification } from "@/types";

const mocks = vi.hoisted(() => ({
  dismissNotification: vi.fn(),
  getNotifications: vi.fn(),
  getUnreadCount: vi.fn(),
  markAllRead: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual<typeof import("@/lib/utils")>("@/lib/utils");
  return {
    ...actual,
    formatRelativeTime: () => "5m ago",
  };
});

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("@/api/notifications", () => ({
  dismissNotification: mocks.dismissNotification,
  getNotifications: mocks.getNotifications,
  getUnreadCount: mocks.getUnreadCount,
  markAllRead: mocks.markAllRead,
}));

function createNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "notification-1",
    message: "Review the deployment smoke check",
    priority: "P1",
    category: "system",
    created_at: "2026-04-07T09:00:00Z",
    dismissed: false,
    ...overrides,
  };
}

describe("NotificationBell", () => {
  beforeEach(() => {
    mocks.dismissNotification.mockReset();
    mocks.dismissNotification.mockResolvedValue(undefined);
    mocks.getNotifications.mockReset();
    mocks.getUnreadCount.mockReset();
    mocks.markAllRead.mockReset();
    mocks.markAllRead.mockResolvedValue(undefined);
    mocks.navigate.mockReset();
  });

  it("renders the unread badge, opens the dropdown, and executes notification actions", async () => {
    const user = userEvent.setup();
    const notifications = [
      createNotification({ id: "notification-1", priority: "P0" }),
      createNotification({
        id: "notification-2",
        category: "deadline",
        message: "Calendar event starts soon",
      }),
    ];

    mocks.getUnreadCount.mockResolvedValue({ total: 120, hasP0: true, hasP1: false });
    mocks.getNotifications.mockResolvedValue(
      createPaginatedResponse(notifications, { total: 2, page_size: 5 }),
    );

    renderWithProviders(<NotificationBell />);

    expect(await screen.findByText("99+")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Notifications" }));

    expect(await screen.findByText("Calendar event starts soon")).toBeInTheDocument();
    expect(screen.getByText("120 unread")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Dismiss notification" })[0]);
    await waitFor(() => {
      expect(mocks.dismissNotification.mock.calls[0]?.[0]).toBe("notification-1");
    });

    await user.click(screen.getByRole("button", { name: "Mark All Read" }));
    await waitFor(() => {
      expect(mocks.markAllRead).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByRole("button", { name: "View All" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/notifications");
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Mark All Read" })).not.toBeInTheDocument();
    });
  });

  it("renders the warning unread badge variant when only P1 items are present", async () => {
    const user = userEvent.setup();
    mocks.getUnreadCount.mockResolvedValue({ total: 5, hasP0: false, hasP1: true });
    mocks.getNotifications.mockResolvedValue(
      createPaginatedResponse([createNotification({ priority: "P1" })], {
        total: 1,
        page_size: 5,
      }),
    );

    renderWithProviders(<NotificationBell />);

    expect(await screen.findByText("5")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("Review the deployment smoke check")).toBeInTheDocument();
    expect(screen.getByText("5 unread")).toBeInTheDocument();
  });

  it("renders the neutral unread badge and dismissed item styling", async () => {
    const user = userEvent.setup();
    mocks.getUnreadCount.mockResolvedValue({ total: 5, hasP0: false, hasP1: false });
    mocks.getNotifications.mockResolvedValue(
      createPaginatedResponse(
        [createNotification({ dismissed: true, message: "Routine follow-up" })],
        { total: 1, page_size: 5 },
      ),
    );

    renderWithProviders(<NotificationBell />);

    expect(await screen.findByText("5")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("Routine follow-up")).toBeInTheDocument();
  });

  it("shows an empty dropdown and closes on outside click or Escape", async () => {
    const user = userEvent.setup();

    mocks.getUnreadCount.mockResolvedValue({ total: 0, hasP0: false, hasP1: false });
    mocks.getNotifications.mockResolvedValue(
      createPaginatedResponse([], { total: 0, page_size: 5 }),
    );

    renderWithProviders(<NotificationBell />);

    await user.click(screen.getByRole("button", { name: "Notifications" }));

    expect(await screen.findByText("No new notifications")).toBeInTheDocument();

    await act(async () => {
      document.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    await waitFor(() => {
      expect(screen.queryByText("No new notifications")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("No new notifications")).toBeInTheDocument();

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    expect(screen.getByText("No new notifications")).toBeInTheDocument();

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    await waitFor(() => {
      expect(screen.queryByText("No new notifications")).not.toBeInTheDocument();
    });
  });
});
