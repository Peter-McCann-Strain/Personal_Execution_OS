import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { Navigate, useLocation } from "react-router";
import { getCurrentSession, getSetupStatus } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { buildLoginPath, buildSetupPath, isLegacyDevAuthEnabled } from "@/lib/auth-mode";
import { useAppStore } from "@/stores/app";

type SessionGateState = "checking" | "authenticated" | "unauthenticated" | "first-run" | "error";

function LegacyDevAuthGate({ children }: { children: ReactNode }) {
  const location = useLocation();
  const apiKey = useAppStore((state) => state.apiKey);
  if (!apiKey) {
    const returnTo = `${location.pathname}${location.search}`;
    return <Navigate to={buildSetupPath(returnTo)} replace />;
  }
  return <>{children}</>;
}

function ServerSessionGate({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [state, setState] = useState<SessionGateState>("checking");
  const [attempt, setAttempt] = useState(0);
  const returnTo = `${location.pathname}${location.search}`;

  const retry = useCallback(() => {
    setState("checking");
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    let active = true;
    getSetupStatus()
      .then(async (status) => {
        if (!active) return;
        if (!status.initialized) {
          setState("first-run");
          return;
        }
        try {
          await getCurrentSession();
          if (active) setState("authenticated");
        } catch (error) {
          if (!active) return;
          setState(error instanceof ApiError && error.status === 401 ? "unauthenticated" : "error");
        }
      })
      .catch(() => {
        if (active) setState("error");
      });
    return () => {
      active = false;
    };
  }, [attempt]);

  if (state === "first-run") {
    return <Navigate to={buildSetupPath(returnTo)} replace />;
  }
  if (state === "unauthenticated") {
    return <Navigate to={buildLoginPath(returnTo)} replace />;
  }
  if (state === "error") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-[var(--color-bg-base)] px-4">
        <div
          role="alert"
          className="flex max-w-md flex-col items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--color-error-500)]/40 bg-[var(--color-bg-surface)] p-6 text-center"
        >
          <AlertCircle className="h-6 w-6 text-[var(--color-error-500)]" />
          <p className="text-sm font-medium text-[var(--color-fg-primary)]">
            Could not verify your session
          </p>
          <p className="text-xs text-[var(--color-fg-secondary)]">
            Check that the backend is running, then try again.
          </p>
          <Button type="button" variant="outline" onClick={retry}>
            Retry
          </Button>
        </div>
      </div>
    );
  }
  if (state !== "authenticated") {
    return (
      <div
        className="flex min-h-dvh items-center justify-center bg-[var(--color-bg-base)]"
        role="status"
        aria-label="Checking session"
      >
        <Loader2 className="h-6 w-6 animate-spin text-[var(--color-fg-tertiary)]" />
      </div>
    );
  }
  return <>{children}</>;
}

function AuthGate({ children }: { children: ReactNode }) {
  return isLegacyDevAuthEnabled ? (
    <LegacyDevAuthGate>{children}</LegacyDevAuthGate>
  ) : (
    <ServerSessionGate>{children}</ServerSessionGate>
  );
}

export { AuthGate };
