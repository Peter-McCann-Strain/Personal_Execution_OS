import { useCallback, useEffect, useMemo, type MouseEvent } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { EntityNode } from "./entity-node";
import type { EntityNodeData } from "./entity-node";
import type { LayoutType } from "./graph-toolbar";
import type { Entity, EntityRelationship, EntityType } from "@/types";

const nodeTypes: NodeTypes = {
  entity: EntityNode,
};

/**
 * Resolve a CSS custom property to its computed value.
 * React Flow renders edges as SVG <path> elements where oklch() CSS vars
 * may not resolve via inline styles in all browsers. Computing them
 * at render-time guarantees visible strokes.
 */
function resolveVar(prop: string): string {
  if (typeof window === "undefined") return prop;
  const raw = prop.replace(/^var\(/, "").replace(/\)$/, "");
  return getComputedStyle(document.documentElement).getPropertyValue(raw).trim() || prop;
}

type EdgeStyle = { strokeDasharray?: string; stroke: string; strokeWidth: number };

function resolvedEdgeStyles(): {
  map: Record<string, EdgeStyle>;
  fallback: EdgeStyle;
} {
  return {
    map: {
      works_at: { stroke: resolveVar("var(--color-fg-secondary)"), strokeWidth: 2 },
      knows: {
        strokeDasharray: "4 4",
        stroke: resolveVar("var(--color-fg-secondary)"),
        strokeWidth: 1.5,
      },
      related_to: {
        strokeDasharray: "6 3",
        stroke: resolveVar("var(--color-fg-tertiary)"),
        strokeWidth: 1.5,
      },
      mentioned_in: { stroke: resolveVar("var(--color-fg-tertiary)"), strokeWidth: 1 },
      manages: { stroke: resolveVar("var(--color-agent-project)"), strokeWidth: 2 },
      located_in: {
        strokeDasharray: "6 3",
        stroke: resolveVar("var(--color-success-500)"),
        strokeWidth: 1.5,
      },
      part_of: { stroke: resolveVar("var(--color-agent-comms)"), strokeWidth: 2 },
    },
    fallback: {
      strokeDasharray: "6 3",
      stroke: resolveVar("var(--color-fg-tertiary)"),
      strokeWidth: 1,
    },
  };
}

function seededRandom(seed: number) {
  return () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };
}

function forceDirectedLayout(
  entities: Entity[],
  relationships: EntityRelationship[],
): Array<{ x: number; y: number }> {
  const count = entities.length;
  const random = seededRandom(42);

  // Initialize positions in a circle for better convergence
  const radius = Math.max(300, count * 20);
  const positions = entities.map((_, i) => {
    const angle = (2 * Math.PI * i) / count;
    return {
      x: radius * Math.cos(angle) + radius,
      y: radius * Math.sin(angle) + radius,
    };
  });

  const idToIdx = new Map(entities.map((e, i) => [e.id, i]));
  const edgeList = relationships
    .map((r) => ({
      source: idToIdx.get(r.source_entity_id),
      target: idToIdx.get(r.target_entity_id),
    }))
    .filter(
      (e): e is { source: number; target: number } =>
        e.source !== undefined && e.target !== undefined,
    );

  // Run iterations
  const iterations = 80;
  const repulsion = 8000;
  const attraction = 0.005;
  const damping = 0.92;
  const velocities = positions.map(() => ({ x: 0, y: 0 }));

  for (let iter = 0; iter < iterations; iter++) {
    const temp = 1 - iter / iterations;

    // Repulsion between all pairs
    for (let i = 0; i < count; i++) {
      for (let j = i + 1; j < count; j++) {
        const dx = positions[i].x - positions[j].x;
        const dy = positions[i].y - positions[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy) + 1;
        const force = (repulsion * temp) / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        velocities[i].x += fx;
        velocities[i].y += fy;
        velocities[j].x -= fx;
        velocities[j].y -= fy;
      }
    }

    // Attraction along edges
    for (const edge of edgeList) {
      const dx = positions[edge.target].x - positions[edge.source].x;
      const dy = positions[edge.target].y - positions[edge.source].y;
      const dist = Math.sqrt(dx * dx + dy * dy) + 1;
      const force = dist * attraction;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      velocities[edge.source].x += fx;
      velocities[edge.source].y += fy;
      velocities[edge.target].x -= fx;
      velocities[edge.target].y -= fy;
    }

    // Apply velocities with damping
    for (let i = 0; i < count; i++) {
      velocities[i].x *= damping;
      velocities[i].y *= damping;
      positions[i].x += velocities[i].x;
      positions[i].y += velocities[i].y;
    }
  }

  // Add a small jitter to prevent exact overlaps for disconnected nodes
  for (let i = 0; i < count; i++) {
    positions[i].x += (random() - 0.5) * 5;
    positions[i].y += (random() - 0.5) * 5;
  }

  return positions;
}

function layoutNodes(
  entities: Entity[],
  layout: LayoutType,
  relationships: EntityRelationship[] = [],
): Array<{ x: number; y: number }> {
  const count = entities.length;
  if (count === 0) return [];

  switch (layout) {
    case "circular": {
      const radius = Math.max(200, count * 30);
      return entities.map((_, i) => {
        const angle = (2 * Math.PI * i) / count - Math.PI / 2;
        return {
          x: radius * Math.cos(angle) + radius,
          y: radius * Math.sin(angle) + radius,
        };
      });
    }
    case "hierarchical": {
      const typeOrder: EntityType[] = ["ORG", "PERSON", "PLACE", "CONCEPT"];
      const grouped = new Map<EntityType, Entity[]>();
      for (const e of entities) {
        const list = grouped.get(e.entity_type) ?? [];
        list.push(e);
        grouped.set(e.entity_type, list);
      }
      const positions: Array<{ x: number; y: number }> = [];
      const entityIndexMap = new Map(entities.map((e, i) => [e.id, i]));
      let row = 0;
      for (const type of typeOrder) {
        const group = grouped.get(type) ?? [];
        group.forEach((ent, col) => {
          const idx = entityIndexMap.get(ent.id)!;
          positions[idx] = { x: col * 180, y: row * 200 };
        });
        if (group.length > 0) row++;
      }
      // Fill any remaining with defaults
      for (let i = 0; i < count; i++) {
        if (!positions[i]) {
          positions[i] = { x: (i % 5) * 180, y: row * 200 };
        }
      }
      return positions;
    }
    case "force":
    default:
      return forceDirectedLayout(entities, relationships);
  }
}

interface GraphCanvasProps {
  entities: Entity[];
  relationships: EntityRelationship[];
  layout: LayoutType;
  enabledTypes: Set<EntityType>;
  searchQuery: string;
  selectedEntityId: string | null;
  onSelectEntity: (entityId: string | null) => void;
}

export function GraphCanvas({
  entities,
  relationships,
  layout,
  enabledTypes,
  searchQuery,
  selectedEntityId,
  onSelectEntity,
}: GraphCanvasProps) {
  const filteredEntities = useMemo(
    () => entities.filter((e) => enabledTypes.has(e.entity_type)),
    [entities, enabledTypes],
  );

  const entityIdSet = useMemo(() => new Set(filteredEntities.map((e) => e.id)), [filteredEntities]);

  const positions = useMemo(
    () => layoutNodes(filteredEntities, layout, relationships),
    [filteredEntities, layout, relationships],
  );

  const searchLower = searchQuery.toLowerCase();

  const initialNodes: Node[] = useMemo(
    () =>
      filteredEntities.map((entity, i) => {
        const isMatch = searchLower.length >= 2 && entity.name.toLowerCase().includes(searchLower);
        return {
          id: entity.id,
          type: "entity",
          position: positions[i]!,
          selected: entity.id === selectedEntityId,
          data: {
            label: entity.name,
            entityType: entity.entity_type,
            mentionCount: entity.mention_count,
            canonicalName: entity.canonical_name,
          } satisfies EntityNodeData,
          style: isMatch
            ? {
                filter: `drop-shadow(0 0 10px var(--color-info-500))`,
              }
            : undefined,
        };
      }),
    [filteredEntities, positions, selectedEntityId, searchLower],
  );

  const initialEdges: Edge[] = useMemo(() => {
    const { map, fallback } = resolvedEdgeStyles();
    const labelFill = resolveVar("var(--color-fg-tertiary)");
    const labelBg = resolveVar("var(--color-bg-surface)");
    return relationships
      .filter((r) => entityIdSet.has(r.source_entity_id) && entityIdSet.has(r.target_entity_id))
      .map((rel) => {
        const edgeStyle = map[rel.relationship_type] ?? fallback;
        return {
          id: rel.id,
          source: rel.source_entity_id,
          target: rel.target_entity_id,
          label: rel.relationship_type,
          labelStyle: { fontSize: 10, fill: labelFill },
          labelShowBg: true,
          labelBgStyle: {
            fill: labelBg,
            fillOpacity: 0.8,
          },
          style: {
            stroke: edgeStyle.stroke,
            strokeWidth: edgeStyle.strokeWidth,
            strokeDasharray: edgeStyle.strokeDasharray,
          },
          animated: false,
        };
      });
  }, [relationships, entityIdSet]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(
      filteredEntities.map((entity, i) => {
        const isMatch = searchLower.length >= 2 && entity.name.toLowerCase().includes(searchLower);
        return {
          id: entity.id,
          type: "entity" as const,
          position: positions[i]!,
          selected: entity.id === selectedEntityId,
          data: {
            label: entity.name,
            entityType: entity.entity_type,
            mentionCount: entity.mention_count,
            canonicalName: entity.canonical_name,
          } satisfies EntityNodeData,
          style: isMatch
            ? {
                filter: `drop-shadow(0 0 10px var(--color-info-500))`,
              }
            : undefined,
        };
      }),
    );
  }, [filteredEntities, positions, selectedEntityId, searchLower, setNodes]);

  useEffect(() => {
    const { map, fallback } = resolvedEdgeStyles();
    const labelFill = resolveVar("var(--color-fg-tertiary)");
    const labelBg = resolveVar("var(--color-bg-surface)");
    setEdges(
      relationships
        .filter((r) => entityIdSet.has(r.source_entity_id) && entityIdSet.has(r.target_entity_id))
        .map((rel) => {
          const edgeStyle = map[rel.relationship_type] ?? fallback;
          return {
            id: rel.id,
            source: rel.source_entity_id,
            target: rel.target_entity_id,
            label: rel.relationship_type,
            labelStyle: { fontSize: 10, fill: labelFill },
            labelShowBg: true,
            labelBgStyle: {
              fill: labelBg,
              fillOpacity: 0.8,
            },
            style: {
              stroke: edgeStyle.stroke,
              strokeWidth: edgeStyle.strokeWidth,
              strokeDasharray: edgeStyle.strokeDasharray,
            },
            animated: false,
          };
        }),
    );
  }, [relationships, entityIdSet, setEdges]);

  const handleNodeClick = useCallback(
    (_event: MouseEvent, node: Node) => {
      onSelectEntity(node.id);
    },
    [onSelectEntity],
  );

  const handlePaneClick = useCallback(() => {
    onSelectEntity(null);
  }, [onSelectEntity]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={4}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="var(--color-border-subtle)"
        />
        <MiniMap
          nodeStrokeColor="var(--color-border-default)"
          nodeColor="var(--color-bg-overlay)"
          maskColor="rgba(0, 0, 0, 0.5)"
          className="!bg-[var(--color-bg-surface)] !border-[var(--color-border-default)]"
        />
        <Controls className="!bg-[var(--color-bg-surface)] !border-[var(--color-border-default)] !shadow-none [&>button]:!bg-[var(--color-bg-surface)] [&>button]:!border-[var(--color-border-default)] [&>button]:!text-[var(--color-fg-secondary)] [&>button:hover]:!bg-[var(--color-bg-overlay)]" />
      </ReactFlow>
    </div>
  );
}
