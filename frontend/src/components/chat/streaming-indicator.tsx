import { cn } from "@/lib/utils";

interface StreamingIndicatorProps {
  className?: string;
}

export function StreamingIndicator({ className }: StreamingIndicatorProps) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)} aria-label="Processing">
      <span
        className="h-1.5 w-1.5 rounded-full bg-[var(--color-fg-tertiary)] animate-bounce"
        style={{ animationDelay: "0ms", animationDuration: "1.2s" }}
      />
      <span
        className="h-1.5 w-1.5 rounded-full bg-[var(--color-fg-tertiary)] animate-bounce"
        style={{ animationDelay: "200ms", animationDuration: "1.2s" }}
      />
      <span
        className="h-1.5 w-1.5 rounded-full bg-[var(--color-fg-tertiary)] animate-bounce"
        style={{ animationDelay: "400ms", animationDuration: "1.2s" }}
      />
    </span>
  );
}
