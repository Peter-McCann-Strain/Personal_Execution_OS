import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { Header } from "@/components/layout/header";
import { useAppStore } from "@/stores/app";

let currentPath = "/dashboard";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useLocation: () => ({ pathname: currentPath }),
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("@/components/notifications/notification-bell", () => ({
  NotificationBell: () => <div data-testid="notification-bell" />,
}));

function resetAppStore() {
  useAppStore.setState({
    sidebarCollapsed: false,
    rightPanelOpen: false,
    rightPanelContent: null,
    theme: "dark",
    commandPaletteOpen: false,
    apiKey: "",
  });
  document.documentElement.removeAttribute("data-theme");
  document.title = "Execution OS";
}

describe("Header", () => {
  beforeEach(() => {
    act(() => {
      resetAppStore();
    });
    mocks.navigate.mockReset();
    currentPath = "/dashboard";
  });

  afterEach(() => {
    act(() => {
      resetAppStore();
    });
  });

  it("renders the fallback dashboard label and home navigation", async () => {
    currentPath = "/unknown";
    const user = userEvent.setup();

    renderWithProviders(<Header />);

    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(document.title).toBe("Dashboard — Execution OS");
    await user.click(screen.getByRole("button", { name: "Home" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/dashboard");
  });

  it("renders a mapped route label and opens the command palette", async () => {
    currentPath = "/monitoring";
    const user = userEvent.setup();

    renderWithProviders(<Header />);

    expect(screen.getByText("Monitoring")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Open command palette"));
    expect(useAppStore.getState().commandPaletteOpen).toBe(true);
  });

  it("opens the command palette from the desktop search trigger", async () => {
    const user = userEvent.setup();

    renderWithProviders(<Header />);

    await user.click(screen.getByText("Search..."));
    expect(useAppStore.getState().commandPaletteOpen).toBe(true);
  });

  it("toggles the workspace panel from the header control", async () => {
    const user = userEvent.setup();

    renderWithProviders(<Header />);

    await user.click(screen.getByLabelText("Toggle workspace panel"));
    expect(useAppStore.getState().rightPanelOpen).toBe(true);
    expect(useAppStore.getState().rightPanelContent).toBe("workspace");

    await user.click(screen.getByLabelText("Toggle workspace panel"));
    expect(useAppStore.getState().rightPanelOpen).toBe(false);
    expect(useAppStore.getState().rightPanelContent).toBeNull();
  });

  it("toggles the theme from dark to light", async () => {
    await act(async () => {
      useAppStore.setState({ theme: "dark" });
    });
    const user = userEvent.setup();

    renderWithProviders(<Header />);

    expect(screen.getByLabelText("Toggle theme")).toHaveAttribute("title", "Switch to light mode");

    await act(async () => {
      await user.click(screen.getByLabelText("Toggle theme"));
    });
    await waitFor(() => {
      expect(useAppStore.getState().theme).toBe("light");
      expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    });
  });

  it("toggles the theme from light to dark on another route label", async () => {
    currentPath = "/settings";
    await act(async () => {
      useAppStore.setState({ theme: "light" });
    });
    const user = userEvent.setup();

    renderWithProviders(<Header />);

    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(document.title).toBe("Settings — Execution OS");
    expect(screen.getByLabelText("Toggle theme")).toHaveAttribute("title", "Switch to dark mode");

    await act(async () => {
      await user.click(screen.getByLabelText("Toggle theme"));
    });
    await waitFor(() => {
      expect(useAppStore.getState().theme).toBe("dark");
      expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    });
  });
});
