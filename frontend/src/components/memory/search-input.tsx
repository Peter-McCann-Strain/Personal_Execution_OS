import { useRef, useEffect, type KeyboardEvent } from "react";
import { Search, X, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading?: boolean;
  className?: string;
}

export function SearchInput({
  value,
  onChange,
  onSubmit,
  loading = false,
  className,
}: SearchInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && value.trim()) {
      onSubmit();
    }
  }

  function handleClear() {
    onChange("");
    inputRef.current?.focus();
  }

  return (
    <div className={cn("relative w-full max-w-2xl", className)}>
      <div
        className={cn(
          "flex items-center gap-3 rounded-[var(--radius-xl)] border-2 bg-[var(--color-bg-surface)] px-4 py-3 transition-colors",
          "border-[var(--color-border-default)] focus-within:border-[var(--color-border-focus)]",
          "shadow-sm focus-within:shadow-md",
        )}
      >
        <Search
          className={cn(
            "h-5 w-5 shrink-0",
            loading
              ? "animate-pulse text-[var(--color-info-500)]"
              : "text-[var(--color-fg-tertiary)]",
          )}
        />
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything about your notes, diary, or knowledge..."
          className="flex-1 bg-transparent text-lg text-[var(--color-fg-primary)] placeholder:text-[var(--color-fg-tertiary)] focus:outline-none"
          disabled={loading}
        />
        {value && (
          <button
            type="button"
            onClick={handleClear}
            className="shrink-0 rounded-[var(--radius-full)] p-1 text-[var(--color-fg-tertiary)] transition-colors hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
        <button
          type="button"
          onClick={onSubmit}
          disabled={!value.trim() || loading}
          className={cn(
            "shrink-0 rounded-[var(--radius-full)] p-2 transition-colors",
            value.trim() && !loading
              ? "bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)] hover:bg-[var(--color-info-600)]"
              : "bg-[var(--color-bg-overlay)] text-[var(--color-fg-disabled)] cursor-not-allowed",
          )}
          aria-label="Search"
        >
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
