import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { EntityNode } from "@/components/knowledge-graph/entity-node";

vi.mock("@xyflow/react", () => ({
  Handle: ({ type }: { type: string }) => <div data-testid={`handle-${type}`} />,
  Position: {
    Top: "top",
    Bottom: "bottom",
  },
}));

describe("EntityNode", () => {
  it("renders a person node with initials and both handles", () => {
    renderWithProviders(
      <EntityNode
        id="node-1"
        selected
        data={{
          label: "Ada Lovelace",
          entityType: "PERSON",
          mentionCount: 20,
          canonicalName: null,
        }}
        dragging={false}
        zIndex={1}
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        xPos={0}
        yPos={0}
        type="entity"
      />,
    );

    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("AL")).toBeInTheDocument();
    expect(screen.getByTestId("handle-target")).toBeInTheDocument();
    expect(screen.getByTestId("handle-source")).toBeInTheDocument();
  });

  it("renders non-person nodes with the correct label", () => {
    renderWithProviders(
      <EntityNode
        id="node-2"
        selected={false}
        data={{
          label: "Analytical Engine",
          entityType: "CONCEPT",
          mentionCount: 3,
          canonicalName: null,
        }}
        dragging={false}
        zIndex={1}
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        xPos={0}
        yPos={0}
        type="entity"
      />,
    );

    expect(screen.getByText("Analytical Engine")).toBeInTheDocument();
  });

  it("renders org and place nodes with their alternate shapes", () => {
    const { rerender } = renderWithProviders(
      <EntityNode
        id="node-3"
        selected={false}
        data={{
          label: "Analytical Society",
          entityType: "ORG",
          mentionCount: 80,
          canonicalName: null,
        }}
        dragging={false}
        zIndex={1}
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        xPos={0}
        yPos={0}
        type="entity"
      />,
    );

    expect(screen.getByText("Analytical Society")).toBeInTheDocument();

    rerender(
      <EntityNode
        id="node-4"
        selected={false}
        data={{
          label: "London",
          entityType: "PLACE",
          mentionCount: 1,
          canonicalName: null,
        }}
        dragging={false}
        zIndex={1}
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        xPos={0}
        yPos={0}
        type="entity"
      />,
    );

    expect(screen.getByText("London")).toBeInTheDocument();
    expect(screen.getByTestId("handle-target")).toBeInTheDocument();
    expect(screen.getByTestId("handle-source")).toBeInTheDocument();
  });
});
