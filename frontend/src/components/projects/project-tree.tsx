import { ChevronDown, ChevronRight, Layers, Milestone as MilestoneIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { getProgressVariant } from "@/lib/colors";
import { Progress } from "@/components/ui/progress";
import { EmptyState } from "@/components/ui/empty-state";
import { TaskCard } from "@/components/projects/task-card";
import { useTreeExpansion } from "@/hooks/use-tree-expansion";
import type { Project, Epic, Milestone, TaskStatus } from "@/types";

// ─── Helpers ────────────────────────────────────────────────

function milestoneProgress(milestone: Milestone): number {
  const total = (milestone.tasks ?? []).length;
  if (total === 0) return 0;
  const done = (milestone.tasks ?? []).filter((t) => t.status === "done").length;
  return Math.round((done / total) * 100);
}

function epicProgress(epic: Epic): number {
  const tasks = (epic.milestones ?? []).flatMap((m) => m.tasks ?? []);
  const total = tasks.length;
  if (total === 0) return 0;
  const done = tasks.filter((t) => t.status === "done").length;
  return Math.round((done / total) * 100);
}

// ─── Collapsible Node ───────────────────────────────────────

interface CollapsibleNodeProps {
  icon: React.ReactNode;
  title: string;
  progress: number;
  depth: number;
  isExpanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function CollapsibleNode({
  icon,
  title,
  progress,
  depth,
  isExpanded,
  onToggle,
  children,
}: CollapsibleNodeProps) {
  return (
    <div>
      {/* Node header */}
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "group flex w-full items-center gap-2 rounded-[var(--radius-md)] px-2 py-1.5 text-left transition-colors hover:bg-[var(--color-bg-overlay)]",
        )}
        style={{ paddingLeft: `${depth * 24 + 8}px` }}
      >
        {/* Expand chevron */}
        <span className="text-[var(--color-fg-tertiary)]">
          {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>

        {/* Icon */}
        <span className="text-[var(--color-fg-tertiary)]">{icon}</span>

        {/* Title */}
        <span className="flex-1 truncate text-sm font-medium text-[var(--color-fg-primary)]">
          {title}
        </span>

        {/* Mini progress */}
        <div className="flex items-center gap-2">
          <Progress
            value={progress}
            colorVariant={getProgressVariant(progress)}
            className="h-1 w-16"
          />
          <span className="min-w-[2rem] text-right font-mono text-xs text-[var(--color-fg-tertiary)]">
            {progress}%
          </span>
        </div>
      </button>

      {/* Children */}
      {isExpanded && <div>{children}</div>}
    </div>
  );
}

// ─── Milestone Node ─────────────────────────────────────────

interface MilestoneNodeProps {
  milestone: Milestone;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  onTaskStatusChange?: (taskId: string, status: TaskStatus) => void;
}

function MilestoneNode({ milestone, expanded, onToggle, onTaskStatusChange }: MilestoneNodeProps) {
  const progress = milestoneProgress(milestone);
  const isExpanded = expanded.has(milestone.id);

  return (
    <CollapsibleNode
      icon={<MilestoneIcon className="h-3.5 w-3.5" />}
      title={milestone.title}
      progress={progress}
      depth={2}
      isExpanded={isExpanded}
      onToggle={() => onToggle(milestone.id)}
    >
      <div className="space-y-0.5" style={{ paddingLeft: "72px" }}>
        {milestone.tasks
          .slice()
          .sort((a, b) => a.sort_order - b.sort_order)
          .map((task) => (
            <TaskCard key={task.id} task={task} onStatusChange={onTaskStatusChange} />
          ))}
      </div>
    </CollapsibleNode>
  );
}

// ─── Epic Node ──────────────────────────────────────────────

interface EpicNodeProps {
  epic: Epic;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  onTaskStatusChange?: (taskId: string, status: TaskStatus) => void;
}

function EpicNode({ epic, expanded, onToggle, onTaskStatusChange }: EpicNodeProps) {
  const progress = epicProgress(epic);
  const isExpanded = expanded.has(epic.id);

  return (
    <CollapsibleNode
      icon={<Layers className="h-3.5 w-3.5" />}
      title={epic.title}
      progress={progress}
      depth={0}
      isExpanded={isExpanded}
      onToggle={() => onToggle(epic.id)}
    >
      {epic.milestones
        .slice()
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((milestone) => (
          <MilestoneNode
            key={milestone.id}
            milestone={milestone}
            expanded={expanded}
            onToggle={onToggle}
            onTaskStatusChange={onTaskStatusChange}
          />
        ))}
    </CollapsibleNode>
  );
}

// ─── Project Tree ───────────────────────────────────────────

interface ProjectTreeProps {
  project: Project;
  onTaskStatusChange?: (taskId: string, status: TaskStatus) => void;
}

function ProjectTree({ project, onTaskStatusChange }: ProjectTreeProps) {
  const allIds = project.epics.flatMap((e) => [e.id, ...e.milestones.map((m) => m.id)]);
  const { expanded, toggleNode, expandAll, collapseAll } = useTreeExpansion(allIds);

  if (project.epics.length === 0) {
    return <EmptyState icon={Layers} title="No epics defined yet" />;
  }

  return (
    <div className="space-y-1">
      {/* Controls */}
      <div className="mb-3 flex items-center gap-2">
        <button
          type="button"
          onClick={() => expandAll(allIds)}
          className="text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
        >
          Expand All
        </button>
        <span className="text-[var(--color-fg-disabled)]">/</span>
        <button
          type="button"
          onClick={collapseAll}
          className="text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
        >
          Collapse All
        </button>
      </div>

      {/* Tree */}
      {project.epics
        .slice()
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((epic) => (
          <EpicNode
            key={epic.id}
            epic={epic}
            expanded={expanded}
            onToggle={toggleNode}
            onTaskStatusChange={onTaskStatusChange}
          />
        ))}
    </div>
  );
}

export { ProjectTree };
export type { ProjectTreeProps };
