import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import type { ReactNode } from "react";
import { act, renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { CommandPalette } from "@/components/layout/command-palette";
import { useAppStore } from "@/stores/app";

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

vi.mock("cmdk", () => {
  const CommandRoot = ({ children, className, onKeyDown }: Record<string, unknown>) => (
    <div className={className as string} onKeyDown={onKeyDown as never}>
      {children as ReactNode}
    </div>
  );
  CommandRoot.Input = (props: Record<string, unknown>) => <input {...props} />;
  CommandRoot.List = ({ children, className }: Record<string, unknown>) => (
    <div className={className as string}>{children as ReactNode}</div>
  );
  CommandRoot.Empty = ({ children, className }: Record<string, unknown>) => (
    <div className={className as string}>{children as ReactNode}</div>
  );
  CommandRoot.Group = ({ children, heading, className }: Record<string, unknown>) => (
    <section className={className as string}>
      <div>{heading as ReactNode}</div>
      {children as ReactNode}
    </section>
  );
  CommandRoot.Item = ({ children, onSelect, value, className }: Record<string, unknown>) => (
    <button
      type="button"
      aria-label={value as string}
      className={className as string}
      onClick={() => (onSelect as (() => void) | undefined)?.()}
    >
      {children as ReactNode}
    </button>
  );
  return { Command: CommandRoot };
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

describe("CommandPalette", () => {
  beforeEach(() => {
    resetAppStore();
    mocks.navigate.mockReset();
  });

  afterEach(() => {
    act(() => {
      resetAppStore();
    });
  });

  it("stays hidden when closed and opens on Cmd+K", async () => {
    const user = userEvent.setup();

    const { container } = renderWithProviders(<CommandPalette />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.keyboard("{Meta>}k{/Meta}");

    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();

    const backdrop = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    await user.click(backdrop);
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
  });

  it("closes on a second Cmd+K press", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CommandPalette />);

    await user.keyboard("{Meta>}k{/Meta}");
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();

    await user.keyboard("{Meta>}k{/Meta}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens on Ctrl+K as well", async () => {
    renderWithProviders(<CommandPalette />);
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    });
    expect(useAppStore.getState().commandPaletteOpen).toBe(true);
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
  });

  it("renders pages, actions, and closes after selecting an item", async () => {
    useAppStore.setState({ commandPaletteOpen: true, theme: "dark" });
    const user = userEvent.setup();

    renderWithProviders(<CommandPalette />);

    expect(screen.getByText("Pages")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Chat")).toBeInTheDocument();
    expect(screen.getByText("Switch to light mode")).toBeInTheDocument();
    expect(screen.getByText("No results found.")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Dashboard"));
    expect(mocks.navigate).toHaveBeenCalledWith("/dashboard");
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
  });

  it("toggles the theme action and supports Escape to close", async () => {
    useAppStore.setState({ commandPaletteOpen: true, theme: "light" });
    const user = userEvent.setup();

    const { rerender } = renderWithProviders(<CommandPalette />);

    await act(async () => {
      await user.click(screen.getByLabelText("Switch to dark mode"));
    });
    await waitFor(() => {
      expect(useAppStore.getState().theme).toBe("dark");
    });

    await act(async () => {
      useAppStore.setState({ commandPaletteOpen: true, theme: "dark" });
      rerender(<CommandPalette />);
    });
    await act(async () => {
      await user.click(screen.getAllByPlaceholderText("Search or type a command...")[0]);
      await user.keyboard("{Escape}");
    });
    await waitFor(() => {
      expect(useAppStore.getState().commandPaletteOpen).toBe(false);
    });
  });

  it("executes the remaining page and action callbacks", async () => {
    async function openAndClick(label: string) {
      await act(async () => {
        useAppStore.setState({ commandPaletteOpen: true });
      });
      screen.getByRole("dialog", { name: "Command palette" });
      const button = screen.getByRole("button", { name: label });
      await act(async () => {
        button.click();
      });
      await waitFor(() => {
        expect(useAppStore.getState().commandPaletteOpen).toBe(false);
      });
    }

    renderWithProviders(<CommandPalette />);

    for (const label of [
      "Diary",
      "Memory",
      "Chat",
      "Knowledge Graph",
      "Notes",
      "Workbench",
      "Projects",
      "Goals",
      "Reviews",
      "Habits",
      "Commitments",
      "Decisions",
      "Tutorials",
      "Contacts",
      "Calendar",
      "Email",
      "Notifications",
      "Monitoring",
      "Settings",
      "New diary entry",
      "Search memory",
      "Check calendar",
      "Review email",
      "Start research",
      "Break down project",
    ]) {
      await openAndClick(label);
    }
  }, 15000);
});
