import { useCallback } from "react";
import { cn } from "@/lib/utils";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { CommitmentStatus } from "@/types";

// ─── Tab View Type ──────────────────────────────────────────

export type CommitmentTab = "open" | "overdue" | "all";

// ─── Tab Options ────────────────────────────────────────────

interface TabOption {
  value: CommitmentTab;
  label: string;
}

function buildTabOptions(overdueCount: number): TabOption[] {
  return [
    { value: "open", label: "Open" },
    {
      value: "overdue",
      label: overdueCount > 0 ? `Overdue (${overdueCount})` : "Overdue",
    },
    { value: "all", label: "All" },
  ];
}

// ─── Status Filter Chips ────────────────────────────────────

const STATUS_CHIPS: { value: CommitmentStatus; label: string }[] = [
  { value: "detected", label: "Detected" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

// ─── CommitmentFilters Component ────────────────────────────

interface CommitmentFiltersProps {
  activeTab: CommitmentTab;
  onTabChange: (tab: CommitmentTab) => void;
  selectedStatuses: CommitmentStatus[];
  onStatusToggle: (status: CommitmentStatus) => void;
  overdueCount: number;
}

function CommitmentFilters({
  activeTab,
  onTabChange,
  selectedStatuses,
  onStatusToggle,
  overdueCount,
}: CommitmentFiltersProps) {
  const tabOptions = buildTabOptions(overdueCount);

  const handleStatusClick = useCallback(
    (status: CommitmentStatus) => {
      onStatusToggle(status);
    },
    [onStatusToggle],
  );

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      {/* Tab selector */}
      <SegmentedControl
        value={activeTab}
        onChange={onTabChange}
        options={tabOptions}
        label="Commitment view filter"
        size="md"
      />

      {/* Status filter chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
          Status
        </span>
        {STATUS_CHIPS.map((chip) => (
          <button
            key={chip.value}
            onClick={() => handleStatusClick(chip.value)}
            className={cn(
              "rounded-[var(--radius-full)] border px-2.5 py-0.5 text-xs font-medium transition-colors",
              selectedStatuses.includes(chip.value)
                ? "border-[var(--color-info-500)] bg-[var(--color-info-50)] text-[var(--color-info-900)]"
                : "border-[var(--color-border-default)] text-[var(--color-fg-secondary)] hover:border-[var(--color-border-strong)]",
            )}
          >
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export { CommitmentFilters };
export type { CommitmentFiltersProps };
