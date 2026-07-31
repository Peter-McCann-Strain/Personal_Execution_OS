import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { createPaginatedResponse } from "../factories";
import { NotificationsPage } from "@/pages/notifications";
import type { Notification } from "@/types";

const mocks = vi.hoisted(() => ({
  dismissAllNotifications: vi.fn(),
  dismissNotification: vi.fn(),
  getNotifications: vi.fn(),
  navigate: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
  },
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("@/api/notifications", () => ({
  dismissAllNotifications: mocks.dismissAllNotifications,
  dismissNotification: mocks.dismissNotification,
  getNotifications: mocks.getNotifications,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
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
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <div>{children}</div>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({ description, title }: { description?: string; title: string }) => (
    <div>
      <div>{title}</div>
      {description ? <div>{description}</div> : null}
    </div>
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
    onChange: (value: "all" | "unread" | "read") => void;
    options: Array<{ label: string; value: "all" | "unread" | "read" }>;
    value: "all" | "unread" | "read";
  }) => (
    <div aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("@/components/notifications/notification-card", () => ({
  NotificationCard: ({
    notification,
    onAction,
    onDismiss,
  }: {
    notification: Notification;
    onAction: (path: string) => void;
    onDismiss: (id: string) => void;
  }) => (
    <div>
      <div>{notification.message}</div>
      <div>{notification.priority}</div>
      <button type="button" onClick={() => onDismiss(notification.id)}>
        Dismiss {notification.id}
      </button>
      <button type="button" onClick={() => onAction(`/notifications/${notification.id}`)}>
        Open {notification.id}
      </button>
    </div>
  ),
}));

function createNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "notification-1",
    message: "System alert",
    priority: "P1",
    category: "system",
    created_at: "2026-04-07T09:00:00Z",
    dismissed: false,
    ...overrides,
  };
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    mocks.dismissAllNotifications.mockReset();
    mocks.dismissAllNotifications.mockResolvedValue(undefined);
    mocks.dismissNotification.mockReset();
    mocks.dismissNotification.mockResolvedValue(undefined);
    mocks.getNotifications.mockReset();
    mocks.navigate.mockReset();
    mocks.toastSuccess.mockReset();
  });

  it("renders notifications, groups them by priority, dismisses items, and navigates actions", async () => {
    const user = userEvent.setup();
    const notifications = [
      createNotification({
        id: "notification-p0",
        message: "Database unavailable",
        priority: "P0",
      }),
      createNotification({
        id: "notification-p1",
        message: "Build checks need attention",
        priority: "P1",
      }),
      createNotification({
        id: "notification-p2",
        message: "Daily digest ready",
        priority: "P2",
        category: "digest",
      }),
      createNotification({
        id: "notification-p3",
        message: "Low priority housekeeping",
        priority: "P3",
      }),
    ];
    mocks.getNotifications.mockResolvedValue(createPaginatedResponse(notifications, { total: 4 }));

    renderWithProviders(<NotificationsPage />);

    expect(await screen.findByRole("heading", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByText("Alerts and reminders")).toBeInTheDocument();
    expect(await screen.findByText("Database unavailable")).toBeInTheDocument();
    expect(screen.getByText("(4 total)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Group notifications by priority" }));

    expect(screen.getByText("P0 Critical (1)")).toBeInTheDocument();
    expect(screen.getByText("P1 Important (1)")).toBeInTheDocument();
    expect(screen.getByText("P2 Normal (1)")).toBeInTheDocument();
    expect(screen.getByText("P3 Low (1)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dismiss notification-p0" }));
    await waitFor(() => {
      expect(mocks.dismissNotification).toHaveBeenCalledWith("notification-p0", expect.any(Object));
    });

    await user.click(screen.getByRole("button", { name: "Dismiss All" }));
    await waitFor(() => {
      expect(mocks.dismissAllNotifications).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByRole("button", { name: "Open notification-p2" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/notifications/notification-p2");
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Notification dismissed");
    expect(mocks.toastSuccess).toHaveBeenCalledWith("All notifications dismissed");
  });

  it("skips empty priority groups when only some priorities are present", async () => {
    const user = userEvent.setup();
    const notifications = [
      createNotification({
        id: "notification-p0",
        message: "Database unavailable",
        priority: "P0",
      }),
      createNotification({
        id: "notification-p2",
        message: "Daily digest ready",
        priority: "P2",
        category: "digest",
      }),
    ];
    mocks.getNotifications.mockResolvedValue(createPaginatedResponse(notifications, { total: 2 }));

    renderWithProviders(<NotificationsPage />);

    await user.click(screen.getByRole("button", { name: "Group notifications by priority" }));

    expect(screen.getByText("P0 Critical (1)")).toBeInTheDocument();
    expect(screen.getByText("P2 Normal (1)")).toBeInTheDocument();
    expect(screen.queryByText("P1 Important (1)")).not.toBeInTheDocument();
    expect(screen.queryByText("P3 Low (1)")).not.toBeInTheDocument();
  });

  it("renders the ungrouped notification list by default", async () => {
    const user = userEvent.setup();
    mocks.getNotifications.mockResolvedValue(
      createPaginatedResponse([createNotification()], { total: 1 }),
    );

    renderWithProviders(<NotificationsPage />);

    expect(await screen.findByText("System alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open notification-1" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open notification-1" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/notifications/notification-1");

    await user.click(screen.getByRole("button", { name: "Dismiss notification-1" }));
    await waitFor(() => {
      expect(mocks.dismissNotification).toHaveBeenCalledWith("notification-1", expect.any(Object));
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Notification dismissed");
  });

  it("updates notification query params when the user changes filters", async () => {
    const user = userEvent.setup();
    mocks.getNotifications.mockResolvedValue(
      createPaginatedResponse([createNotification()], { total: 1 }),
    );

    renderWithProviders(<NotificationsPage />);

    expect(await screen.findByText("System alert")).toBeInTheDocument();

    await user.click(screen.getByLabelText("P0"));
    await user.selectOptions(screen.getByRole("combobox"), "digest");
    await user.click(screen.getByRole("button", { name: "Unread" }));

    await waitFor(() => {
      expect(mocks.getNotifications).toHaveBeenLastCalledWith({
        category: "digest",
        limit: 50,
        priority: ["P0"],
        status: "unread",
      });
    });

    await user.click(screen.getByLabelText("P0"));
    await waitFor(() => {
      expect(mocks.getNotifications).toHaveBeenLastCalledWith({
        category: "digest",
        limit: 50,
        priority: undefined,
        status: "unread",
      });
    });
  });

  it("renders the empty state when no notifications match", async () => {
    mocks.getNotifications.mockResolvedValue(createPaginatedResponse([], { total: 0 }));

    renderWithProviders(<NotificationsPage />);

    expect(await screen.findByText("No notifications match your filters")).toBeInTheDocument();
  });

  it("renders the page error when the notifications query fails", async () => {
    const user = userEvent.setup();
    mocks.getNotifications.mockRejectedValue({});

    renderWithProviders(<NotificationsPage />);

    expect(await screen.findByText("Page Error: Failed to load notifications")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(mocks.getNotifications).toHaveBeenCalledTimes(2);
    });
  });
});
