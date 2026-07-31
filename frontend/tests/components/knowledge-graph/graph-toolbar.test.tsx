import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { GraphToolbar } from "@/components/knowledge-graph/graph-toolbar";

describe("GraphToolbar", () => {
  it("forwards layout, type, search, and depth changes", async () => {
    const user = userEvent.setup();
    const onLayoutChange = vi.fn();
    const onToggleType = vi.fn();
    const onSearchChange = vi.fn();
    const onDepthChange = vi.fn();

    renderWithProviders(
      <GraphToolbar
        layout="force"
        onLayoutChange={onLayoutChange}
        enabledTypes={new Set(["PERSON", "ORG"])}
        onToggleType={onToggleType}
        searchQuery=""
        onSearchChange={onSearchChange}
        depth={2}
        onDepthChange={onDepthChange}
        hasSelection
      />,
    );

    await user.click(screen.getByRole("button", { name: "Hierarchy layout" }));
    expect(onLayoutChange).toHaveBeenCalledWith("hierarchical");

    await user.click(screen.getByRole("button", { name: "Hide Person nodes" }));
    await user.click(screen.getByRole("button", { name: "Show Place nodes" }));
    expect(onToggleType).toHaveBeenNthCalledWith(1, "PERSON");
    expect(onToggleType).toHaveBeenNthCalledWith(2, "PLACE");

    fireEvent.change(screen.getByPlaceholderText("Find entity..."), {
      target: { value: "Ada" },
    });
    expect(onSearchChange).toHaveBeenLastCalledWith("Ada");

    fireEvent.change(screen.getByLabelText("Depth: 2"), {
      target: { value: "3" },
    });
    expect(onDepthChange).toHaveBeenCalledWith(3);
  });

  it("disables the depth slider when there is no selection", () => {
    renderWithProviders(
      <GraphToolbar
        layout="force"
        onLayoutChange={vi.fn()}
        enabledTypes={new Set(["PERSON"])}
        onToggleType={vi.fn()}
        searchQuery=""
        onSearchChange={vi.fn()}
        depth={1}
        onDepthChange={vi.fn()}
        hasSelection={false}
      />,
    );

    expect(screen.getByLabelText("Depth: 1")).toBeDisabled();
  });
});
