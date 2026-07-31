import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Header } from "@/components/layout/header";
import { useChatStore } from "@/stores/chat";

const mocks = vi.hoisted(() => ({
  logoutCurrentSession: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("@/api/auth", () => ({
  logoutCurrentSession: mocks.logoutCurrentSession,
}));

vi.mock("@/lib/auth-mode", () => ({
  isLegacyDevAuthEnabled: false,
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useLocation: () => ({ pathname: "/dashboard", search: "" }),
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("@/components/notifications/notification-bell", () => ({
  NotificationBell: () => <div data-testid="notification-bell" />,
}));

describe("Header logout", () => {
  beforeEach(() => {
    mocks.logoutCurrentSession.mockReset().mockResolvedValue(undefined);
    mocks.navigate.mockReset();
  });

  it("ends the server session, clears client data, and returns to login", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const clearQueries = vi.spyOn(queryClient, "clear");
    const clearMessages = vi.spyOn(useChatStore.getState(), "clearMessages");

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Header />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(mocks.logoutCurrentSession).toHaveBeenCalledOnce();
      expect(clearQueries).toHaveBeenCalledOnce();
      expect(clearMessages).toHaveBeenCalledOnce();
      expect(mocks.navigate).toHaveBeenCalledWith("/login", { replace: true });
    });
  });
});
