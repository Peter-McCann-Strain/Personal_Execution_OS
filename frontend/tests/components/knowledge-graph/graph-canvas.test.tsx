import { describe, expect, it, beforeEach, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { GraphCanvas } from "@/components/knowledge-graph/graph-canvas";
import type { Entity, EntityRelationship } from "@/types";

vi.mock("@xyflow/react", async () => {
  const React = await vi.importActual<typeof import("react")>("react");

  function ReactFlow({
    nodes,
    edges,
    onNodeClick,
    onPaneClick,
    children,
  }: {
    nodes: Array<Record<string, unknown>>;
    edges: Array<Record<string, unknown>>;
    onNodeClick?: (event: MouseEvent, node: Record<string, unknown>) => void;
    onPaneClick?: () => void;
    children?: React.ReactNode;
  }) {
    return (
      <div>
        <div data-testid="node-count">{nodes.length}</div>
        <div data-testid="edge-count">{edges.length}</div>
        {nodes.map((node) => (
          <button
            key={String(node.id)}
            data-testid={`node-${String(node.id)}`}
            type="button"
            onClick={(event) => onNodeClick?.(event as unknown as MouseEvent, node)}
          >
            {[
              String(node.id),
              `${(node.position as { x: number; y: number }).x},${(node.position as { x: number; y: number }).y}`,
              String(node.selected),
              String((node.style as { filter?: string } | undefined)?.filter ?? "none"),
            ].join(" | ")}
          </button>
        ))}
        {edges.map((edge) => (
          <div key={String(edge.id)} data-testid={`edge-${String(edge.id)}`}>
            {[
              String(edge.id),
              `${String(edge.source)}->${String(edge.target)}`,
              String(edge.label),
              String((edge.style as { stroke?: string } | undefined)?.stroke ?? "none"),
              String(
                (edge.style as { strokeDasharray?: string } | undefined)?.strokeDasharray ??
                  "solid",
              ),
            ].join(" | ")}
          </div>
        ))}
        <button type="button" onClick={() => onPaneClick?.()}>
          Pane click
        </button>
        {children}
      </div>
    );
  }

  return {
    ReactFlow,
    MiniMap: () => <div>MiniMap</div>,
    Controls: () => <div>Controls</div>,
    Background: ({ variant }: { variant: string }) => <div>Background {variant}</div>,
    BackgroundVariant: { Dots: "dots" },
    useNodesState: (initialNodes: unknown[]) => {
      const [nodes, setNodes] = React.useState(initialNodes);
      return [nodes, setNodes, vi.fn()] as const;
    },
    useEdgesState: (initialEdges: unknown[]) => {
      const [edges, setEdges] = React.useState(initialEdges);
      return [edges, setEdges, vi.fn()] as const;
    },
  };
});

function createEntity(overrides: Partial<Entity> = {}): Entity {
  return {
    id: "entity-1",
    name: "Ada Lovelace",
    entity_type: "PERSON",
    canonical_name: null,
    mention_count: 12,
    first_seen: null,
    last_seen: null,
    metadata: {},
    created_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createRelationship(overrides: Partial<EntityRelationship> = {}): EntityRelationship {
  return {
    id: "rel-1",
    source_entity_id: "entity-1",
    target_entity_id: "entity-2",
    relationship_type: "works_at",
    valid_from: null,
    valid_to: null,
    ...overrides,
  };
}

describe("GraphCanvas", () => {
  beforeEach(() => {
    document.documentElement.style.setProperty("--color-fg-secondary", "rgb(1, 2, 3)");
    document.documentElement.style.setProperty("--color-fg-tertiary", "rgb(4, 5, 6)");
    document.documentElement.style.setProperty("--color-bg-surface", "rgb(7, 8, 9)");
    document.documentElement.style.setProperty("--color-agent-project", "rgb(10, 11, 12)");
    document.documentElement.style.setProperty("--color-success-500", "rgb(13, 14, 15)");
    document.documentElement.style.setProperty("--color-agent-comms", "rgb(16, 17, 18)");
  });

  it("filters hidden entity types, applies hierarchical positions, and maps edge styles", () => {
    const entities = [
      createEntity({
        id: "entity-1",
        name: "Ada Lovelace",
        entity_type: "PERSON",
      }),
      createEntity({
        id: "entity-2",
        name: "Analytical Society",
        entity_type: "ORG",
      }),
      createEntity({
        id: "entity-3",
        name: "London",
        entity_type: "PLACE",
      }),
    ];
    const relationships = [
      createRelationship({
        id: "rel-visible",
        source_entity_id: "entity-1",
        target_entity_id: "entity-2",
        relationship_type: "works_at",
      }),
      createRelationship({
        id: "rel-hidden",
        source_entity_id: "entity-2",
        target_entity_id: "entity-3",
        relationship_type: "located_in",
      }),
    ];

    renderWithProviders(
      <GraphCanvas
        entities={entities}
        relationships={relationships}
        layout="hierarchical"
        enabledTypes={new Set(["PERSON", "ORG"])}
        searchQuery="Ada"
        selectedEntityId="entity-1"
        onSelectEntity={vi.fn()}
      />,
    );

    expect(screen.getByTestId("node-count")).toHaveTextContent("2");
    expect(screen.getByTestId("edge-count")).toHaveTextContent("1");
    expect(screen.getByTestId("node-entity-1")).toHaveTextContent(
      "entity-1 | 0,200 | true | drop-shadow(0 0 10px var(--color-info-500))",
    );
    expect(screen.getByTestId("node-entity-2")).toHaveTextContent("entity-2 | 0,0 | false | none");
    expect(screen.getByTestId("edge-rel-visible")).toHaveTextContent(
      "rel-visible | entity-1->entity-2 | works_at | rgb(1, 2, 3) | solid",
    );
    expect(screen.queryByTestId("edge-rel-hidden")).not.toBeInTheDocument();
    expect(screen.getByText("Background dots")).toBeInTheDocument();
    expect(screen.getByText("MiniMap")).toBeInTheDocument();
    expect(screen.getByText("Controls")).toBeInTheDocument();
  });

  it("renders an empty graph when there are no entities", () => {
    renderWithProviders(
      <GraphCanvas
        entities={[]}
        relationships={[]}
        layout="hierarchical"
        enabledTypes={new Set(["PERSON"])}
        searchQuery=""
        selectedEntityId={null}
        onSelectEntity={vi.fn()}
      />,
    );

    expect(screen.getByTestId("node-count")).toHaveTextContent("0");
    expect(screen.getByTestId("edge-count")).toHaveTextContent("0");
  });

  it("forwards node and pane clicks and updates the rendered graph on rerender", async () => {
    const user = userEvent.setup();
    const onSelectEntity = vi.fn();
    const entities = [
      createEntity({
        id: "entity-1",
        name: "Ada Lovelace",
        entity_type: "PERSON",
      }),
      createEntity({
        id: "entity-2",
        name: "Charles Babbage",
        entity_type: "PERSON",
      }),
    ];
    const relationships = [
      createRelationship({
        id: "rel-force",
        source_entity_id: "entity-1",
        target_entity_id: "entity-2",
        relationship_type: "knows",
      }),
    ];

    const { rerender } = renderWithProviders(
      <GraphCanvas
        entities={entities}
        relationships={relationships}
        layout="force"
        enabledTypes={new Set(["PERSON"])}
        searchQuery=""
        selectedEntityId={null}
        onSelectEntity={onSelectEntity}
      />,
    );

    await user.click(screen.getByTestId("node-entity-1"));
    await user.click(screen.getByRole("button", { name: "Pane click" }));

    expect(onSelectEntity).toHaveBeenNthCalledWith(1, "entity-1");
    expect(onSelectEntity).toHaveBeenNthCalledWith(2, null);
    expect(screen.getByTestId("edge-rel-force")).toHaveTextContent(
      "rel-force | entity-1->entity-2 | knows | rgb(1, 2, 3) | 4 4",
    );

    rerender(
      <GraphCanvas
        entities={entities}
        relationships={relationships}
        layout="circular"
        enabledTypes={new Set(["PERSON"])}
        searchQuery="Charles"
        selectedEntityId="entity-2"
        onSelectEntity={onSelectEntity}
      />,
    );

    expect(screen.getByTestId("node-entity-2")).toHaveTextContent(
      "entity-2 | 200,400 | true | drop-shadow(0 0 10px var(--color-info-500))",
    );
  });

  it("falls back to default layout and edge styles for unusual graph data", () => {
    const entities = [
      createEntity({
        id: "entity-1",
        name: "Ada Lovelace",
        entity_type: "PERSON",
      }),
      createEntity({
        id: "entity-2",
        name: "Unknown Node",
        entity_type: "PERSON",
      }),
      createEntity({
        id: "entity-3",
        name: "Mystery Node",
        entity_type: "MYSTERY" as Entity["entity_type"],
      }),
    ];
    const relationships = [
      createRelationship({
        id: "rel-fallback",
        source_entity_id: "entity-1",
        target_entity_id: "entity-3",
        relationship_type: "collaborated_with",
      }),
    ];

    renderWithProviders(
      <GraphCanvas
        entities={entities}
        relationships={relationships}
        layout="hierarchical"
        enabledTypes={new Set(["PERSON", "MYSTERY" as never])}
        searchQuery="A"
        selectedEntityId="entity-3"
        onSelectEntity={vi.fn()}
      />,
    );

    expect(screen.getByTestId("node-count")).toHaveTextContent("3");
    expect(screen.getByTestId("node-entity-3")).toHaveTextContent(
      "entity-3 | 360,200 | true | none",
    );
    expect(screen.getByTestId("edge-rel-fallback")).toHaveTextContent(
      "rel-fallback | entity-1->entity-3 | collaborated_with | rgb(4, 5, 6) | 6 3",
    );
  });
});
