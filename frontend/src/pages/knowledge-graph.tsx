import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { Network } from "lucide-react";
import { GraphCanvas } from "@/components/knowledge-graph/graph-canvas";
import { GraphToolbar } from "@/components/knowledge-graph/graph-toolbar";
import type { LayoutType } from "@/components/knowledge-graph/graph-toolbar";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { getEntities, getEntityRelationships } from "@/api/memory";
import { useAppStore } from "@/stores/app";
import type { Entity, EntityType } from "@/types";

function GraphSkeleton() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-[var(--color-bg-base)]">
      <div className="flex flex-col items-center gap-4">
        <Skeleton className="h-64 w-64 rounded-full" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-4 w-32" />
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]">
        <Network className="h-8 w-8 text-[var(--color-fg-tertiary)]" />
      </div>
      <div className="space-y-2">
        <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">No entities yet</h2>
        <p className="max-w-md text-sm text-[var(--color-fg-secondary)]">
          Entities are automatically extracted from your diary entries and notes. Start journaling
          to build your knowledge graph.
        </p>
      </div>
    </div>
  );
}

export function KnowledgeGraphPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const entityParam = searchParams.get("entity");
  const openRightPanel = useAppStore((s) => s.openRightPanel);
  const closeRightPanel = useAppStore((s) => s.closeRightPanel);
  const rightPanelContent = useAppStore((s) => s.rightPanelContent);
  const setInspectedEntity = useAppStore((s) => s.setInspectedEntity);
  const shouldOpenInspectorRef = useRef(entityParam !== null);

  const [layout, setLayout] = useState<LayoutType>("force");
  const [enabledTypes, setEnabledTypes] = useState<Set<EntityType>>(
    new Set(["PERSON", "ORG", "PLACE", "CONCEPT"]),
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [depth, setDepth] = useState(2);
  const selectedEntityId = entityParam;

  const entitiesQuery = useQuery({
    queryKey: ["entities"],
    queryFn: () => getEntities({ limit: 500 }),
  });

  const relationshipsQuery = useQuery({
    queryKey: ["entity-relationships"],
    queryFn: getEntityRelationships,
  });

  const entities = useMemo(() => entitiesQuery.data ?? [], [entitiesQuery.data]);
  const relationships = useMemo(() => relationshipsQuery.data ?? [], [relationshipsQuery.data]);

  const selectedEntity = useMemo(
    () => entities.find((e) => e.id === selectedEntityId) ?? null,
    [entities, selectedEntityId],
  );

  const entityMap = useMemo(() => new Map(entities.map((e) => [e.id, e])), [entities]);

  const selectedRelationships = useMemo(() => {
    if (!selectedEntityId) return [];
    return relationships
      .filter(
        (r) => r.source_entity_id === selectedEntityId || r.target_entity_id === selectedEntityId,
      )
      .map((r) => {
        const relatedId =
          r.source_entity_id === selectedEntityId ? r.target_entity_id : r.source_entity_id;
        const relatedEntity = entityMap.get(relatedId);
        if (!relatedEntity) return null;
        return { relationship: r, relatedEntity };
      })
      .filter(
        (item): item is { relationship: (typeof relationships)[0]; relatedEntity: Entity } =>
          item !== null,
      );
  }, [selectedEntityId, relationships, entityMap]);

  const handleSelectEntity = useCallback(
    (entityId: string | null) => {
      if (entityId) {
        const entity = entityMap.get(entityId);
        if (entity) {
          const relationshipsForEntity = relationships
            .filter((r) => r.source_entity_id === entityId || r.target_entity_id === entityId)
            .map((r) => {
              const relatedId =
                r.source_entity_id === entityId ? r.target_entity_id : r.source_entity_id;
              const relatedEntity = entityMap.get(relatedId);
              if (!relatedEntity) return null;
              return { relationship: r, relatedEntity };
            })
            .filter(
              (
                item,
              ): item is {
                relationship: (typeof relationships)[0];
                relatedEntity: Entity;
              } => item !== null,
            );

          setInspectedEntity({
            entity,
            relationships: relationshipsForEntity,
          });
          openRightPanel("entity");
        }
        shouldOpenInspectorRef.current = true;
        setSearchParams({ entity: entityId });
      } else {
        setInspectedEntity(null);
        if (rightPanelContent === "entity") {
          closeRightPanel();
        }
        setSearchParams({});
      }
    },
    [
      closeRightPanel,
      entityMap,
      openRightPanel,
      relationships,
      rightPanelContent,
      setInspectedEntity,
      setSearchParams,
    ],
  );

  const handleToggleType = useCallback((type: EntityType) => {
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  const isLoading = entitiesQuery.isLoading || relationshipsQuery.isLoading;
  const isError = entitiesQuery.isError || relationshipsQuery.isError;
  const errorMessage =
    entitiesQuery.error?.message ??
    relationshipsQuery.error?.message ??
    "Failed to load knowledge graph";
  const isEmpty = !isLoading && !isError && entities.length === 0;

  useEffect(() => {
    if (entityParam) {
      shouldOpenInspectorRef.current = true;
      return;
    }

    setInspectedEntity(null);
    if (rightPanelContent === "entity") {
      closeRightPanel();
    }
  }, [closeRightPanel, entityParam, rightPanelContent, setInspectedEntity]);

  useEffect(() => {
    if (!selectedEntity) {
      return;
    }

    setInspectedEntity({
      entity: selectedEntity,
      relationships: selectedRelationships,
    });

    if (shouldOpenInspectorRef.current) {
      openRightPanel("entity");
      shouldOpenInspectorRef.current = false;
    }
  }, [openRightPanel, selectedEntity, selectedRelationships, setInspectedEntity]);

  return (
    <PageTransition className="flex h-full flex-col">
      <div className="shrink-0 px-4 pt-4 pb-2">
        <PageHeader
          title="Knowledge Graph"
          subtitle="Entities and relationships"
          icon={Network}
          agentColor="memory"
        />
        <GraphToolbar
          layout={layout}
          onLayoutChange={setLayout}
          enabledTypes={enabledTypes}
          onToggleType={handleToggleType}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          depth={depth}
          onDepthChange={setDepth}
          hasSelection={selectedEntityId !== null}
        />
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1">
          {isLoading && <GraphSkeleton />}
          {isError && (
            <PageError
              message={errorMessage}
              onRetry={() => {
                entitiesQuery.refetch();
                relationshipsQuery.refetch();
              }}
              context="the knowledge graph"
              icon={Network}
            />
          )}
          {isEmpty && <EmptyState />}
          {!isLoading && !isError && !isEmpty && (
            <GraphCanvas
              entities={entities}
              relationships={relationships}
              layout={layout}
              enabledTypes={enabledTypes}
              searchQuery={searchQuery}
              selectedEntityId={selectedEntityId}
              onSelectEntity={handleSelectEntity}
            />
          )}
        </div>
      </div>
    </PageTransition>
  );
}
