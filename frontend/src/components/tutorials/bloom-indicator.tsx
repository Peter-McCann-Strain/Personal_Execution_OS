import { cn } from "@/lib/utils";
import { BLOOM_LEVELS, bloomLevelIndex } from "./bloom-utils";
import type { BloomLevel } from "@/api/tutorials";

// ─── Stepper Variant ────────────────────────────────────────

interface BloomIndicatorProps {
  current: BloomLevel | null;
  className?: string;
  /** Show labels below each step */
  showLabels?: boolean;
  /** Compact single-line mode */
  compact?: boolean;
}

function BloomIndicator({
  current,
  className,
  showLabels = true,
  compact = false,
}: BloomIndicatorProps) {
  const currentIndex = current ? bloomLevelIndex(current) : -1;

  if (compact) {
    return (
      <div className={cn("flex items-center gap-1", className)}>
        {BLOOM_LEVELS.map((bloom, i) => (
          <div
            key={bloom.level}
            className={cn(
              "h-1.5 flex-1 rounded-[var(--radius-full)] transition-colors duration-300",
              i <= currentIndex ? "opacity-100" : "opacity-20",
            )}
            style={{
              backgroundColor: bloom.color,
            }}
            title={bloom.label}
          />
        ))}
      </div>
    );
  }

  return (
    <div className={cn("flex items-start gap-1", className)}>
      {BLOOM_LEVELS.map((bloom, i) => {
        const isActive = i <= currentIndex;
        const isCurrent = i === currentIndex;

        return (
          <div key={bloom.level} className="flex flex-1 flex-col items-center gap-1.5">
            {/* Step dot + connector */}
            <div className="flex w-full items-center">
              {i > 0 && (
                <div
                  className="h-0.5 flex-1 transition-colors duration-300"
                  style={{
                    backgroundColor: isActive ? bloom.color : "var(--color-border-subtle)",
                  }}
                />
              )}
              <div
                className={cn(
                  "shrink-0 rounded-full transition-all duration-300",
                  isCurrent ? "h-3 w-3 ring-2 ring-offset-1" : "h-2.5 w-2.5",
                )}
                style={{
                  backgroundColor: isActive ? bloom.color : "var(--color-bg-overlay)",
                  borderColor: isActive ? bloom.color : "var(--color-border-default)",
                  ...(isCurrent
                    ? {
                        boxShadow: `0 0 0 2px var(--color-bg-base), 0 0 0 4px ${bloom.color}`,
                      }
                    : {}),
                }}
              />
              {i < BLOOM_LEVELS.length - 1 && (
                <div
                  className="h-0.5 flex-1 transition-colors duration-300"
                  style={{
                    backgroundColor:
                      i < currentIndex ? BLOOM_LEVELS[i + 1].color : "var(--color-border-subtle)",
                  }}
                />
              )}
            </div>
            {/* Label */}
            {showLabels && (
              <span
                className={cn(
                  "text-[10px] font-medium leading-tight transition-colors duration-300",
                  isActive ? "text-[var(--color-fg-primary)]" : "text-[var(--color-fg-disabled)]",
                )}
              >
                {bloom.label}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Progression Bar (start → end) ─────────────────────────

interface BloomProgressionBarProps {
  start: BloomLevel | null;
  end: BloomLevel | null;
  className?: string;
}

function BloomProgressionBar({ start, end, className }: BloomProgressionBarProps) {
  const startIdx = start ? bloomLevelIndex(start) : -1;
  const endIdx = end ? bloomLevelIndex(end) : -1;

  return (
    <div className={cn("flex items-center gap-0.5", className)}>
      {BLOOM_LEVELS.map((bloom, i) => {
        const inRange = i >= startIdx && i <= endIdx;
        const isStart = i === startIdx;
        const isEnd = i === endIdx;

        return (
          <div
            key={bloom.level}
            className={cn(
              "h-2 flex-1 transition-all duration-300",
              isStart && "rounded-l-[var(--radius-full)]",
              isEnd && "rounded-r-[var(--radius-full)]",
              !inRange && "rounded-[var(--radius-full)]",
            )}
            style={{
              backgroundColor: inRange ? bloom.color : "var(--color-bg-overlay)",
              opacity: inRange ? 1 : 0.3,
            }}
            title={bloom.label}
          />
        );
      })}
    </div>
  );
}

// ─── Bloom Badge ────────────────────────────────────────────

interface BloomBadgeProps {
  level: BloomLevel;
  className?: string;
}

function BloomBadge({ level, className }: BloomBadgeProps) {
  const config = BLOOM_LEVELS[bloomLevelIndex(level)];
  if (!config) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[var(--radius-full)] border px-2 py-0.5 text-xs font-medium capitalize",
        className,
      )}
      style={{
        color: config.color,
        backgroundColor: config.bgColor,
        borderColor: `color-mix(in oklch, ${config.borderColor} 30%, transparent)`,
      }}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: config.color }}
      />
      {config.label}
    </span>
  );
}

export { BloomIndicator, BloomProgressionBar, BloomBadge };
export type { BloomIndicatorProps, BloomProgressionBarProps, BloomBadgeProps };
