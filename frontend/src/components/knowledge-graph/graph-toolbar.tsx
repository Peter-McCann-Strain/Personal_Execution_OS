import type { ReactNode } from "react";
import { Search, Network, GitBranch, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EntityType } from "@/types";

export type LayoutType = "force" | "hierarchical" | "circular";

const LAYOUT_OPTIONS: Array<{ value: LayoutType; label: string; icon: ReactNode }> = [
  { value: "force", label: "Force", icon: <Network className="h-3.5 w-3.5" /> },
  { value: "hierarchical", label: "Hierarchy", icon: <GitBranch className="h-3.5 w-3.5" /> },
  { value: "circular", label: "Circular", icon: <Circle className="h-3.5 w-3.5" /> },
];

const ENTITY_TYPE_FILTERS: Array<{ value: EntityType; label: string; color: string }> = [
  { value: "PERSON", label: "Person", color: "var(--color-agent-memory)" },
  { value: "ORG", label: "Org", color: "var(--color-agent-comms)" },
  { value: "PLACE", label: "Place", color: "var(--color-success-500)" },
  { value: "CONCEPT", label: "Concept", color: "var(--color-agent-research)" },
];

interface GraphToolbarProps {
  layout: LayoutType;
  onLayoutChange: (layout: LayoutType) => void;
  enabledTypes: Set<EntityType>;
  onToggleType: (type: EntityType) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  depth: number;
  onDepthChange: (depth: number) => void;
  hasSelection: boolean;
  className?: string;
}

export function GraphToolbar({
  layout,
  onLayoutChange,
  enabledTypes,
  onToggleType,
  searchQuery,
  onSearchChange,
  depth,
  onDepthChange,
  hasSelection,
  className,
}: GraphToolbarProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-4 py-2.5",
        className,
      )}
    >
      {/* Layout toggle */}
      <div className="flex items-center gap-1 rounded-[var(--radius-md)] border border-[var(--color-border-default)] p-0.5">
        {LAYOUT_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onLayoutChange(opt.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 py-1 text-xs font-medium transition-colors",
              layout === opt.value
                ? "bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]"
                : "text-[var(--color-fg-secondary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]",
            )}
            aria-label={`${opt.label} layout`}
          >
            {opt.icon}
            <span className="hidden sm:inline">{opt.label}</span>
          </button>
        ))}
      </div>

      <div className="h-5 w-px bg-[var(--color-border-default)]" />

      {/* Entity type filters */}
      <div className="flex items-center gap-1.5">
        {ENTITY_TYPE_FILTERS.map((filter) => {
          const enabled = enabledTypes.has(filter.value);
          return (
            <button
              key={filter.value}
              type="button"
              onClick={() => onToggleType(filter.value)}
              className={cn(
                "inline-flex items-center gap-1 rounded-[var(--radius-full)] border px-2 py-0.5 text-[10px] font-medium transition-all",
                enabled
                  ? "border-[var(--color-border-strong)] text-[var(--color-fg-primary)]"
                  : "border-[var(--color-border-default)] text-[var(--color-fg-tertiary)] opacity-70 hover:opacity-100",
              )}
              aria-label={`${enabled ? "Hide" : "Show"} ${filter.label} nodes`}
              aria-pressed={enabled}
            >
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{
                  backgroundColor: enabled ? filter.color : "var(--color-fg-disabled)",
                }}
              />
              {filter.label}
            </button>
          );
        })}
      </div>

      <div className="h-5 w-px bg-[var(--color-border-default)]" />

      {/* Search */}
      <div className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1">
        <Search className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Find entity..."
          className="w-32 bg-transparent text-xs text-[var(--color-fg-primary)] placeholder:text-[var(--color-fg-tertiary)] focus:outline-none"
        />
      </div>

      <div className="h-5 w-px bg-[var(--color-border-default)]" />

      {/* Depth slider */}
      <div className="flex items-center gap-2">
        <label
          htmlFor="depth-slider"
          className={cn(
            "text-xs",
            hasSelection ? "text-[var(--color-fg-secondary)]" : "text-[var(--color-fg-disabled)]",
          )}
        >
          Depth: {depth}
        </label>
        <input
          id="depth-slider"
          type="range"
          min={1}
          max={3}
          value={depth}
          onChange={(e) => onDepthChange(Number(e.target.value))}
          disabled={!hasSelection}
          className={cn(
            "h-1.5 w-20 appearance-none rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]",
            "[&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-info-500)]",
            !hasSelection && "opacity-40",
          )}
        />
      </div>
    </div>
  );
}
