import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderWithProviders, screen, waitFor } from "../../test-utils";
import { AppLayout } from "@/components/layout/app-layout";
import { useAppStore } from "@/stores/app";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
    Outlet: () => <div data-testid="outlet">Outlet</div>,
  };
});

vi.mock("@/components/layout/sidebar", () => ({
  Sidebar: () => <nav data-testid="sidebar">Sidebar</nav>,
}));

vi.mock("@/components/layout/header", () => ({
  Header: () => <header data-testid="header">Header</header>,
}));

vi.mock("@/components/layout/command-palette", () => ({
  CommandPalette: () => <div data-testid="command-palette">CommandPalette</div>,
}));

vi.mock("@/components/layout/right-panel", () => ({
  RightPanel: () => <div data-testid="right-panel">RightPanel</div>,
}));

function resetAppStore() {
  useAppStore.setState({
    sidebarCollapsed: false,
    rightPanelOpen: false,
    rightPanelContent: null,
    theme: "dark",
    commandPaletteOpen: false,
    apiKey: "",
    runtimeStreamStatus: "idle",
  });
  document.documentElement.removeAttribute("data-theme");
  document.title = "Execution OS";
}

describe("AppLayout", () => {
  beforeEach(() => {
    vi.mocked(window.matchMedia).mockImplementation((query: string) => ({
      matches: query === "(min-width: 1024px)",
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    act(() => {
      resetAppStore();
    });
    mocks.navigate.mockReset();
  });

  afterEach(() => {
    act(() => {
      resetAppStore();
    });
  });

  it("renders the shell and applies the current theme", async () => {
    await act(async () => {
      useAppStore.setState({
        theme: "light",
        rightPanelOpen: false,
      });
    });

    let container: HTMLElement;
    await act(async () => {
      ({ container } = renderWithProviders(<AppLayout />));
    });

    expect(screen.getByTestId("header")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("outlet")).toBeInTheDocument();
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    expect(screen.getByText("Skip to content")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    });
    expect(container!.querySelector("aside")).not.toBeInTheDocument();
  });

  it("removes the theme attribute when system theme is active", async () => {
    await act(async () => {
      useAppStore.setState({
        theme: "system",
        rightPanelOpen: true,
      });
    });

    let container: HTMLElement;
    await act(async () => {
      ({ container } = renderWithProviders(<AppLayout />));
    });

    await waitFor(() => {
      expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    });
    expect(container!.querySelector("aside")).toBeInTheDocument();
    expect(screen.getByTestId("right-panel")).toBeInTheDocument();
  });

  it("handles global keyboard shortcuts for sidebar and route navigation", async () => {
    await act(async () => {
      useAppStore.setState({
        theme: "dark",
        sidebarCollapsed: false,
        rightPanelOpen: false,
      });
    });

    renderWithProviders(<AppLayout />);

    await act(async () => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "b", metaKey: true, bubbles: true }),
      );
    });
    await waitFor(() => {
      expect(useAppStore.getState().sidebarCollapsed).toBe(true);
    });

    await act(async () => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "2", metaKey: true, bubbles: true }),
      );
    });
    expect(mocks.navigate).toHaveBeenCalledWith("/chat");
  });

  it("supports ctrl-based shortcuts and ignores shifted route shortcuts", async () => {
    await act(async () => {
      useAppStore.setState({
        theme: "dark",
        sidebarCollapsed: false,
        rightPanelOpen: false,
      });
    });

    renderWithProviders(<AppLayout />);

    await act(async () => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "7",
          ctrlKey: true,
          shiftKey: true,
          bubbles: true,
        }),
      );
    });
    expect(mocks.navigate).not.toHaveBeenCalled();

    await act(async () => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "7", ctrlKey: true, bubbles: true }),
      );
    });
    expect(mocks.navigate).toHaveBeenCalledWith("/email");

    await act(async () => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "x", ctrlKey: true, bubbles: true }),
      );
    });
    expect(mocks.navigate).toHaveBeenCalledTimes(1);
  });
});
