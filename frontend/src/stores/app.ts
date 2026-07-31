import { create } from "zustand";
import { persist } from "zustand/middleware";
import { isLegacyDevAuthEnabled } from "@/lib/auth-mode";
import type { Email, Entity, EntityRelationship } from "@/types";

const API_KEY_STORAGE_KEY = ["api", "key"].join("_");

function readStoredApiKey(): string {
  if (!isLegacyDevAuthEnabled) return "";
  return sessionStorage.getItem(API_KEY_STORAGE_KEY) ?? "";
}

function writeStoredApiKey(key: string): void {
  if (!isLegacyDevAuthEnabled) {
    sessionStorage.removeItem(API_KEY_STORAGE_KEY);
    return;
  }
  if (key) {
    sessionStorage.setItem(API_KEY_STORAGE_KEY, key);
    return;
  }
  sessionStorage.removeItem(API_KEY_STORAGE_KEY);
}

export interface EntityInspectorSelection {
  entity: Entity;
  relationships: Array<{
    relationship: EntityRelationship;
    relatedEntity: Entity;
  }>;
}

interface AppState {
  // Sidebar
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  mobileSidebarOpen: boolean;
  toggleMobileSidebar: () => void;
  setMobileSidebarOpen: (open: boolean) => void;

  // Right panel
  rightPanelOpen: boolean;
  rightPanelContent: "workspace" | "artifact" | "entity" | "email" | "agent-run" | null;
  openRightPanel: (content: "workspace" | "artifact" | "entity" | "email" | "agent-run") => void;
  closeRightPanel: () => void;
  inspectedEmail: Email | null;
  setInspectedEmail: (email: Email | null) => void;
  inspectedEntity: EntityInspectorSelection | null;
  setInspectedEntity: (selection: EntityInspectorSelection | null) => void;
  inspectedAgentRunId: string | null;
  setInspectedAgentRunId: (runId: string | null) => void;

  // Theme
  theme: "dark" | "light" | "system";
  setTheme: (theme: "dark" | "light" | "system") => void;
  profileSettings: {
    displayName: string;
    timezone: string;
    workStart: string;
    workEnd: string;
  };
  setProfileSettings: (settings: AppState["profileSettings"]) => void;

  // Command palette
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;

  // Local development credentials
  apiKey: string;
  setApiKey: (key: string) => void;

  // Live runtime stream
  runtimeStreamStatus: "idle" | "connecting" | "live" | "error";
  setRuntimeStreamStatus: (status: "idle" | "connecting" | "live" | "error") => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // Sidebar
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      mobileSidebarOpen: false,
      toggleMobileSidebar: () => set((s) => ({ mobileSidebarOpen: !s.mobileSidebarOpen })),
      setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),

      // Right panel
      rightPanelOpen: false,
      rightPanelContent: null,
      openRightPanel: (content) => set({ rightPanelOpen: true, rightPanelContent: content }),
      closeRightPanel: () => set({ rightPanelOpen: false, rightPanelContent: null }),
      inspectedEmail: null,
      setInspectedEmail: (email) => set({ inspectedEmail: email }),
      inspectedEntity: null,
      setInspectedEntity: (selection) => set({ inspectedEntity: selection }),
      inspectedAgentRunId: null,
      setInspectedAgentRunId: (runId) => set({ inspectedAgentRunId: runId }),

      // Theme
      theme: "dark",
      setTheme: (theme) => {
        if (theme === "system") {
          // Detect OS preference and apply it
          const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
          document.documentElement.setAttribute("data-theme", prefersDark ? "dark" : "light");
        } else {
          document.documentElement.setAttribute("data-theme", theme);
        }
        set({ theme });
      },
      profileSettings: {
        displayName: "Owner",
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        workStart: "09:00",
        workEnd: "17:30",
      },
      setProfileSettings: (profileSettings) => set({ profileSettings }),

      // Command palette
      commandPaletteOpen: false,
      setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),

      // Local development credentials. In production builds these setters clear
      // session credentials instead of enabling browser API-key auth.
      apiKey: readStoredApiKey(),
      setApiKey: (key) => {
        writeStoredApiKey(key);
        set({ apiKey: key });
      },
      runtimeStreamStatus: "idle",
      setRuntimeStreamStatus: (status) => set({ runtimeStreamStatus: status }),
    }),
    {
      name: "assistant-app-store",
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        theme: state.theme,
        profileSettings: state.profileSettings,
      }),
    },
  ),
);
