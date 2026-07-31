import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { Search, Sun, Moon, PanelRightOpen, PanelRightClose, Menu, LogOut } from "lucide-react";
import { toast } from "sonner";
import { logoutCurrentSession } from "@/api/auth";
import { cn } from "@/lib/utils";
import { isLegacyDevAuthEnabled } from "@/lib/auth-mode";
import { MOD_KEY } from "@/lib/platform";
import { useAppStore } from "@/stores/app";
import { useChatStore } from "@/stores/chat";
import { Button } from "@/components/ui/button";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { getRouteMeta } from "./route-metadata";

// ─── Header Component ────────────────────────────────────────

function Header() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const toggleMobileSidebar = useAppStore((s) => s.toggleMobileSidebar);
  const rightPanelOpen = useAppStore((s) => s.rightPanelOpen);
  const rightPanelContent = useAppStore((s) => s.rightPanelContent);
  const openRightPanel = useAppStore((s) => s.openRightPanel);
  const closeRightPanel = useAppStore((s) => s.closeRightPanel);

  const currentLabel = getRouteMeta(location.pathname).label;

  useEffect(() => {
    document.title = `${currentLabel} — Execution OS`;
  }, [currentLabel]);

  const toggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  const toggleWorkspacePanel = () => {
    if (rightPanelOpen && rightPanelContent === "workspace") {
      closeRightPanel();
      return;
    }
    openRightPanel("workspace");
  };

  const handleLogout = async () => {
    try {
      await logoutCurrentSession();
      queryClient.clear();
      useChatStore.getState().clearMessages();
      navigate("/login", { replace: true });
    } catch {
      toast.error("Sign out failed. Please try again.");
    }
  };

  return (
    <header
      className="flex h-[var(--header-height)] items-center gap-2 border-b border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 sm:gap-4 sm:px-4"
      style={{ gridArea: "header" }}
    >
      <Button
        variant="ghost"
        size="icon"
        onClick={toggleMobileSidebar}
        className="lg:hidden text-[var(--color-fg-tertiary)]"
        aria-label="Open navigation menu"
      >
        <Menu className="h-4 w-4" />
      </Button>

      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm min-w-0">
        <button
          onClick={() => navigate("/dashboard")}
          className="text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)] transition-colors shrink-0"
        >
          Home
        </button>
        <span className="text-[var(--color-fg-tertiary)]">/</span>
        <span className="truncate text-[var(--color-fg-primary)] font-medium">{currentLabel}</span>
      </nav>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Search Trigger */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setCommandPaletteOpen(true)}
        className="hidden sm:flex gap-2 text-[var(--color-fg-tertiary)]"
      >
        <Search className="h-4 w-4" />
        <span className="text-xs">Search...</span>
        <kbd
          className={cn(
            "pointer-events-none ml-1 hidden select-none rounded-[var(--radius-sm)] border border-[var(--color-border-default)] bg-[var(--color-bg-overlay)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-fg-tertiary)]",
            "sm:inline-block",
          )}
        >
          {MOD_KEY}+K
        </kbd>
      </Button>

      {/* Mobile search icon */}
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setCommandPaletteOpen(true)}
        className="sm:hidden text-[var(--color-fg-tertiary)]"
        aria-label="Open command palette"
      >
        <Search className="h-4 w-4" />
      </Button>

      {/* Notification Bell */}
      <NotificationBell />

      {/* Workspace Panel Toggle */}
      <Button
        variant="ghost"
        size="icon"
        onClick={toggleWorkspacePanel}
        className="text-[var(--color-fg-tertiary)]"
        title={
          rightPanelOpen && rightPanelContent === "workspace"
            ? "Close workspace panel"
            : "Open workspace panel"
        }
        aria-label="Toggle workspace panel"
      >
        {rightPanelOpen && rightPanelContent === "workspace" ? (
          <PanelRightClose className="h-4 w-4" />
        ) : (
          <PanelRightOpen className="h-4 w-4" />
        )}
      </Button>

      {/* Theme Toggle */}
      <Button
        variant="ghost"
        size="icon"
        onClick={toggleTheme}
        className="text-[var(--color-fg-tertiary)]"
        title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        aria-label="Toggle theme"
      >
        {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </Button>

      {!isLegacyDevAuthEnabled ? (
        <Button
          variant="ghost"
          size="icon"
          onClick={handleLogout}
          className="text-[var(--color-fg-tertiary)]"
          title="Sign out"
          aria-label="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </Button>
      ) : null}
    </header>
  );
}

export { Header };
