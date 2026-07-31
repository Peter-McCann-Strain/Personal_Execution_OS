import { describe, it, expect } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { StaggerList } from "@/components/ui/stagger-list";

describe("StaggerList", () => {
  it("renders all children", () => {
    renderWithProviders(
      <StaggerList className="grid">
        {[<div key="a">Item A</div>, <div key="b">Item B</div>, <div key="c">Item C</div>]}
      </StaggerList>,
    );
    expect(screen.getByText("Item A")).toBeInTheDocument();
    expect(screen.getByText("Item B")).toBeInTheDocument();
    expect(screen.getByText("Item C")).toBeInTheDocument();
  });

  it("applies container className", () => {
    const { container } = renderWithProviders(
      <StaggerList className="my-grid-class">{[<div key="a">A</div>]}</StaggerList>,
    );
    expect(container.querySelector(".my-grid-class")).toBeInTheDocument();
  });

  it("renders empty array without crashing", () => {
    const { container } = renderWithProviders(<StaggerList>{[]}</StaggerList>);
    expect(container).toBeTruthy();
  });

  it("accepts a custom stagger duration", () => {
    const { container } = renderWithProviders(
      <StaggerList staggerMs={120} className="custom-stagger">
        {[<div key="only">Only item</div>]}
      </StaggerList>,
    );

    expect(screen.getByText("Only item")).toBeInTheDocument();
    expect(container.querySelector(".custom-stagger")).toBeInTheDocument();
  });
});
