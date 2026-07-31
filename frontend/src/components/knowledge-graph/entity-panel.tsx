import type { ReactNode } from "react";
import {
  X,
  User,
  Building,
  MapPin,
  Lightbulb,
  ArrowRight,
  Crosshair,
  Calendar,
} from "lucide-react";
import { cn, formatRelativeTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Entity, EntityRelationship } from "@/types";

const ENTITY_TYPE_CONFIG: Record<string, { label: string; icon: ReactNode; color: string }> = {
  PERSON: {
    label: "Person",
    icon: <User className="h-4 w-4" />,
    color: "var(--color-agent-memory)",
  },
  ORG: {
    label: "Organization",
    icon: <Building className="h-4 w-4" />,
    color: "var(--color-agent-comms)",
  },
  PLACE: {
    label: "Place",
    icon: <MapPin className="h-4 w-4" />,
    color: "var(--color-success-500)",
  },
  CONCEPT: {
    label: "Concept",
    icon: <Lightbulb className="h-4 w-4" />,
    color: "var(--color-agent-research)",
  },
};

interface EntityPanelProps {
  entity: Entity;
  relationships: Array<{
    relationship: EntityRelationship;
    relatedEntity: Entity;
  }>;
  onClose: () => void;
  onCenterOnGraph: (entityId: string) => void;
  onSelectEntity: (entityId: string) => void;
  className?: string;
}

export function EntityPanel({
  entity,
  relationships,
  onClose,
  onCenterOnGraph,
  onSelectEntity,
  className,
}: EntityPanelProps) {
  const config = ENTITY_TYPE_CONFIG[entity.entity_type] ?? ENTITY_TYPE_CONFIG.CONCEPT;
  const metadataEntries = Object.entries(entity.metadata).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  const firstSeen = entity.first_seen
    ? new Date(entity.first_seen).toLocaleDateString()
    : "Unknown";
  const lastSeen = entity.last_seen ? formatRelativeTime(entity.last_seen) : "Unknown";

  return (
    <div
      className={cn(
        "flex h-full w-80 flex-col border-l border-[var(--color-border-default)] bg-[var(--color-bg-surface)]",
        className,
      )}
    >
      <div className="flex items-start justify-between border-b border-[var(--color-border-subtle)] p-4">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-lg font-semibold text-[var(--color-fg-primary)]">
            {entity.name}
          </h2>
          <div className="mt-1 flex items-center gap-1.5">
            <span style={{ color: config.color }}>{config.icon}</span>
            <Badge size="sm">{config.label}</Badge>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-[var(--radius-md)] p-1 text-[var(--color-fg-tertiary)] transition-colors hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]"
          aria-label="Close panel"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Stats */}
        <div className="border-b border-[var(--color-border-subtle)] p-4">
          {entity.canonical_name && entity.canonical_name !== entity.name && (
            <div className="mb-2 text-xs text-[var(--color-fg-tertiary)]">
              Canonical: {entity.canonical_name}
            </div>
          )}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-[var(--color-fg-secondary)]">Mentions</span>
              <span className="font-medium text-[var(--color-fg-primary)]">
                {entity.mention_count}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)]">
              <div
                className="h-full rounded-[var(--radius-full)]"
                style={{
                  width: `${Math.min((entity.mention_count / 50) * 100, 100)}%`,
                  backgroundColor: config.color,
                }}
              />
            </div>
            <div className="flex items-center gap-1.5 text-xs text-[var(--color-fg-tertiary)]">
              <Calendar className="h-3 w-3" />
              First seen: {firstSeen}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-[var(--color-fg-tertiary)]">
              <Calendar className="h-3 w-3" />
              Last seen: {lastSeen}
            </div>
          </div>
        </div>

        {/* Relationships */}
        {relationships.length > 0 && (
          <div className="border-b border-[var(--color-border-subtle)] p-4">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Relationships ({relationships.length})
            </h3>
            <div className="space-y-2">
              {relationships.map(({ relationship, relatedEntity }) => {
                const isSource = relationship.source_entity_id === entity.id;
                const relConfig =
                  ENTITY_TYPE_CONFIG[relatedEntity.entity_type] ?? ENTITY_TYPE_CONFIG.CONCEPT;

                return (
                  <button
                    key={relationship.id}
                    type="button"
                    onClick={() => onSelectEntity(relatedEntity.id)}
                    className="flex w-full items-center gap-2 rounded-[var(--radius-md)] p-2 text-left transition-colors hover:bg-[var(--color-bg-overlay)]"
                  >
                    <span className="shrink-0 text-xs text-[var(--color-fg-tertiary)]">
                      {relationship.relationship_type}
                    </span>
                    <ArrowRight
                      className={cn(
                        "h-3 w-3 shrink-0 text-[var(--color-fg-disabled)]",
                        !isSource && "rotate-180",
                      )}
                    />
                    <span className="flex items-center gap-1 truncate text-sm text-[var(--color-fg-primary)]">
                      <span style={{ color: relConfig.color }}>{relConfig.icon}</span>
                      {relatedEntity.name}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Metadata */}
        {metadataEntries.length > 0 && (
          <div className="border-b border-[var(--color-border-subtle)] p-4">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Metadata
            </h3>
            <dl className="space-y-1.5">
              {metadataEntries.map(([key, value]) => (
                <div key={key} className="flex items-baseline gap-2 text-sm">
                  <dt className="shrink-0 text-[var(--color-fg-tertiary)]">{key}:</dt>
                  <dd className="truncate text-[var(--color-fg-primary)]">{String(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="border-t border-[var(--color-border-subtle)] p-4">
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => onCenterOnGraph(entity.id)}
        >
          <Crosshair className="h-4 w-4" />
          Center on Graph
        </Button>
      </div>
    </div>
  );
}
