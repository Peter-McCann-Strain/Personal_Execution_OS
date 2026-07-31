import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface FollowUpPillsProps {
  suggestions: string[];
  onSelect: (query: string) => void;
  className?: string;
}

export function FollowUpPills({ suggestions, onSelect, className }: FollowUpPillsProps) {
  if (suggestions.length === 0) return null;

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-fg-tertiary)]">
        <Sparkles className="h-3 w-3" />
        Follow-up questions
      </div>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onSelect(suggestion)}
            className={cn(
              "rounded-[var(--radius-full)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-1.5 text-sm text-[var(--color-fg-secondary)] transition-colors",
              "hover:border-[var(--color-info-500)] hover:bg-[var(--color-info-50)] hover:text-[var(--color-info-900)]",
            )}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
