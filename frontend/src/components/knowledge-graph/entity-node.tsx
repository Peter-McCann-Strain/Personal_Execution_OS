import { memo, type ComponentType, type CSSProperties } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { User, Building, MapPin, Lightbulb } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EntityType } from "@/types";

export interface EntityNodeData {
  label: string;
  entityType: EntityType;
  mentionCount: number;
  canonicalName: string | null;
  [key: string]: unknown;
}

const ENTITY_STYLES: Record<
  EntityType,
  {
    color: string;
    icon: ComponentType<{ className?: string }>;
    shape: "circle" | "rounded-rect" | "diamond" | "hexagon";
  }
> = {
  PERSON: {
    color: "var(--color-agent-memory)",
    icon: User,
    shape: "circle",
  },
  ORG: {
    color: "var(--color-agent-comms)",
    icon: Building,
    shape: "rounded-rect",
  },
  PLACE: {
    color: "var(--color-success-500)",
    icon: MapPin,
    shape: "diamond",
  },
  CONCEPT: {
    color: "var(--color-agent-research)",
    icon: Lightbulb,
    shape: "hexagon",
  },
};

function computeSize(mentionCount: number, min: number, max: number): number {
  const scale = Math.min(Math.log2(mentionCount + 1) / Math.log2(50), 1.0);
  return min + (max - min) * scale;
}

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function PersonShape({ size, color, initials }: { size: number; color: string; initials: string }) {
  return (
    <div
      className="flex items-center justify-center rounded-full border-2 bg-[var(--color-bg-surface)]"
      style={{
        width: size,
        height: size,
        borderColor: color,
      }}
    >
      <span
        className="text-xs font-semibold"
        style={{ color, fontSize: Math.max(size * 0.28, 10) }}
      >
        {initials}
      </span>
    </div>
  );
}

function OrgShape({
  size,
  color,
  Icon,
}: {
  size: number;
  color: string;
  Icon: ComponentType<{ className?: string; style?: CSSProperties }>;
}) {
  const width = size * 1.4;
  const height = size * 0.8;
  return (
    <div
      className="flex items-center justify-center rounded-[var(--radius-md)] border-2 bg-[var(--color-bg-surface)]"
      style={{ width, height, borderColor: color }}
    >
      <Icon className="shrink-0" style={{ color, width: size * 0.35, height: size * 0.35 }} />
    </div>
  );
}

function DiamondShape({
  size,
  color,
  Icon,
}: {
  size: number;
  color: string;
  Icon: ComponentType<{ className?: string; style?: CSSProperties }>;
}) {
  return (
    <div
      className="flex items-center justify-center border-2 bg-[var(--color-bg-surface)]"
      style={{
        width: size,
        height: size,
        borderColor: color,
        transform: "rotate(45deg)",
      }}
    >
      <div style={{ transform: "rotate(-45deg)" }}>
        <Icon className="shrink-0" style={{ color, width: size * 0.35, height: size * 0.35 }} />
      </div>
    </div>
  );
}

function HexagonShape({
  size,
  color,
  Icon,
}: {
  size: number;
  color: string;
  Icon: ComponentType<{ className?: string; style?: CSSProperties }>;
}) {
  const points = Array.from({ length: 6 }, (_, i) => {
    const angle = (Math.PI / 3) * i - Math.PI / 2;
    const r = size / 2;
    return `${r + r * Math.cos(angle)},${r + r * Math.sin(angle)}`;
  }).join(" ");

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} className="absolute inset-0">
        <polygon points={points} fill="var(--color-bg-surface)" stroke={color} strokeWidth={2} />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <Icon className="shrink-0" style={{ color, width: size * 0.35, height: size * 0.35 }} />
      </div>
    </div>
  );
}

function EntityNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as EntityNodeData;
  const { label, entityType, mentionCount } = nodeData;
  const style = ENTITY_STYLES[entityType];
  const size = computeSize(mentionCount, 40, 100);

  return (
    <div className={cn("flex flex-col items-center gap-1 group")}>
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-transparent !border-0 !w-0 !h-0"
      />

      <div
        className={cn(
          "relative transition-transform duration-150",
          selected && "rounded-full",
          "group-hover:scale-110",
        )}
        style={{
          filter: selected ? `drop-shadow(0 0 8px ${style.color})` : undefined,
          outline: selected ? `2px solid ${style.color}` : undefined,
          outlineOffset: selected ? "3px" : undefined,
          borderRadius: selected ? "var(--radius-full)" : undefined,
        }}
        title={`${label} (${entityType}) - ${mentionCount} mentions`}
      >
        {style.shape === "circle" && (
          <PersonShape size={size} color={style.color} initials={getInitials(label)} />
        )}
        {style.shape === "rounded-rect" && (
          <OrgShape size={size} color={style.color} Icon={style.icon} />
        )}
        {style.shape === "diamond" && (
          <DiamondShape size={size} color={style.color} Icon={style.icon} />
        )}
        {style.shape === "hexagon" && (
          <HexagonShape size={size} color={style.color} Icon={style.icon} />
        )}
      </div>

      <span
        className={cn(
          "max-w-[120px] truncate text-center font-medium text-[var(--color-fg-primary)]",
          size < 60 ? "text-[10px]" : size < 80 ? "text-xs" : "text-sm",
        )}
      >
        {label}
      </span>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-transparent !border-0 !w-0 !h-0"
      />
    </div>
  );
}

export const EntityNode = memo(EntityNodeComponent);
