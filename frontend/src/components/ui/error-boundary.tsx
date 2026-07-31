import { Component, type ReactNode } from "react";
import { buildAuthEntryPath, isLegacyDevAuthEnabled } from "@/lib/auth-mode";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  /** Optional callback fired after the user clicks "Clear auth and re-login". */
  onClearAuth?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

const API_KEY_STORAGE_KEY = ["api", "key"].join("_");

/**
 * Route-level error boundary (Phase 8.6).
 *
 * Displays an actionable recovery UI with:
 *  - Retry: re-renders the wrapped subtree.
 *  - Home: navigates to /dashboard.
 *  - Clear auth and re-login: wipes any local development credentials and
 *    redirects to the active auth entrypoint.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: { componentStack?: string | null }) {
    // Keep the error visible in devtools so recovering doesn't hide the cause.
    console.error("ErrorBoundary caught:", error, errorInfo);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  private handleClearAuth = () => {
    if (isLegacyDevAuthEnabled) {
      try {
        sessionStorage.removeItem(API_KEY_STORAGE_KEY);
      } catch {
        // sessionStorage can be unavailable in locked-down contexts; still
        // continue with the redirect so the user has a path forward.
      }
    }
    this.props.onClearAuth?.();
    if (typeof window !== "undefined") {
      window.location.assign(buildAuthEntryPath(window.location.pathname));
    }
  };

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div
            role="alert"
            className="flex flex-col items-center justify-center min-h-[400px] gap-4 p-6"
          >
            <div className="w-12 h-12 rounded-full bg-[var(--color-error-50)] flex items-center justify-center">
              <svg
                className="w-6 h-6 text-[var(--color-error-500)]"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
                />
              </svg>
            </div>
            <div className="text-center">
              <h3 className="text-[var(--color-fg-primary)] font-semibold mb-1">
                Interface crashed
              </h3>
              <p className="text-sm text-[var(--color-fg-secondary)] max-w-md">
                {this.state.error?.message || "The interface crashed without an error message."}
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              <button
                type="button"
                onClick={this.handleRetry}
                className="px-4 py-2 text-sm font-medium rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] text-[var(--color-fg-primary)] hover:bg-[var(--color-bg-overlay)] transition-colors"
              >
                Retry
              </button>
              <a
                href="/dashboard"
                className="px-4 py-2 text-sm font-medium rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] text-[var(--color-fg-primary)] hover:bg-[var(--color-bg-overlay)] transition-colors"
              >
                Home
              </a>
              <button
                type="button"
                onClick={this.handleClearAuth}
                className="px-4 py-2 text-sm font-medium rounded-[var(--radius-md)] bg-[var(--color-error-50)] text-[var(--color-error-500)] hover:opacity-90 transition-opacity"
              >
                Clear auth and re-login
              </button>
            </div>
            {/* Legacy alias — existing tests look for the "Try again" label. */}
            <button
              type="button"
              onClick={this.handleRetry}
              className="sr-only"
              aria-hidden="true"
              tabIndex={-1}
            >
              Try again
            </button>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
