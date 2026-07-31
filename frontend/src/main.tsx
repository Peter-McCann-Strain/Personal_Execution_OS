import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { setUnauthorizedHandler } from "./api/client";
import { buildAuthEntryPath } from "./lib/auth-mode";
import { useAppStore } from "./stores/app";
import { AppRouter } from "./router";
import "./index.css";

// Redirect to the active auth entrypoint whenever any /api/* call returns 401.
// Production uses a same-origin server session; the legacy /setup path only
// exists for explicit insecure local development.
setUnauthorizedHandler(() => {
  const path = window.location.pathname;
  if (
    path === "/setup" ||
    path === "/welcome" ||
    path === "/login" ||
    path.startsWith("/sign-in") ||
    path.startsWith("/sign-up")
  ) {
    return;
  }
  const returnTo = `${window.location.pathname}${window.location.search}`;
  const target = buildAuthEntryPath(returnTo);
  // Use replace so the broken page isn't in the history.
  window.location.replace(target);
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

function readSavedTheme(): "light" | "dark" | "system" | undefined {
  try {
    const saved = JSON.parse(localStorage.getItem("assistant-app-store") ?? "{}")?.state?.theme;
    return saved === "light" || saved === "dark" || saved === "system" ? saved : undefined;
  } catch {
    return undefined;
  }
}

// Apply saved theme before render to prevent flash
const savedTheme = readSavedTheme();
if (savedTheme === "system") {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", prefersDark ? "dark" : "light");
} else if (savedTheme) {
  document.documentElement.setAttribute("data-theme", savedTheme);
}

function ReactiveToaster() {
  const theme = useAppStore((s) => s.theme);
  const resolved =
    theme === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : theme;
  return (
    <Toaster
      position="bottom-right"
      theme={resolved}
      toastOptions={{
        style: {
          background: "var(--color-bg-surface)",
          border: "1px solid var(--color-border-default)",
          color: "var(--color-fg-primary)",
        },
      }}
    />
  );
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppRouter />
      <ReactiveToaster />
    </QueryClientProvider>
  </StrictMode>,
);
