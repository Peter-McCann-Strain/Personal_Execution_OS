import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { KnowledgeGraphPage } from "@/pages/knowledge-graph";
import { useAppStore } from "@/stores/app";
import type { Entity, EntityRelationship } from "@/types";

const searchState = vi.hoisted(() => ({
  params: new URLSearchParams(),
  setSearchParams: vi.fn(),
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useSearchParams: () => [searchState.params, searchState.setSearchParams] as const,
  };
});

const mocks = vi.hoisted(() => ({
  getEntities: vi.fn(),
  getEntityRelationships: vi.fn(),
}));

vi.mock("@/api/memory", () => ({
  getEntities: mocks.getEntities,
  getEntityRelationships: mocks.getEntityRelationships,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({ title, subtitle }: { title: string; subtitle: string }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message }: { message: string }) => <div>Page Error: {message}</div>,
}));

vi.mock("@/components/knowledge-graph/graph-toolbar", () => ({
  GraphToolbar: ({
    hasSelection,
    onDepthChange,
    onLayoutChange,
    onSearchChange,
    onToggleType,
  }: {
    hasSelection: boolean;
    onDepthChange: (depth: number) => void;
    onLayoutChange: (layout: "force" | "hierarchical" | "circular") => void;
    onSearchChange: (query: string) => void;
    onToggleType: (type: "PERSON" | "ORG" | "PLACE" | "CONCEPT") => void;
  }) => (
    <div>
      <div>Toolbar selection {String(hasSelection)}</div>
      <button type="button" onClick={() => onLayoutChange("hierarchical")}>
        Layout hierarchy
      </button>
      <button type="button" onClick={() => onToggleType("PERSON")}>
        Toggle person
      </button>
      <button type="button" onClick={() => onSearchChange("Ada")}>
        Search Ada
      </button>
      <button type="button" onClick={() => onDepthChange(3)}>
        Set depth
      </button>
    </div>
  ),
}));

vi.mock("@/components/knowledge-graph/graph-canvas", () => ({
  GraphCanvas: ({
    entities,
    selectedEntityId,
    onSelectEntity,
  }: {
    entities: Entity[];
    selectedEntityId: string | null;
    onSelectEntity: (entityId: string | null) => void;
  }) => (
    <div>
      <div>Canvas with {entities.length} entities</div>
      <div>Selected {selectedEntityId ?? "none"}</div>
      <button type="button" onClick={() => onSelectEntity("entity-1")}>
        Select Ada
      </button>
      <button type="button" onClick={() => onSelectEntity(null)}>
        Clear selection
      </button>
    </div>
  ),
}));

describe("KnowledgeGraphPage", () => {
  beforeEach(() => {
    mocks.getEntities.mockReset();
    mocks.getEntityRelationships.mockReset();
    searchState.params = new URLSearchParams();
    searchState.setSearchParams.mockReset();
    searchState.setSearchParams.mockImplementation((next: Record<string, string>) => {
      searchState.params = new URLSearchParams(next);
    });
    useAppStore.setState({
      rightPanelOpen: false,
      rightPanelContent: null,
      inspectedEntity: null,
    });
  });

  it("renders the empty state when there are no entities", async () => {
    mocks.getEntities.mockResolvedValue([]);
    mocks.getEntityRelationships.mockResolvedValue([]);

    renderWithProviders(<KnowledgeGraphPage />);

    expect(await screen.findByText("No entities yet")).toBeInTheDocument();
  });

  it("renders the page error when graph loading fails", async () => {
    mocks.getEntities.mockRejectedValue(new Error("graph failed"));
    mocks.getEntityRelationships.mockRejectedValue(new Error("graph failed"));

    renderWithProviders(<KnowledgeGraphPage />);

    expect(await screen.findByText("Page Error: graph failed")).toBeInTheDocument();
  });

  it("renders the graph, selects entities, and keeps the global inspector state in sync", async () => {
    const user = userEvent.setup();
    const ada: Entity = {
      id: "entity-1",
      name: "Ada Lovelace",
      entity_type: "PERSON",
      canonical_name: null,
      mention_count: 12,
      first_seen: null,
      last_seen: null,
      metadata: {},
      created_at: "2026-03-01T09:00:00Z",
    };
    const babbage: Entity = {
      id: "entity-2",
      name: "Charles Babbage",
      entity_type: "PERSON",
      canonical_name: null,
      mention_count: 8,
      first_seen: null,
      last_seen: null,
      metadata: {},
      created_at: "2026-03-02T09:00:00Z",
    };
    const relationship: EntityRelationship = {
      id: "rel-1",
      source_entity_id: "entity-1",
      target_entity_id: "entity-2",
      relationship_type: "collaborated_with",
      valid_from: null,
      valid_to: null,
    };

    mocks.getEntities.mockResolvedValue([ada, babbage]);
    mocks.getEntityRelationships.mockResolvedValue([relationship]);

    renderWithProviders(<KnowledgeGraphPage />);

    expect(await screen.findByRole("heading", { name: "Knowledge Graph" })).toBeInTheDocument();
    expect(await screen.findByText("Canvas with 2 entities")).toBeInTheDocument();
    expect(screen.getByText("Toolbar selection false")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Layout hierarchy" }));
    await user.click(screen.getByRole("button", { name: "Search Ada" }));
    await user.click(screen.getByRole("button", { name: "Set depth" }));
    await user.click(screen.getByRole("button", { name: "Toggle person" }));
    await user.click(screen.getByRole("button", { name: "Toggle person" }));

    await user.click(screen.getByRole("button", { name: "Select Ada" }));
    await waitFor(() => {
      expect(useAppStore.getState().rightPanelContent).toBe("entity");
      expect(useAppStore.getState().inspectedEntity?.entity.name).toBe("Ada Lovelace");
      expect(useAppStore.getState().inspectedEntity?.relationships).toHaveLength(1);
    });

    await user.click(screen.getByRole("button", { name: "Select Ada" }));
    expect(useAppStore.getState().inspectedEntity?.entity.id).toBe("entity-1");

    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    await waitFor(() => {
      expect(useAppStore.getState().inspectedEntity).toBeNull();
      expect(useAppStore.getState().rightPanelOpen).toBe(false);
    });
  });

  it("starts with a selected entity from the query string and hydrates the inspector", async () => {
    const ada: Entity = {
      id: "entity-2",
      name: "Ada Lovelace",
      entity_type: "PERSON",
      canonical_name: null,
      mention_count: 12,
      first_seen: null,
      last_seen: null,
      metadata: {},
      created_at: "2026-03-01T09:00:00Z",
    };
    const missingRelated: EntityRelationship = {
      id: "rel-2",
      source_entity_id: "entity-2",
      target_entity_id: "entity-99",
      relationship_type: "mentioned_in",
      valid_from: null,
      valid_to: null,
    };

    searchState.params = new URLSearchParams("entity=entity-2");
    mocks.getEntities.mockResolvedValue([ada]);
    mocks.getEntityRelationships.mockResolvedValue([missingRelated]);

    renderWithProviders(<KnowledgeGraphPage />);

    await waitFor(() => {
      expect(useAppStore.getState().rightPanelContent).toBe("entity");
      expect(useAppStore.getState().inspectedEntity?.entity.id).toBe("entity-2");
      expect(useAppStore.getState().inspectedEntity?.relationships).toHaveLength(0);
    });
  });
});
