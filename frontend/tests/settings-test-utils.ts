import { vi } from "vitest";
import { useAppStore } from "@/stores/app";

function resetSettingsState() {
  useAppStore.setState({
    sidebarCollapsed: false,
    rightPanelOpen: false,
    rightPanelContent: null,
    theme: "dark",
    commandPaletteOpen: false,
    apiKey: "",
    profileSettings: {
      displayName: "Owner",
      timezone: "UTC",
      workStart: "09:00",
      workEnd: "17:30",
    },
  });
  useAppStore.persist.clearStorage();
  sessionStorage.clear();
  document.documentElement.removeAttribute("data-theme");
}

function mockMatchMedia(matches: boolean) {
  return {
    matches,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  };
}

export { mockMatchMedia, resetSettingsState };
