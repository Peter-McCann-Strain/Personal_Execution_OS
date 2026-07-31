import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { NotificationCard } from "@/components/notifications/notification-card";
import type { Notification } from "@/types";

vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual<typeof import("@/lib/utils")>("@/lib/utils");
  return {
    ...actual,
    formatRelativeTime: () => "2h ago",
  };
});

function createNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "notification-1",
    message: "Monitor background jobs",
    priority: "P1",
    category: "system",
    created_at: "2026-04-07T09:00:00Z",
    dismissed: false,
    ...overrides,
  };
}

describe("NotificationCard", () => {
  it("renders unread system notifications and forwards action callbacks", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    const onDismiss = vi.fn();

    const { container } = renderWithProviders(
      <NotificationCard
        notification={createNotification({ priority: "P0" })}
        onAction={onAction}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByText("System")).toBeInTheDocument();
    expect(screen.getByText("Monitor background jobs")).toBeInTheDocument();
    expect(screen.getByText("2h ago")).toBeInTheDocument();
    expect(screen.getByText("P0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View Health" })).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse-subtle")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "View Health" }));
    expect(onAction).toHaveBeenCalledWith("/monitoring");

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledWith("notification-1");
  });

  it("renders read digest notifications without an action button", () => {
    const onDismiss = vi.fn();
    const { container } = renderWithProviders(
      <NotificationCard
        notification={createNotification({
          category: "digest",
          dismissed: true,
          message: "Daily digest delivered",
          priority: "P3",
        })}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByText("Digest")).toBeInTheDocument();
    expect(screen.getByText("Daily digest delivered")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View Health" })).not.toBeInTheDocument();
    expect(container.querySelector(".animate-pulse-subtle")).toBeNull();
  });
});
