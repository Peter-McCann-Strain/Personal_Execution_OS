import { useEffect, useCallback, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { useAppStore } from "@/stores/app";
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";
import { CommandPalette } from "@/components/layout/command-palette";
import { ProactiveNotificationBridge } from "@/components/layout/proactive-notification-bridge";
import { RuntimeStreamBridge } from "@/components/layout/runtime-stream-bridge";
import { RightPanel } from "@/components/layout/right-panel";
import { cn } from "@/lib/utils";

const DESKTOP_NAV_QUERY = "(min-width: 1024px)";

function getIsDesktop() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(DESKTOP_NAV_QUERY).matches
    : true;
}

function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(getIsDesktop);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;

    const mediaQuery = window.matchMedia(DESKTOP_NAV_QUERY);
    const update = () => setIsDesktop(mediaQuery.matches);

    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, []);

  return isDesktop;
}

function AppLayout() {
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const toggleMobileSidebar = useAppStore((s) => s.toggleMobileSidebar);
  const mobileSidebarOpen = useAppStore((s) => s.mobileSidebarOpen);
  const setMobileSidebarOpen = useAppStore((s) => s.setMobileSidebarOpen);
  const rightPanelOpen = useAppStore((s) => s.rightPanelOpen);
  const closeRightPanel = useAppStore((s) => s.closeRightPanel);
  const theme = useAppStore((s) => s.theme);
  const navigate = useNavigate();
  const location = useLocation();
  const isDesktop = useIsDesktop();
  const dockRightPanel = rightPanelOpen && isDesktop;

  // Apply theme on mount
  useEffect(() => {
    if (theme === "system") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", theme);
    }
  }, [theme]);

  // Global keyboard shortcuts
  const handleGlobalKeyDown = useCallback(
    (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;

      // Cmd+B: Toggle sidebar
      if (mod && e.key === "b") {
        e.preventDefault();
        if (isDesktop) {
          toggleSidebar();
        } else {
          toggleMobileSidebar();
        }
        return;
      }

      // Cmd+N: Open quick capture
      if (mod && e.key === "n") {
        e.preventDefault();
        navigate("/diary?capture=1");
        return;
      }

      // Cmd+1..9: Navigate to routes
      if (mod && !e.shiftKey) {
        const routeMap: Record<string, string> = {
          "1": "/dashboard",
          "2": "/chat",
          "3": "/diary",
          "4": "/memory",
          "5": "/projects",
          "6": "/calendar",
          "7": "/email",
          "8": "/pulse",
          "9": "/settings",
        };
        if (routeMap[e.key]) {
          e.preventDefault();
          navigate(routeMap[e.key]);
          return;
        }
      }
    },
    [isDesktop, toggleMobileSidebar, toggleSidebar, navigate],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleGlobalKeyDown);
    return () => document.removeEventListener("keydown", handleGlobalKeyDown);
  }, [handleGlobalKeyDown]);

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [location.pathname, setMobileSidebarOpen]);

  useEffect(() => {
    if (isDesktop) {
      setMobileSidebarOpen(false);
    }
  }, [isDesktop, setMobileSidebarOpen]);

  return (
    <>
      {/* Skip to content link for keyboard users */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-[var(--color-bg-surface)] focus:text-[var(--color-fg-primary)] focus:rounded-[var(--radius-md)] focus:border focus:border-[var(--color-border-focus)]"
      >
        Skip to content
      </a>
      <div
        className="grid h-dvh overflow-hidden bg-[var(--color-bg-base)]"
        style={{
          gridTemplateRows: "var(--header-height) 1fr",
          gridTemplateColumns: dockRightPanel
            ? "auto minmax(0, 1fr) var(--right-panel-width)"
            : "auto minmax(0, 1fr)",
          gridTemplateAreas: dockRightPanel
            ? `"header header header" "sidebar main panel"`
            : `"header header" "sidebar main"`,
        }}
      >
        {/* Header */}
        <Header />

        {/* Sidebar */}
        <Sidebar className="hidden lg:flex" />

        {/* Main Content */}
        <main
          id="main-content"
          className="overflow-y-auto overflow-x-hidden"
          style={{ gridArea: "main" }}
        >
          <Outlet />
        </main>

        {/* Right panel */}
        {rightPanelOpen && !isDesktop && (
          <button
            type="button"
            className="fixed inset-x-0 bottom-0 top-[var(--header-height)] z-40 bg-black/50 backdrop-blur-sm lg:hidden"
            onClick={closeRightPanel}
            aria-label="Close workspace panel"
          />
        )}
        {rightPanelOpen && (
          <aside
            className={cn(
              "overflow-y-auto border-l border-[var(--color-border-default)] bg-[var(--color-bg-surface)]",
              isDesktop
                ? ""
                : "fixed bottom-0 right-0 top-[var(--header-height)] z-50 w-[min(92vw,var(--right-panel-width))] shadow-2xl",
            )}
            style={isDesktop ? { gridArea: "panel" } : undefined}
          >
            <RightPanel />
          </aside>
        )}

        {mobileSidebarOpen && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <button
              type="button"
              className="absolute inset-0 bg-black/55 backdrop-blur-sm"
              onClick={() => setMobileSidebarOpen(false)}
              aria-label="Close navigation menu"
            />
            <Sidebar
              mobile
              onNavigate={() => setMobileSidebarOpen(false)}
              className="absolute inset-y-0 left-0 z-10 shadow-2xl"
            />
          </div>
        )}

        {/* Command Palette (overlay) */}
        <CommandPalette />
      </div>
      <RuntimeStreamBridge />
      <ProactiveNotificationBridge />
    </>
  );
}

export { AppLayout };
