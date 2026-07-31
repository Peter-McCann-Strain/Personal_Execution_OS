import { cn } from "@/lib/utils";

// ─── Segmented Control ───────────────────────────────────────
// Reusable tab-style switcher used across filters, view toggles, etc.

interface SegmentedControlProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: readonly T[] | Array<{ value: T; label: string }>;
  label: string;
  size?: "sm" | "md";
  className?: string;
}

function isLabeledOption<T extends string>(
  opt: T | { value: T; label: string },
): opt is { value: T; label: string } {
  return typeof opt === "object" && "value" in opt;
}

function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "sm",
  className,
}: SegmentedControlProps<T>) {
  const sizeClasses = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm";

  return (
    <div
      className={cn(
        "flex rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] p-0.5",
        className,
      )}
      role="tablist"
      aria-label={label}
    >
      {options.map((opt) => {
        const optValue = isLabeledOption(opt) ? opt.value : opt;
        const optLabel = isLabeledOption(opt) ? opt.label : opt;
        const isSelected = value === optValue;

        return (
          <button
            key={optValue}
            onClick={() => onChange(optValue)}
            role="tab"
            aria-selected={isSelected}
            tabIndex={isSelected ? 0 : -1}
            className={cn(
              "rounded-[var(--radius-sm)] font-medium capitalize transition-colors",
              sizeClasses,
              isSelected
                ? "bg-[var(--color-bg-surface)] text-[var(--color-fg-primary)] shadow-sm"
                : "text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)]",
            )}
          >
            {optLabel}
          </button>
        );
      })}
    </div>
  );
}

export { SegmentedControl };
export type { SegmentedControlProps };
