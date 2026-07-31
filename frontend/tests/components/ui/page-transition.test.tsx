import { describe, it, expect } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { PageTransition } from "@/components/ui/page-transition";

describe("PageTransition", () => {
  it("renders children", () => {
    renderWithProviders(
      <PageTransition>
        <div data-testid="child">Hello</div>
      </PageTransition>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = renderWithProviders(
      <PageTransition className="custom-class">
        <span>Content</span>
      </PageTransition>,
    );
    expect(container.querySelector(".custom-class")).toBeInTheDocument();
  });
});
