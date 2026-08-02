import { Link } from "react-router";
import { Brain, ExternalLink } from "lucide-react";

function getSourceRepositoryUrl(): string | null {
  const configured = (import.meta.env.VITE_SOURCE_REPOSITORY_URL as string | undefined)?.trim();
  if (!configured) return null;
  try {
    const url = new URL(configured);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

const sourceRepositoryUrl = getSourceRepositoryUrl();

export function LandingFooter() {
  return (
    <footer className="border-t border-[var(--color-border-subtle)] py-8 px-6">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <div
            className="w-6 h-6 rounded-[var(--radius-sm)] flex items-center justify-center"
            style={{
              background: "linear-gradient(135deg, oklch(0.55 0.18 250), oklch(0.5 0.2 290))",
            }}
          >
            <Brain className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-xs text-[var(--color-fg-tertiary)]">
            Personal Execution OS -- self-hosted workspace
          </span>
        </div>

        <div className="flex items-center gap-6">
          <Link
            to="/dashboard"
            className="text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)] transition-colors"
          >
            Dashboard
          </Link>
          <Link
            to="/settings"
            className="text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)] transition-colors"
          >
            Settings
          </Link>
          {sourceRepositoryUrl && (
            <a
              href={sourceRepositoryUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)] transition-colors"
            >
              Source
              <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      </div>
    </footer>
  );
}
