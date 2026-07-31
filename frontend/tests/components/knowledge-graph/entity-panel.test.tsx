import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { EntityPanel } from "@/components/knowledge-graph/entity-panel";
import type { Entity, EntityRelationship } from "@/types";

describe("EntityPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-08T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders entity metadata, relationships, and forwards actions", async () => {
    const onClose = vi.fn();
    const onCenterOnGraph = vi.fn();
    const onSelectEntity = vi.fn();

    const entity: Entity = {
      id: "entity-1",
      name: "Ada Lovelace",
      entity_type: "PERSON",
      canonical_name: "Augusta Ada Lovelace",
      mention_count: 12,
      first_seen: "2026-03-01T09:00:00Z",
      last_seen: "2026-04-08T10:00:00Z",
      metadata: { role: "Mathematician", country: "UK", empty: "" },
      created_at: "2026-03-01T09:00:00Z",
    };

    const relationship: EntityRelationship = {
      id: "rel-1",
      source_entity_id: "entity-1",
      target_entity_id: "entity-2",
      relationship_type: "collaborated_with",
      valid_from: null,
      valid_to: null,
    };

    const relatedEntity: Entity = {
      id: "entity-2",
      name: "Charles Babbage",
      entity_type: "PERSON",
      canonical_name: null,
      mention_count: 5,
      first_seen: null,
      last_seen: null,
      metadata: {},
      created_at: "2026-03-02T09:00:00Z",
    };

    renderWithProviders(
      <EntityPanel
        entity={entity}
        relationships={[{ relationship, relatedEntity }]}
        onClose={onClose}
        onCenterOnGraph={onCenterOnGraph}
        onSelectEntity={onSelectEntity}
      />,
    );

    expect(screen.getByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByText("Canonical: Augusta Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Mathematician")).toBeInTheDocument();
    expect(screen.getByText("UK")).toBeInTheDocument();
    expect(screen.getByText("Charles Babbage")).toBeInTheDocument();

    screen.getByRole("button", { name: /Charles Babbage/i }).click();
    expect(onSelectEntity).toHaveBeenCalledWith("entity-2");

    screen.getByRole("button", { name: "Center on Graph" }).click();
    expect(onCenterOnGraph).toHaveBeenCalledWith("entity-1");

    screen.getByRole("button", { name: "Close panel" }).click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("falls back for unknown entity types and handles empty metadata/relationships", () => {
    const onClose = vi.fn();
    const onCenterOnGraph = vi.fn();
    const onSelectEntity = vi.fn();

    const entity: Entity = {
      id: "entity-3",
      name: "Mystery Node",
      entity_type: "MYSTERY" as Entity["entity_type"],
      canonical_name: null,
      mention_count: 1,
      first_seen: null,
      last_seen: null,
      metadata: {},
      created_at: "2026-03-03T09:00:00Z",
    };

    const relationship: EntityRelationship = {
      id: "rel-2",
      source_entity_id: "entity-4",
      target_entity_id: "entity-3",
      relationship_type: "linked_to",
      valid_from: null,
      valid_to: null,
    };

    const relatedEntity: Entity = {
      id: "entity-4",
      name: "Related Node",
      entity_type: "MYSTERY" as Entity["entity_type"],
      canonical_name: null,
      mention_count: 2,
      first_seen: null,
      last_seen: null,
      metadata: {},
      created_at: "2026-03-04T09:00:00Z",
    };

    renderWithProviders(
      <EntityPanel
        entity={entity}
        relationships={[{ relationship, relatedEntity }]}
        onClose={onClose}
        onCenterOnGraph={onCenterOnGraph}
        onSelectEntity={onSelectEntity}
      />,
    );

    expect(screen.getByText("Mystery Node")).toBeInTheDocument();
    expect(screen.getByText("Concept")).toBeInTheDocument();
    expect(screen.getByText("First seen: Unknown")).toBeInTheDocument();
    expect(screen.getByText("Last seen: Unknown")).toBeInTheDocument();
    expect(screen.getByText("Related Node")).toBeInTheDocument();

    screen.getByRole("button", { name: /Related Node/i }).click();
    expect(onSelectEntity).toHaveBeenCalledWith("entity-4");
  });
});
