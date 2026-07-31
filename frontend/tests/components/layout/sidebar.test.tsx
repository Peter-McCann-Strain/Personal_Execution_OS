import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { Sidebar } from "@/components/layout/sidebar";
import { navSections } from "@/components/layout/sidebar.config";
import type { NavSection } from "@/components/layout/sidebar.config";
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

function resetAppStore() {
  useAppStore.setState({
    sidebarCollapsed: false,
    rightPanelOpen: false,
    rightPanelContent: null,
    theme: "dark",
    commandPaletteOpen: false,
    apiKey: "",
  });
}

describe("Sidebar", () => {
  beforeEach(() => {
    currentPath = "/dashboard";
    mocks.navigate.mockReset();
    resetAppStore();
  });

  afterEach(() => {
    currentPath = "/dashboard";
    mocks.navigate.mockReset();
    resetAppStore();
  });

  it("renders all navigation sections", () => {
    renderWithProviders(<Sidebar />);
    for (const section of navSections) {
      // Section titles visible in expanded mode
      expect(screen.getByText(section.title)).toBeInTheDocument();
    }
  });

  it("renders all navigation items as buttons", () => {
    renderWithProviders(<Sidebar />);
    for (const section of navSections) {
      for (const item of section.items) {
        expect(screen.getByRole("button", { name: item.label })).toBeInTheDocument();
      }
    }
  });

  it("has 3 focused navigation sections", () => {
    expect(navSections).toHaveLength(3);
  });

  it("includes all expected sections", () => {
    const sectionTitles = navSections.map((s: NavSection) => s.title);
    expect(sectionTitles).toEqual(["Primary", "Workspace", "Admin"]);
  });

  it("Primary section has 5 items", () => {
    const primary = navSections.find((s: NavSection) => s.title === "Primary");
    expect(primary?.items).toHaveLength(5);
  });

  it("Workspace section has 12 items", () => {
    const workspace = navSections.find((s: NavSection) => s.title === "Workspace");
    expect(workspace?.items).toHaveLength(12);
  });

  it("renders Quick Capture button", () => {
    renderWithProviders(<Sidebar />);
    expect(screen.getByRole("button", { name: /quick capture/i })).toBeInTheDocument();
  });

  it("navigates to diary capture from the expanded quick capture button", async () => {
    const user = userEvent.setup();

    renderWithProviders(<Sidebar />);

    await user.click(screen.getByRole("button", { name: "Quick Capture" }));

    expect(mocks.navigate).toHaveBeenCalledWith("/diary?capture=1");
  });

  it("navigates when a nav item is clicked", async () => {
    const user = userEvent.setup();

    renderWithProviders(<Sidebar />);

    await user.click(screen.getByRole("button", { name: "Chat" }));

    expect(mocks.navigate).toHaveBeenCalledWith("/chat");
  });

  it("renders 8 agent activity dots", () => {
    const { container } = renderWithProviders(<Sidebar />);
    // Agent dots are spans with rounded-full class and agent background colors
    // With Radix tooltips, they're Tooltip.Trigger children
    // Count the colored dot spans in the agent activity area
    const dots = container.querySelectorAll("span.inline-block");
    expect(dots.length).toBe(8);
  });

  it("renders toggle sidebar button", () => {
    renderWithProviders(<Sidebar />);
    expect(screen.getByRole("button", { name: /toggle sidebar/i })).toBeInTheDocument();
  });

  it("supports the collapsed shell and expanding back to the full nav", async () => {
    const user = userEvent.setup();
    useAppStore.setState({ sidebarCollapsed: true });

    renderWithProviders(<Sidebar />);

    expect(screen.queryByText("Primary")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /toggle sidebar/i })).toHaveAttribute(
      "title",
      "Expand sidebar",
    );
    expect(screen.getByRole("button", { name: /quick capture/i })).toHaveAttribute(
      "title",
      expect.stringContaining("Quick Capture"),
    );

    await user.click(screen.getByRole("button", { name: /toggle sidebar/i }));

    expect(useAppStore.getState().sidebarCollapsed).toBe(false);
    expect(screen.getByText("Primary")).toBeInTheDocument();
  });

  it("all nav items have valid paths starting with /", () => {
    for (const section of navSections) {
      for (const item of section.items) {
        expect(item.path).toMatch(/^\//);
      }
    }
  });

  it("applies active styling for an agent-colored nav item", () => {
    currentPath = "/chat";

    const { container } = renderWithProviders(<Sidebar />);
    const chatButton = screen.getByRole("button", { name: "Chat" });

    expect(chatButton.getAttribute("style")).toContain("border-left");
    expect(container.querySelector('button[aria-label="Toggle sidebar"]')).toBeInTheDocument();
  });
});
