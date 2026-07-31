import type { LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { Button } from "./button";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  /** Optional secondary link, e.g. "Learn more in Tutorials" */
  secondaryAction?: {
    label: string;
    onClick: () => void;
  };
}

function EmptyState({ icon: Icon, title, description, action, secondaryAction }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="flex flex-col items-center justify-center py-16 px-4 text-center"
    >
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1, duration: 0.4 }}
        className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-[var(--color-bg-overlay)]"
      >
        <Icon className="h-7 w-7 text-[var(--color-fg-tertiary)]" />
      </motion.div>
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.2, duration: 0.3 }}
        className="text-base font-medium text-[var(--color-fg-secondary)]"
      >
        {title}
      </motion.p>
      {description && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.25, duration: 0.3 }}
          className="mt-1.5 text-sm text-[var(--color-fg-tertiary)] max-w-xs"
        >
          {description}
        </motion.p>
      )}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35, duration: 0.3 }}
        className="mt-5 flex items-center gap-3"
      >
        {action && (
          <Button variant="default" size="sm" onClick={action.onClick}>
            {action.label}
          </Button>
        )}
        {secondaryAction && (
          <Button variant="ghost" size="sm" onClick={secondaryAction.onClick}>
            {secondaryAction.label}
          </Button>
        )}
      </motion.div>
    </motion.div>
  );
}

export { EmptyState };
export type { EmptyStateProps };
