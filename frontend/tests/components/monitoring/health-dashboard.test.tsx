import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { HealthDashboard } from "@/components/monitoring/health-dashboard";

const mocks = vi.hoisted(() => ({
  invalidateQueries: vi.fn(),
  getHealth: vi.fn().mockResolvedValue({
    status: "degraded",
    services: {
      database: { status: "ok", message: "Primary database is healthy" },
      redis: { status: "down", message: "Redis is unavailable" },
      anthropic: { status: "ok", message: "Claude is reachable" },
    },
  }),
}));

vi.mock("@tanstack/react-query", async () => {
  const actual =
    await vi.importActual<typeof import("@tanstack/react-query")>("@tanstack/react-query");
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
  };
});

vi.mock("@/api/monitoring", () => ({
  getHealth: mocks.getHealth,
}));

describe("HealthDashboard", () => {
  beforeEach(() => {
    mocks.invalidateQueries.mockReset();
    mocks.getHealth.mockClear();
  });

  afterEach(() => {
    mocks.invalidateQueries.mockReset();
  });

  it("renders loading, live service status, and refresh behavior", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<HealthDashboard />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    expect(await screen.findByText("System Status")).toBeInTheDocument();
    expect(await screen.findByText("Claude is reachable")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
    expect(screen.getAllByText("Not configured")).toHaveLength(7);

    const refreshButton = screen.getByRole("button", { name: "Check Now" });
    await user.click(refreshButton);

    expect(mocks.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["health"] });
    expect(refreshButton).toBeDisabled();

    await waitFor(() => expect(screen.getByText(/Last check:/)).toBeInTheDocument());
  });
});
