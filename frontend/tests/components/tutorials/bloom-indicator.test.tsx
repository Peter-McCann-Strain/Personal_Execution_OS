import { describe, expect, it } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import {
  BloomBadge,
  BloomIndicator,
  BloomProgressionBar,
} from "@/components/tutorials/bloom-indicator";
import { bloomColor, bloomLevelIndex } from "@/components/tutorials/bloom-utils";

describe("Bloom indicator helpers", () => {
  it("maps bloom levels to stable indexes and colors", () => {
    expect(bloomLevelIndex("remember")).toBe(0);
    expect(bloomLevelIndex("create")).toBe(5);
    expect(bloomColor("evaluate")).toBe("var(--color-info-500)");
    expect(bloomColor("not-a-level" as never)).toBe("var(--color-fg-tertiary)");
  });
});

describe("BloomIndicator", () => {
  it("renders labeled steps and highlights the current level", () => {
    const { container } = renderWithProviders(<BloomIndicator current="analyze" />);

    expect(screen.getByText("Remember")).toBeInTheDocument();
    expect(screen.getByText("Analyze")).toBeInTheDocument();
    expect(container.querySelectorAll(".ring-2").length).toBe(1);
  });

  it("renders compact progression without labels", () => {
    const { container } = renderWithProviders(
      <BloomIndicator current="understand" compact showLabels={false} />,
    );

    expect(screen.queryByText("Remember")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[title]").length).toBe(6);
  });

  it("renders the inactive state when no current level is available", () => {
    const { container } = renderWithProviders(
      <BloomIndicator current={null} compact showLabels={false} />,
    );

    expect(container.querySelectorAll("[title]").length).toBe(6);
    expect(container.querySelectorAll(".opacity-20").length).toBe(6);
  });
});

describe("BloomProgressionBar", () => {
  it("renders the start to end range", () => {
    const { container } = renderWithProviders(
      <BloomProgressionBar start="understand" end="evaluate" />,
    );

    expect(container.querySelectorAll("div").length).toBeGreaterThan(0);
    expect(screen.getByTitle("Understand")).toBeInTheDocument();
    expect(screen.getByTitle("Evaluate")).toBeInTheDocument();
  });

  it("renders the inactive range when no bounds are available", () => {
    const { container } = renderWithProviders(<BloomProgressionBar start={null} end={null} />);

    expect(container.querySelectorAll("[title]").length).toBe(6);
  });
});

describe("BloomBadge", () => {
  it("renders the label for the provided level", () => {
    renderWithProviders(<BloomBadge level="apply" />);

    expect(screen.getByText("Apply")).toBeInTheDocument();
  });

  it("returns nothing for an invalid level", () => {
    const { container } = renderWithProviders(<BloomBadge level={"invalid" as never} />);

    expect(container).toBeEmptyDOMElement();
  });
});
