import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { SegmentedControl } from "@/components/ui/segmented-control";

describe("SegmentedControl", () => {
  it("renders labeled options, applies the md size, and changes the selected tab", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    renderWithProviders(
      <SegmentedControl
        value="weekly"
        onChange={onChange}
        options={[
          { value: "daily", label: "Daily" },
          { value: "weekly", label: "Weekly" },
        ]}
        label="Review cadence"
        size="md"
        className="custom-tabs"
      />,
    );

    const weekly = screen.getByRole("tab", { name: "Weekly" });
    const daily = screen.getByRole("tab", { name: "Daily" });

    expect(screen.getByRole("tablist", { name: "Review cadence" })).toHaveClass("custom-tabs");
    expect(weekly).toHaveAttribute("aria-selected", "true");
    expect(weekly).toHaveClass("px-3", "py-1.5", "text-sm");
    expect(daily).toHaveAttribute("aria-selected", "false");

    await user.click(daily);
    expect(onChange).toHaveBeenCalledWith("daily");
  });

  it("supports plain string options with the default small size", () => {
    renderWithProviders(
      <SegmentedControl
        value="all"
        onChange={vi.fn()}
        options={["all", "active", "done"]}
        label="Task filter"
      />,
    );

    expect(screen.getByRole("tab", { name: "all" })).toHaveClass("px-2.5", "py-1", "text-xs");
    expect(screen.getByRole("tab", { name: "active" })).toHaveAttribute("tabindex", "-1");
  });
});
