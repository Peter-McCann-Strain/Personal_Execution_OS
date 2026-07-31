import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { CommitmentFilters } from "@/components/commitments/commitment-filters";

vi.mock("@/components/ui/segmented-control", () => ({
  SegmentedControl: ({
    label,
    onChange,
    options,
    value,
  }: {
    label: string;
    onChange: (value: "open" | "overdue" | "all") => void;
    options: Array<{ label: string; value: "open" | "overdue" | "all" }>;
    value: "open" | "overdue" | "all";
  }) => (
    <div aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  ),
}));

describe("CommitmentFilters", () => {
  it("renders tab labels with overdue counts and toggles status chips", async () => {
    const user = userEvent.setup();
    const onTabChange = vi.fn();
    const onStatusToggle = vi.fn();

    renderWithProviders(
      <CommitmentFilters
        activeTab="open"
        onTabChange={onTabChange}
        selectedStatuses={["acknowledged"]}
        onStatusToggle={onStatusToggle}
        overdueCount={3}
      />,
    );

    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Overdue (3)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Overdue (3)" }));
    await user.click(screen.getByRole("button", { name: "Completed" }));

    expect(onTabChange).toHaveBeenCalledWith("overdue");
    expect(onStatusToggle).toHaveBeenCalledWith("completed");
  });
});
