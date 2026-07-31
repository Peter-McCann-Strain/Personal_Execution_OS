import type { LucideIcon } from "lucide-react";
import { RefreshCw } from "lucide-react";
import { motion } from "motion/react";
import { Button } from "./button";
import { classifyError } from "./page-error.utils";

interface PageErrorProps {
  /** The raw error message from the API call */
  message?: string;
  /** Retry handler */
  onRetry?: () => void;
  /** Optional page icon to show alongside the error */
  icon?: LucideIcon;
  /** Human-friendly context, e.g. "your habits" or "diary entries" */
  context?: string;
}

function PageError({ message, onRetry, icon: PageIcon, context }: PageErrorProps) {
  const classified = classifyError(message);
  const ErrorIcon = classified.icon;
  const contextMsg = context ? `Couldn't load ${context}.` : "";
  const detail = message?.trim() || "An unexpected error occurred.";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex flex-col items-center justify-center min-h-[400px] gap-5 px-4"
    >
      <div className="relative">
        <div className="w-16 h-16 rounded-full bg-[var(--color-error-50)] flex items-center justify-center">
          <ErrorIcon className="w-7 h-7 text-[var(--color-error-500)]" />
        </div>
        {PageIcon && (
          <div className="absolute -bottom-1 -right-1 w-7 h-7 rounded-full bg-[var(--color-bg-surface)] border-2 border-[var(--color-border-default)] flex items-center justify-center">
            <PageIcon className="w-3.5 h-3.5 text-[var(--color-fg-tertiary)]" />
          </div>
        )}
      </div>
      <div className="text-center max-w-sm">
        <h3 className="text-base font-semibold text-[var(--color-fg-primary)] mb-1">
          {classified.title}
        </h3>
        {contextMsg && (
          <p className="text-sm text-[var(--color-fg-secondary)] mb-1">{contextMsg}</p>
        )}
        <p className="text-sm text-[var(--color-fg-tertiary)]">{detail}</p>
        {classified.hint && (
          <p className="mt-1 text-xs text-[var(--color-fg-muted)]">{classified.hint}</p>
        )}
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="gap-2">
          <RefreshCw className="w-3.5 h-3.5" />
          Try again
        </Button>
      )}
    </motion.div>
  );
}

export { PageError };
export type { PageErrorProps };
