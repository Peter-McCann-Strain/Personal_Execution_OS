import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen } from "../../test-utils";
import { QuickActions } from "@/components/dashboard/quick-actions";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

describe("QuickActions", () => {
  beforeEach(() => {
    mocks.navigate.mockReset();
  });

  it("renders the quick-action grid and routes clicks to the expected destinations", async () => {
    renderWithProviders(<QuickActions />);

    expect(screen.getByText("Quick Actions")).toBeInTheDocument();
    expect(screen.getByText("New Diary Entry")).toBeInTheDocument();
    expect(screen.getByText("Search Memory")).toBeInTheDocument();
    expect(screen.getByText("Research")).toBeInTheDocument();
    expect(screen.getByText("Check Calendar")).toBeInTheDocument();
    expect(screen.getByText("Check Email")).toBeInTheDocument();
    expect(screen.getByText("Weekly Review")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /New Diary Entry/i }));
    fireEvent.click(screen.getByRole("button", { name: /Check Calendar/i }));
    fireEvent.click(screen.getByRole("button", { name: /Weekly Review/i }));

    expect(mocks.navigate).toHaveBeenNthCalledWith(1, "/diary?capture=1");
    expect(mocks.navigate).toHaveBeenNthCalledWith(2, "/calendar");
    expect(mocks.navigate).toHaveBeenNthCalledWith(3, "/reviews");
  });
});
