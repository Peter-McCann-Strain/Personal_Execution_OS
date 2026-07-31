import { useMemo } from "react";
import { ChevronDown, ChevronRight, Calendar, FileText, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { getPriorityColorClass, getProgressVariant } from "@/lib/colors";
import { formatDeadline } from "@/lib/date";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";
import { useTreeExpansion } from "@/hooks/use-tree-expansion";
import type { Goal, GoalStatus } from "@/types";

function PriorityDot({ priority }: { priority: number }) {
  return (
    <span
      className={cn(
        "inline-block h-2.5 w-2.5 rounded-full shrink-0",
        getPriorityColorClass(priority),
      )}
      title={`Priority: ${priority}`}
    />
  );
}

// ─── Status Badge ───────────────────────────────────────────

const goalStatusConfig: Record<
  GoalStatus,
  { label: string; variant: "success" | "warning" | "info" | "default" }
> = {
  active: { label: "Active", variant: "success" },
  paused: { label: "Paused", variant: "warning" },
  completed: { label: "Completed", variant: "info" },
  cancelled: { label: "Cancelled", variant: "default" },
};

function GoalStatusBadge({ status }: { status: GoalStatus }) {
  const config = goalStatusConfig[status] ?? { label: status, variant: "default" as const };
  return (
    <Badge variant={config.variant} size="sm">
      {config.label}
    </Badge>
  );
}

// ─── Build Tree from Flat List ──────────────────────────────

interface GoalNode extends Goal {
  children: GoalNode[];
}

function buildGoalTree(goals: Goal[]): GoalNode[] {
  const lookup = new Map<string, GoalNode>();
  const roots: GoalNode[] = [];

  for (const goal of goals) {
    lookup.set(goal.id, { ...goal, children: [] });
  }

  for (const goal of goals) {
    const node = lookup.get(goal.id)!;
    if (goal.parent_id && lookup.has(goal.parent_id)) {
      lookup.get(goal.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const sortByPriority = (a: GoalNode, b: GoalNode) => a.priority - b.priority;
  for (const node of lookup.values()) {
    node.children.sort(sortByPriority);
  }
  roots.sort(sortByPriority);

  return roots;
}

// ─── Goal Node Row ──────────────────────────────────────────

interface GoalNodeRowProps {
  node: GoalNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  onSelect?: (goal: Goal) => void;
}

function GoalNodeRow({ node, depth, expanded, onToggle, onSelect }: GoalNodeRowProps) {
  const hasChildren = node.children.length > 0;
  const isExpanded = expanded.has(node.id);

  return (
    <div>
      {/* Row */}
      <div
        className="group flex items-center gap-2 rounded-[var(--radius-md)] py-2 pr-3 transition-colors hover:bg-[var(--color-bg-overlay)] cursor-pointer"
        style={{ paddingLeft: `${depth * 24 + 8}px` }}
        onClick={() => {
          if (hasChildren) {
            onToggle(node.id);
          }
          onSelect?.(node);
        }}
      >
        {/* Expand/Collapse */}
        <span className="w-4 shrink-0 text-[var(--color-fg-tertiary)]">
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )
          ) : (
            <span className="inline-block w-4" />
          )}
        </span>

        {/* Priority dot */}
        <PriorityDot priority={node.priority} />

        {/* Left bar for visual hierarchy */}
        <div
          className={cn(
            "w-1 self-stretch rounded-full shrink-0",
            getPriorityColorClass(node.priority),
          )}
        />

        {/* Title */}
        <span className="flex-1 truncate text-sm font-medium text-[var(--color-fg-primary)]">
          {node.title}
        </span>

        {/* Status */}
        <GoalStatusBadge status={node.status} />

        {/* Progress bar */}
        <div className="hidden items-center gap-2 sm:flex">
          <Progress
            value={node.progress}
            colorVariant={getProgressVariant(node.progress)}
            className="h-1.5 w-20"
          />
          <span className="min-w-[2.5rem] text-right font-mono text-xs text-[var(--color-fg-tertiary)]">
            {Math.round(node.progress)}%
          </span>
        </div>

        {/* Deadline */}
        <span className="hidden items-center gap-1 text-xs text-[var(--color-fg-tertiary)] lg:flex">
          <Calendar className="h-3 w-3" />
          {formatDeadline(node.deadline)}
        </span>

        {/* Evidence count */}
        {(node.evidence ?? []).length > 0 && (
          <span className="hidden items-center gap-0.5 text-[10px] text-[var(--color-fg-disabled)] xl:flex">
            <FileText className="h-3 w-3" />
            {(node.evidence ?? []).length}
          </span>
        )}

        {/* Children count */}
        {hasChildren && (
          <span className="hidden items-center gap-0.5 text-[10px] text-[var(--color-fg-disabled)] xl:flex">
            <Users className="h-3 w-3" />
            {node.children.length}
          </span>
        )}
      </div>

      {/* Children */}
      {isExpanded &&
        node.children.map((child) => (
          <GoalNodeRow
            key={child.id}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            onToggle={onToggle}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

// ─── Goal Tree ──────────────────────────────────────────────

interface GoalTreeProps {
  goals: Goal[];
  onSelect?: (goal: Goal) => void;
}

function GoalTree({ goals, onSelect }: GoalTreeProps) {
  const tree = useMemo(() => buildGoalTree(goals), [goals]);
  const rootIds = useMemo(() => tree.map((n) => n.id), [tree]);
  const { expanded, toggleNode } = useTreeExpansion(rootIds);

  // Group by goal_type
  const grouped = useMemo(() => {
    const groups = new Map<string, GoalNode[]>();
    for (const node of tree) {
      const type = node.goal_type ?? "other";
      if (!groups.has(type)) groups.set(type, []);
      groups.get(type)!.push(node);
    }
    const typeOrder = ["life", "yearly", "quarterly", "monthly", "weekly", "other"];
    return typeOrder.filter((t) => groups.has(t)).map((t) => ({ type: t, goals: groups.get(t)! }));
  }, [tree]);

  if (goals.length === 0) {
    return <EmptyState icon={FileText} title="No goals defined yet" />;
  }

  return (
    <div className="space-y-6">
      {grouped.map(({ type, goals: groupGoals }) => (
        <div key={type}>
          {/* Group header */}
          <h3 className="mb-2 px-2 text-xs font-semibold uppercase tracking-widest text-[var(--color-fg-tertiary)]">
            {type === "other" ? "Uncategorized" : `${type} Goals`}
          </h3>

          {/* Goal rows */}
          <div className="space-y-0.5">
            {groupGoals.map((node) => (
              <GoalNodeRow
                key={node.id}
                node={node}
                depth={0}
                expanded={expanded}
                onToggle={toggleNode}
                onSelect={onSelect}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export { GoalTree, GoalStatusBadge, PriorityDot };
export type { GoalTreeProps };
